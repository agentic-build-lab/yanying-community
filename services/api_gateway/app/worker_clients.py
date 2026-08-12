import json
import threading
import time
from collections.abc import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from uuid import uuid4

from .cover_designer import CoverDesignError, create_designed_cover
from .job_records import RenderJobCreate
from .runtime_config import runtime_config
from .tts_bridge import TtsGenerateRequest

_legacy_tts_lock = threading.Lock()
PipelineProgressCallback = Callable[[str, str, int, str, dict[str, object] | None], None]


def get_json(url: str, timeout: int = 3) -> dict[str, object] | None:
    try:
        with urlopen(url, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
            return payload if isinstance(payload, dict) else None
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
    except (OSError, URLError, json.JSONDecodeError):
        return None


def post_json(url: str, payload: dict[str, object], timeout: int = 180) -> dict[str, object] | None:
    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, json.JSONDecodeError):
        return None


def post_json_required(
    url: str, payload: dict[str, object], timeout: int = 180
) -> dict[str, object]:
    result = post_json(url, payload, timeout=timeout)
    if result is None:
        return {
            "status": "failed",
            "message": f"Request failed or returned invalid JSON: {url}",
        }
    return result


def post_tts_job(payload: TtsGenerateRequest) -> dict[str, object] | None:
    if not runtime_config.enable_tts_worker:
        return None

    return post_json(
        f"{runtime_config.tts_worker_url}/api/tts/jobs",
        payload.model_dump(),
        timeout=runtime_config.tts_worker_timeout_sec,
    )


def default_legacy_prompt_audio() -> str:
    if not runtime_config.enable_legacy_adapter:
        return ""
    result = get_json(
        f"{runtime_config.legacy_adapter_url.rstrip('/')}/api/legacy/proxy/voices/",
        timeout=8,
    )
    items = result.get("data") if isinstance(result, dict) else None
    if not isinstance(items, list):
        return ""
    for item in items:
        if not isinstance(item, dict):
            continue
        prompt_audio = str(item.get("audio_file") or item.get("url") or "").strip()
        if prompt_audio:
            return prompt_audio
    return ""


def post_tts_job_resilient(payload: TtsGenerateRequest) -> dict[str, object] | None:
    result = post_tts_job(payload)
    if payload.dry_run or (isinstance(result, dict) and result.get("status") == "completed"):
        return result

    prompt_audio = default_legacy_prompt_audio()
    if not prompt_audio:
        return result
    fallback = generate_legacy_audio(
        text=payload.text,
        prompt_audio=prompt_audio,
        speed=payload.speed,
        timeout_sec=runtime_config.legacy_adapter_timeout_sec,
    )
    if fallback.get("status") == "completed":
        fallback["fallback_from"] = "edge_neural"
        fallback["message"] = "Online TTS was unavailable; local V1 voice fallback completed."
        return fallback
    return result or fallback


def generate_legacy_audio(
    *,
    text: str,
    prompt_audio: str,
    speed: float,
    timeout_sec: int | None = None,
) -> dict[str, object]:
    if not runtime_config.enable_legacy_adapter:
        return {"status": "failed", "message": "Legacy adapter is disabled."}
    if not text.strip() or not prompt_audio.strip():
        return {"status": "failed", "message": "Legacy voice requires text and prompt_audio."}
    prompt_url = urlparse(prompt_audio)
    if prompt_url.scheme not in {"http", "https"} or prompt_url.hostname not in {
        "127.0.0.1",
        "localhost",
    }:
        return {
            "status": "failed",
            "message": "Legacy prompt audio must use the local legacy engine.",
        }

    timeout = timeout_sec or runtime_config.legacy_adapter_timeout_sec
    base_url = runtime_config.legacy_adapter_url.rstrip("/")
    with _legacy_tts_lock:
        start_result = post_json(
            f"{base_url}/api/legacy/proxy/audio/generate/",
            {
                "version": "1",
                "emo": "",
                "tts_type": "direct",
                "text": text,
                "speed": speed,
                "prompt_audio": prompt_audio,
                "pause": {"pause1": 0, "pause2": 0},
            },
            timeout=30,
        )
        if not start_result or start_result.get("code") != 0:
            return {
                "status": "failed",
                "message": (start_result or {}).get(
                    "message", "Legacy voice task could not be started."
                ),
            }

        deadline = time.monotonic() + timeout
        result_url = ""
        while time.monotonic() < deadline:
            progress = get_json(f"{base_url}/api/legacy/proxy/audio/progress/", timeout=15)
            if not progress or progress.get("code") != 0:
                time.sleep(1)
                continue
            progress_data = progress.get("data")
            if isinstance(progress_data, dict):
                status = str(progress_data.get("status", "")).lower()
                if status in {"failed", "error"}:
                    return {
                        "status": "failed",
                        "message": progress_data.get("message", "Legacy voice task failed."),
                    }
                if status in {"done", "success", "completed"}:
                    result_url = str(progress_data.get("url") or "")
                    break
            time.sleep(1)

        if not result_url:
            return {
                "status": "failed",
                "message": "Legacy voice task timed out or returned no audio URL.",
            }

        parsed_url = urlparse(result_url)
        if parsed_url.scheme not in {"http", "https"} or parsed_url.hostname not in {
            "127.0.0.1",
            "localhost",
        }:
            return {"status": "failed", "message": "Legacy voice returned a non-local audio URL."}

        output_dir = runtime_config.output_root / "tts"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"legacy_voice_{uuid4().hex[:12]}.wav"
        try:
            with urlopen(result_url, timeout=30) as response:
                audio_bytes = response.read()
        except (OSError, URLError) as exc:
            return {"status": "failed", "message": f"Legacy audio download failed: {exc}"}
        if len(audio_bytes) <= 44:
            return {"status": "failed", "message": "Legacy voice returned an empty audio file."}
        output_path.write_bytes(audio_bytes)
        return {
            "status": "completed",
            "provider": "legacy_v1_voice",
            "audio_path": str(output_path),
            "source_url": result_url,
        }


