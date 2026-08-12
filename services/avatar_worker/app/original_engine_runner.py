import json
import mimetypes
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urljoin, urlparse
from urllib.request import Request, urlopen
from uuid import uuid4

from .runtime_config import avatar_worker_config


class OriginalEngineError(RuntimeError):
    pass


AVATAR_TO_META_HUMAN: dict[str, str] = {}
REMOVED_NONCOMMERCIAL_META_HUMANS = {
    "坐姿测试数字人.mp4",
    "站立测试数字人.mp4",
}
META_HUMAN_AVATAR_PREFIX = "original_meta_human:"


def is_original_engine_available() -> bool:
    try:
        response = _request_json("/algorithm/status/", timeout=2)
    except OriginalEngineError:
        return False

    data = response.get("data") if isinstance(response, dict) else None
    if not isinstance(data, dict):
        return False

    return data.get("video_status") == "open" or data.get("video_sync_status") == "open"


def list_original_meta_humans() -> list[dict[str, object]]:
    response = _request_json("/meta_human/", timeout=5)
    if response.get("code") != 0:
        raise OriginalEngineError(
            _response_message(response, "Original engine rejected the meta-human list request.")
        )

    data = response.get("data")
    if not isinstance(data, list):
        raise OriginalEngineError("Original engine returned an invalid meta-human list.")

    items = []
    for item in data:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        if name in REMOVED_NONCOMMERCIAL_META_HUMANS:
            continue
        video_info = item.get("video_info") if isinstance(item.get("video_info"), dict) else {}
        items.append(
            {
                "avatar_id": _avatar_id_for_meta_human_name(name),
                "name": name,
                "type": item.get("type") or "sync",
                "cover_url": item.get("cover"),
                "video_url": item.get("video"),
                "width": video_info.get("width"),
                "height": video_info.get("height"),
                "license_status": "test_only" if "测试" in name else "unknown",
                "source": "original_engine",
            }
        )
    return items


def import_original_meta_human(
    *, video_path: Path, name: str, meta_human_type: str = "sync"
) -> dict[str, object]:
    if not video_path.exists():
        raise OriginalEngineError(f"Meta-human source video not found: {video_path}")
    if video_path.suffix.lower() not in {".mp4", ".mov", ".mkv"}:
        raise OriginalEngineError("Original engine only accepts mp4, mov, or mkv source videos.")
    if not name.strip():
        raise OriginalEngineError("Meta-human import requires a non-empty name.")

    content_type = mimetypes.guess_type(video_path.name)[0] or "video/mp4"
    fields = {
        "type": meta_human_type,
        "name": name.strip(),
    }
    files = {
        "file": (video_path.name, content_type, video_path.read_bytes()),
    }
    body, content_type_header = _encode_multipart(fields, files)
    request = Request(
        urljoin(_base_url(), "meta_human/"),
        data=body,
        headers={"Content-Type": content_type_header},
        method="POST",
    )

    try:
        with urlopen(request, timeout=avatar_worker_config.original_engine_timeout_sec) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, OSError, json.JSONDecodeError) as exc:
        raise OriginalEngineError(f"Original engine meta-human import failed: {exc}") from exc

    if result.get("code") != 0:
        raise OriginalEngineError(
            _response_message(result, "Original engine rejected the meta-human import.")
        )

    return {
        "name": name.strip(),
        "type": meta_human_type,
        "source_video_path": str(video_path),
        "response": result,
    }


def run_original_engine(*, audio_path: Path, avatar_id: str, output_dir: Path) -> Path:
    if not audio_path.exists():
        raise OriginalEngineError(f"Audio not found: {audio_path}")

    output_dir.mkdir(parents=True, exist_ok=True)
    meta_human_name = _resolve_meta_human_name(avatar_id)
    available_names = {str(item.get("name") or "") for item in list_original_meta_humans()}
    if meta_human_name not in available_names:
        raise OriginalEngineError(
            f"Selected original-engine template is unavailable: {meta_human_name}"
        )
    uploaded_audio_url = _upload_audio(audio_path)

    start_payload = {
        "type": "sync",
        "audio_file": uploaded_audio_url,
        "meta_human_name": meta_human_name,
        "use_super_resolution": avatar_worker_config.original_engine_use_super_resolution,
        "use_action_generalization": avatar_worker_config.original_engine_use_action_generalization,
        "batch_size": avatar_worker_config.original_engine_batch_size,
    }
    start_response = _request_json(
        "/video/meta_human_video/", method="POST", payload=start_payload, timeout=30
    )
    if start_response.get("code") != 0:
        raise OriginalEngineError(
            _response_message(start_response, "Original engine rejected the video job.")
        )

    result_url = _wait_for_result_url()
    output_path = output_dir / "original_engine_lip_sync.mp4"
    _download_result(result_url, output_path)

    if not output_path.exists() or output_path.stat().st_size < 64 * 1024:
        raise OriginalEngineError("Original engine finished without a usable video file.")

    return output_path


def _resolve_meta_human_name(avatar_id: str) -> str:
    if avatar_id.startswith(META_HUMAN_AVATAR_PREFIX):
        meta_human_name = unquote(avatar_id.removeprefix(META_HUMAN_AVATAR_PREFIX)).strip()
        if not meta_human_name:
            raise OriginalEngineError("Original-engine avatar id does not contain a template name.")
        return meta_human_name

    meta_human_name = AVATAR_TO_META_HUMAN.get(avatar_id)
    if meta_human_name:
        return meta_human_name
    raise OriginalEngineError(f"Unknown original-engine avatar id: {avatar_id}")


def _avatar_id_for_meta_human_name(name: str) -> str:
    for avatar_id, meta_human_name in AVATAR_TO_META_HUMAN.items():
        if meta_human_name == name:
            return avatar_id
    return f"{META_HUMAN_AVATAR_PREFIX}{quote(name, safe='')}"


def _base_url() -> str:
    return avatar_worker_config.original_engine_url.rstrip("/") + "/"


def _request_json(
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, object] | None = None,
    timeout: int = 10,
) -> dict[str, object]:
    url = urljoin(_base_url(), path.lstrip("/"))
    data = None
    headers: dict[str, str] = {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"

    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, OSError, json.JSONDecodeError) as exc:
        raise OriginalEngineError(f"Original engine request failed: {url}: {exc}") from exc


def _upload_audio(audio_path: Path) -> str:
    content_type = mimetypes.guess_type(audio_path.name)[0] or "application/octet-stream"
    fields = {
        "overwrite": "true",
        "key": "临时文件",
    }
    files = {
        "file": (audio_path.name, content_type, audio_path.read_bytes()),
    }
    body, content_type_header = _encode_multipart(fields, files)
    request = Request(
        urljoin(_base_url(), "files/upload/"),
        data=body,
        headers={"Content-Type": content_type_header},
        method="POST",
    )

    try:
        with urlopen(request, timeout=60) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, OSError, json.JSONDecodeError) as exc:
        raise OriginalEngineError(f"Original engine audio upload failed: {exc}") from exc

    if result.get("code") != 0 or not result.get("data"):
        raise OriginalEngineError(
            _response_message(result, "Original engine did not accept the audio upload.")
        )

    return str(result["data"])


def _encode_multipart(
    fields: dict[str, str],
    files: dict[str, tuple[str, str, bytes]],
) -> tuple[bytes, str]:
    boundary = f"----metahuman{uuid4().hex}"
    lines: list[bytes] = []

    for name, value in fields.items():
        lines.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"),
                str(value).encode("utf-8"),
                b"\r\n",
            ]
        )

    for name, (filename, content_type, content) in files.items():
        safe_filename = filename.replace('"', "")
        lines.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                (
                    f'Content-Disposition: form-data; name="{name}"; filename="{safe_filename}"\r\n'
                ).encode("utf-8"),
                f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"),
                content,
                b"\r\n",
            ]
        )

    lines.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(lines), f"multipart/form-data; boundary={boundary}"


def _wait_for_result_url() -> str:
    deadline = time.monotonic() + avatar_worker_config.original_engine_timeout_sec
    last_message = "Original engine is still running."

    while time.monotonic() < deadline:
        response = _request_json("/video/meta_human_video/progress/", timeout=10)
        if response.get("code") == 0:
            data = response.get("data")
            if isinstance(data, dict):
                status = data.get("status")
                if status == "done":
                    result_url = data.get("urlData") or data.get("url")
                    if result_url:
                        return str(result_url)
                    raise OriginalEngineError("Original engine completed without a result URL.")
                if status in {"failed", "error"}:
                    raise OriginalEngineError(
                        _response_message(response, "Original engine video job failed.")
                    )
                last_message = f"Original engine progress: {data.get('data', status)}"
        else:
            last_message = _response_message(response, last_message)

        time.sleep(avatar_worker_config.original_engine_poll_interval_sec)

    raise OriginalEngineError(f"Original engine timed out. Last status: {last_message}")


def _download_result(result_url: str, output_path: Path) -> None:
    parsed = urlparse(result_url)
    if parsed.scheme in {"http", "https"}:
        url = result_url
    else:
        url = urljoin(_base_url(), result_url.lstrip("/"))

    try:
        with urlopen(url, timeout=120) as response:
            output_path.write_bytes(response.read())
    except (HTTPError, URLError, OSError) as exc:
        raise OriginalEngineError(
            f"Could not download original engine video: {url}: {exc}"
        ) from exc


def _response_message(response: dict[str, object], fallback: str) -> str:
    message = response.get("message")
    if message:
        return str(message)
    return fallback