def _track_legacy_avatar_progress(
    stop_event: threading.Event,
    on_progress: PipelineProgressCallback,
) -> None:
    seen_active = False
    progress_url = (
        f"{runtime_config.legacy_adapter_url.rstrip('/')}"
        "/api/legacy/proxy/video/meta_human_video/progress/"
    )
    while not stop_event.wait(1):
        response = get_json(progress_url, timeout=8)
        data = response.get("data") if isinstance(response, dict) else None
        if not isinstance(data, dict):
            continue
        status = str(data.get("status") or "").lower()
        try:
            raw_progress = float(data.get("data"))
        except (TypeError, ValueError):
            raw_progress = 0
        if status not in {"done", "success", "completed"} or raw_progress < 100:
            seen_active = True
        if not seen_active:
            continue
        mapped_progress = min(75, 25 + round(max(0, min(100, raw_progress)) * 0.5))
        if status in {"done", "success", "completed"} and raw_progress >= 100:
            progress_message = "源引擎口型匹配已完成，正在下载并校验视频"
        else:
            progress_message = f"正在进行口型匹配，源引擎进度 {round(raw_progress)}%"
        on_progress(
            "avatar",
            "running",
            mapped_progress,
            progress_message,
            None,
        )


def run_pipeline(
    payload: RenderJobCreate,
    on_progress: PipelineProgressCallback | None = None,
) -> list[dict[str, object]]:
    stages: list[dict[str, object]] = []
    emit = on_progress or (lambda stage, status, progress, message, result: None)

    tts_result = None
    emit("tts", "running", 5, "正在生成口播语音", None)
    if payload.voice_source == "legacy_engine" and payload.dry_run:
        tts_result = {"status": "completed", "provider": "legacy_v1_voice", "dry_run": True}
    elif payload.voice_source == "legacy_engine":
        tts_result = generate_legacy_audio(
            text=payload.script,
            prompt_audio=payload.legacy_prompt_audio or "",
            speed=payload.speed,
            timeout_sec=runtime_config.legacy_adapter_timeout_sec,
        )
    elif runtime_config.enable_tts_worker:
        tts_result = post_tts_job_resilient(
            TtsGenerateRequest(
                text=payload.script,
                voice_id=payload.voice_id,
                speed=payload.speed,
                dry_run=payload.dry_run,
            )
        )
        if tts_result is None:
            tts_result = {
                "status": "failed",
                "message": (
                    "TTS worker request failed or timed out after "
                    f"{runtime_config.tts_worker_timeout_sec} seconds."
                ),
            }
    tts_status = _stage_status(tts_result)
    stages.append({"stage": "tts", "status": tts_status, "result": tts_result})
    emit(
        "tts",
        tts_status,
        20 if tts_status == "completed" else 5,
        "口播语音已生成" if tts_status == "completed" else "口播语音生成失败",
        tts_result,
    )
    audio_path = tts_result.get("audio_path") if isinstance(tts_result, dict) else None

    if not payload.dry_run and not audio_path:
        if isinstance(tts_result, dict) and tts_result.get("status") != "failed":
            stages[-1] = {
                "stage": "tts",
                "status": "failed",
                "result": {
                    **tts_result,
                    "status": "failed",
                    "message": "TTS completed without audio_path.",
                },
            }
        stages.append({"stage": "avatar", "status": "skipped", "result": None})
        stages.append({"stage": "render", "status": "skipped", "result": None})
        emit("avatar", "skipped", 20, "因语音生成失败，已跳过口型匹配", None)
        emit("render", "skipped", 20, "因语音生成失败，已跳过字幕与合成", None)
        return stages

    avatar_result = None
    emit("avatar", "running", 25, "正在驱动数字人并匹配口型", None)
    avatar_tracker_stop = threading.Event()
    avatar_tracker = None
    if payload.avatar_source in {"legacy_video_avatar", "original_engine", "legacy_template"}:
        avatar_tracker = threading.Thread(
            target=_track_legacy_avatar_progress,
            args=(avatar_tracker_stop, emit),
            daemon=True,
            name="legacy-avatar-progress",
        )
        avatar_tracker.start()
    if runtime_config.enable_avatar_worker:
        try:
            avatar_result = post_json(
                f"{runtime_config.avatar_worker_url}/api/avatar/jobs",
                {
                    "project_id": payload.project_id,
                    "script": payload.script,
                    "avatar_id": payload.avatar_id,
                    "avatar_source": payload.avatar_source,
                    "audio_path": audio_path,
                    "image_prompt": payload.image_prompt,
                    "image_path": payload.image_path,
                    "dry_run": payload.dry_run,
                },
                timeout=runtime_config.avatar_worker_timeout_sec,
            )
        finally:
            avatar_tracker_stop.set()
            if avatar_tracker is not None:
                avatar_tracker.join(timeout=2)
    else:
        avatar_tracker_stop.set()
        if avatar_tracker is not None:
            avatar_tracker.join(timeout=2)
    if avatar_result is None:
        avatar_result = {
            "status": "failed",
            "message": ("数字人工作进程超时或未返回结果，已停止后续合成，不会改用其他人物模板。"),
        }
    avatar_status = _stage_status(avatar_result)
    stages.append({"stage": "avatar", "status": avatar_status, "result": avatar_result})
    emit(
        "avatar",
        avatar_status,
        80 if avatar_status == "completed" else 25,
        "数字人口型视频已生成" if avatar_status == "completed" else "数字人口型生成失败",
        avatar_result,
    )
    image_path = avatar_result.get("image_path") if isinstance(avatar_result, dict) else None
    video_path = avatar_result.get("video_path") if isinstance(avatar_result, dict) else None
    render_audio_path = (
        avatar_result.get("audio_path")
        if isinstance(avatar_result, dict) and avatar_result.get("audio_path")
        else audio_path
    )

    missing_avatar_output = not video_path and not image_path
    if avatar_status != "completed" or (missing_avatar_output and not payload.dry_run):
        if avatar_status == "completed" and missing_avatar_output:
            avatar_result = {
                **avatar_result,
                "status": "failed",
                "message": "数字人阶段没有返回视频或人物图片，已停止后续合成。",
            }
            stages[-1] = {"stage": "avatar", "status": "failed", "result": avatar_result}
            emit(
                "avatar",
                "failed",
                25,
                str(avatar_result["message"]),
                avatar_result,
            )
        stages.append({"stage": "render", "status": "skipped", "result": None})
        emit(
            "render",
            "skipped",
            25,
            "因数字人视频未生成，已跳过字幕烧录与成片合成",
            None,
        )
        return stages

    render_result = None
    emit("render", "running", 85, "正在烧录字幕、封面并合成成片", None)
    if runtime_config.enable_render_worker:
        render_result = post_json(
            f"{runtime_config.render_worker_url}/api/render/jobs",
            {
                "project_id": payload.project_id,
                "output_category": payload.output_category,
                "video_path": video_path,
                "image_path": image_path,
                "audio_path": render_audio_path,
                "subtitle_text": payload.script,
                "subtitle_segments": (
                    tts_result.get("subtitle_segments", []) if isinstance(tts_result, dict) else []
                ),
                "subtitle_template": payload.subtitle_template,
                "target_format": payload.target_format,
                "burn_subtitles": payload.burn_subtitles,
                "make_cover": payload.make_cover,
                "dry_run": payload.dry_run,
            },
            timeout=runtime_config.render_worker_timeout_sec,
        )
    if (
        isinstance(render_result, dict)
        and render_result.get("status") == "completed"
        and payload.make_cover
        and render_result.get("cover_path")
    ):
        try:
            designed_cover = create_designed_cover(
                image_source=str(render_result["cover_path"]),
                title_line_1=payload.cover_title_line_1 or payload.script[:10],
                title_line_2=payload.cover_title_line_2 or payload.script[10:20],
                style=payload.cover_style,
                target_format=payload.target_format,
                accent_color=payload.cover_accent_color,
                media_root=runtime_config.output_root,
            )
            render_result["frame_cover_path"] = render_result["cover_path"]
            render_result["cover_path"] = designed_cover["image_path"]
            render_result["designed_cover"] = designed_cover
        except CoverDesignError as exc:
            render_result["cover_warning"] = str(exc)
    render_status = _stage_status(render_result)
    stages.append({"stage": "render", "status": render_status, "result": render_result})
    emit(
        "render",
        render_status,
        99 if render_status == "completed" else 85,
        "成片合成完成" if render_status == "completed" else "成片合成失败",
        render_result,
    )

    return stages


def _stage_status(result: dict[str, object] | None) -> str:
    if result is None:
        return "skipped"

    status = result.get("status")
    if status in {"completed", "failed", "queued", "running"}:
        return str(status)

    return "completed"
