import asyncio

from fastapi import (
    BackgroundTasks,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .asset_records import default_assets
from .capability_records import build_capabilities
from .cover_designer import CoverDesignError, create_designed_cover
from .job_records import JobStore, RenderJobCreate
from .legacy_adapter_client import LegacyAdapterRequestError, request_legacy_adapter
from .project_records import demo_project
from .runtime_config import runtime_config
from .tts_bridge import TtsGenerateRequest, preview_tts_request
from .ui_profile_store import UiImageUpload, UiProfileStore, UiProfileUpdate
from .user_media_library import UserMediaError, UserMediaLibrary
from .worker_clients import (
    generate_legacy_audio,
    get_json,
    post_json,
    post_json_required,
    post_tts_job_resilient,
    run_pipeline,
)

app = FastAPI(title="YanYing Digital Human Studio API", version="0.3.0")
runtime_config.output_root.mkdir(parents=True, exist_ok=True)
job_store = JobStore(runtime_config.output_root / "jobs" / "job_records.json")
ui_profile_store = UiProfileStore(
    runtime_config.output_root / "settings" / "ui_profiles.json",
    runtime_config.output_root,
)
user_media_library = UserMediaLibrary(
    runtime_config.output_root / "settings" / "user_media_library.json",
    runtime_config.output_root,
)


class VideoFrameCreate(BaseModel):
    video_source: str = Field(min_length=1, max_length=3000)
    time_seconds: float = Field(default=1, ge=0, le=36000)


class CoverDesignCreate(BaseModel):
    image_source: str = Field(min_length=1, max_length=3000)
    title_line_1: str = Field(default="", max_length=30)
    title_line_2: str = Field(default="", max_length=30)
    style: str = Field(default="studio")
    target_format: str = Field(default="1080x1920")
    accent_color: str = Field(default="#f2c94c", max_length=16)


app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^http://(127\.0\.0\.1|localhost):\d+$",
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

app.mount("/media", StaticFiles(directory=runtime_config.output_root), name="generated_media")


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "bind_host": runtime_config.default_bind_host,
        "mode": "local_mvp",
        "media_root": str(runtime_config.output_root),
    }


@app.get("/api/system/status")
def system_status() -> dict[str, object]:
    tts_worker_health = None
    if runtime_config.enable_tts_worker:
        tts_worker_health = get_json(f"{runtime_config.tts_worker_url}/health")

    avatar_worker_health = None
    if runtime_config.enable_avatar_worker:
        avatar_worker_health = get_json(f"{runtime_config.avatar_worker_url}/health")

    render_worker_health = None
    if runtime_config.enable_render_worker:
        render_worker_health = get_json(f"{runtime_config.render_worker_url}/health")

    legacy_adapter_health = None
    if runtime_config.enable_legacy_adapter:
        legacy_adapter_health = get_json(f"{runtime_config.legacy_adapter_url}/health", timeout=4)

    content_worker_health = None
    if runtime_config.enable_content_worker:
        content_worker_health = get_json(f"{runtime_config.content_worker_url}/health", timeout=4)

    tts_status = "not_connected"
    if tts_worker_health:
        tts_status = "connected"
    elif runtime_config.enable_legacy_tts:
        tts_status = "legacy_bridge_enabled"

    avatar_status = "connected" if avatar_worker_health else "not_connected"
    render_status = "connected" if render_worker_health else "not_connected"
    legacy_engine = legacy_adapter_health.get("legacy_engine") if legacy_adapter_health else None
    legacy_available = (
        bool(legacy_engine.get("available")) if isinstance(legacy_engine, dict) else False
    )
    legacy_status = (
        "connected"
        if legacy_available
        else "adapter_only"
        if legacy_adapter_health
        else "not_connected"
    )

    return {
        "api": {
            "connected": True,
            "host": runtime_config.default_bind_host,
            "mode": "local_mvp",
        },
        "workers": [
            {
                "id": "tts_worker",
                "label": "TTS Worker",
                "status": tts_status,
                "url": runtime_config.tts_worker_url,
                "provider": tts_worker_health.get("provider") if tts_worker_health else None,
                "voice": tts_worker_health.get("edge_voice") if tts_worker_health else None,
                "enhance_audio": tts_worker_health.get("enhance_audio")
                if tts_worker_health
                else None,
                "enhancement_preset": tts_worker_health.get("enhancement_preset")
                if tts_worker_health
                else None,
                "voice_profiles": tts_worker_health.get("voice_profiles")
                if tts_worker_health
                else None,
            },
            {
                "id": "avatar_worker",
                "label": "Avatar Worker",
                "status": avatar_status,
                "url": runtime_config.avatar_worker_url,
                "lip_sync_mode": avatar_worker_health.get("lip_sync_mode")
                if avatar_worker_health
                else None,
                "wav2lip_available": avatar_worker_health.get("wav2lip_available")
                if avatar_worker_health
                else None,
                "original_engine_url": avatar_worker_health.get("original_engine_url")
                if avatar_worker_health
                else None,
                "original_engine_available": avatar_worker_health.get("original_engine_available")
                if avatar_worker_health
                else None,
                "original_engine_super_resolution": avatar_worker_health.get(
                    "original_engine_super_resolution"
                )
                if avatar_worker_health
                else None,
                "original_engine_action_generalization": avatar_worker_health.get(
                    "original_engine_action_generalization"
                )
                if avatar_worker_health
                else None,
            },
            {
                "id": "render_worker",
                "label": "Render Worker",
                "status": render_status,
                "url": runtime_config.render_worker_url,
                "motion_mode": render_worker_health.get("motion_mode")
                if render_worker_health
                else None,
            },
            {
                "id": "legacy_engine_adapter",
                "label": "Legacy Engine Adapter",
                "status": legacy_status,
                "url": runtime_config.legacy_adapter_url,
                "legacy_engine_available": legacy_available,
            },
            {
                "id": "content_worker",
                "label": "Content Worker",
                "status": "connected" if content_worker_health else "not_connected",
                "url": runtime_config.content_worker_url,
                "provider": content_worker_health.get("provider")
                if content_worker_health
                else None,
            },
        ],
        "safety": {
            "default_bind_host": runtime_config.default_bind_host,
            "auto_publish_enabled": False,
            "publish_review_required": True,
            "old_frontend_required": False,
            "logs_redacted": True,
            "legacy_tts_url": runtime_config.legacy_tts_url,
        },
    }


def request_content_worker(path: str, payload: dict[str, object]) -> dict[str, object]:
    if not runtime_config.enable_content_worker:
        raise HTTPException(status_code=503, detail="Content worker is disabled.")
    result = post_json(
        f"{runtime_config.content_worker_url.rstrip('/')}{path}",
        payload,
        timeout=runtime_config.content_worker_timeout_sec,
    )
    if result is None:
        raise HTTPException(
            status_code=502, detail="Content worker request failed or returned invalid JSON."
        )
    return result


@app.get("/api/content/status")
def content_status() -> dict[str, object]:
    if not runtime_config.enable_content_worker:
        return {"available": False, "configured": False}
    health = get_json(f"{runtime_config.content_worker_url}/health", timeout=4)
    config_response = get_json(f"{runtime_config.content_worker_url}/api/config", timeout=4)
    config_data = config_response.get("data") if isinstance(config_response, dict) else None
    llm = config_data.get("llm") if isinstance(config_data, dict) else None
    key_info = llm.get("api_key_info") if isinstance(llm, dict) else None
    return {
        "available": bool(health),
        "configured": bool(key_info.get("set")) if isinstance(key_info, dict) else False,
        "provider": llm.get("provider") if isinstance(llm, dict) else None,
        "model": llm.get("model") if isinstance(llm, dict) else None,
        "enabled": bool(llm.get("enabled")) if isinstance(llm, dict) else False,
    }


@app.get("/api/content/config")
def get_content_config() -> dict[str, object]:
    if not runtime_config.enable_content_worker:
        raise HTTPException(status_code=503, detail="文案服务未启用。")
    result = get_json(f"{runtime_config.content_worker_url}/api/config", timeout=4)
    if result is None:
        raise HTTPException(status_code=502, detail="无法读取文案服务配置。")
    return result


@app.post("/api/content/config")
def update_content_config(payload: dict[str, object]) -> dict[str, object]:
    return request_content_worker("/api/config", payload)


@app.post("/api/content/test")
def test_content_generation() -> dict[str, object]:
    return request_content_worker("/api/llm/test", {})


@app.post("/api/content/rewrite")
def rewrite_content(payload: dict[str, object]) -> dict[str, object]:
    return request_content_worker("/text/rewrite/", payload)


@app.post("/api/content/title")
def generate_content_title(payload: dict[str, object]) -> dict[str, object]:
    return request_content_worker("/title/", payload)


@app.post("/api/content/douyin/extract")
def extract_douyin_content(payload: dict[str, object]) -> dict[str, object]:
    return request_content_worker("/text/douyin/", payload)


@app.get("/api/project")
def get_project():
    return demo_project()


@app.get("/api/assets")
def list_assets():
    return default_assets()


@app.get("/api/capabilities")
def list_capabilities() -> dict[str, object]:
    tts_ready = (
        bool(get_json(f"{runtime_config.tts_worker_url}/health"))
        if runtime_config.enable_tts_worker
        else False
    )
    avatar_ready = (
        bool(get_json(f"{runtime_config.avatar_worker_url}/health"))
        if runtime_config.enable_avatar_worker
        else False
    )
    render_ready = (
        bool(get_json(f"{runtime_config.render_worker_url}/health"))
        if runtime_config.enable_render_worker
        else False
    )
    adapter_health = (
        get_json(f"{runtime_config.legacy_adapter_url}/health", timeout=4)
        if runtime_config.enable_legacy_adapter
        else None
    )
    legacy_engine = adapter_health.get("legacy_engine") if adapter_health else None
    legacy_ready = (
        bool(legacy_engine.get("available")) if isinstance(legacy_engine, dict) else False
    )
    return build_capabilities(
        native_ready=tts_ready and avatar_ready and render_ready,
        legacy_ready=legacy_ready,
    )


@app.get("/api/legacy/catalog")
def get_legacy_catalog() -> Response:
    if not runtime_config.enable_legacy_adapter:
        raise HTTPException(status_code=503, detail="Legacy adapter is disabled.")
    try:
        status, body, media_type = request_legacy_adapter("/api/legacy/catalog")
    except LegacyAdapterRequestError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return Response(content=body, status_code=status, media_type=media_type)


@app.get("/api/tts/voices")
def list_tts_voices() -> dict[str, object]:
    if not runtime_config.enable_tts_worker:
        return {"items": []}
    return get_json(f"{runtime_config.tts_worker_url}/api/tts/voices") or {"items": []}


@app.post("/api/legacy/runtime-config")
async def update_legacy_runtime_config(request: Request) -> Response:
    if not runtime_config.enable_legacy_adapter:
        raise HTTPException(status_code=503, detail="Legacy adapter is disabled.")
    body = await request.body()
    try:
        status, response_body, media_type = await asyncio.to_thread(
            request_legacy_adapter,
            "/api/legacy/runtime-config",
            method="POST",
            body=body or None,
            content_type=request.headers.get("content-type"),
        )
    except LegacyAdapterRequestError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return Response(content=response_body, status_code=status, media_type=media_type)


@app.api_route("/api/legacy/{route_path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy_legacy_route(route_path: str, request: Request) -> Response:
    if not runtime_config.enable_legacy_adapter:
        raise HTTPException(status_code=503, detail="Legacy adapter is disabled.")
    body = await request.body()
    try:
        status, response_body, media_type = await asyncio.to_thread(
            request_legacy_adapter,
            f"/api/legacy/proxy/{route_path}",
            method=request.method,
            query=request.url.query,
            body=body or None,
            content_type=request.headers.get("content-type"),
            review_approved=request.headers.get("X-Metahuman-Review-Approved"),
        )
    except LegacyAdapterRequestError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return Response(content=response_body, status_code=status, media_type=media_type)


@app.get("/api/avatar/original-engine/meta-humans")
def list_original_engine_meta_humans() -> dict[str, object]:
    if not runtime_config.enable_avatar_worker:
        return {"available": False, "items": [], "message": "Avatar worker is disabled."}

    response = get_json(
        f"{runtime_config.avatar_worker_url}/api/avatar/original-engine/meta-humans", timeout=8
    )
    if response is None:
        return {
            "available": False,
            "items": [],
            "message": "Avatar worker did not return meta-human assets.",
        }
    return response


@app.post("/api/avatar/original-engine/meta-humans/import-from-path")
def import_original_engine_meta_human(payload: dict[str, object]) -> dict[str, object]:
    if not runtime_config.enable_avatar_worker:
        return {"status": "failed", "message": "Avatar worker is disabled."}

    return post_json_required(
        f"{runtime_config.avatar_worker_url}/api/avatar/original-engine/meta-humans/import-from-path",
        payload,
        timeout=runtime_config.avatar_worker_timeout_sec,
    )


@app.get("/api/jobs")
def list_jobs():
    return job_store.list_jobs()


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = job_store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在。")
    return job


def _execute_pipeline_job(job_id: str, payload: RenderJobCreate) -> None:
    def update_progress(
        stage: str,
        stage_status: str,
        progress: int,
        message: str,
        result: dict[str, object] | None,
    ) -> None:
        job_store.update_stage(
            job_id,
            stage=stage,
            stage_status=stage_status,
            progress=progress,
            message=message,
            result=result,
        )

    try:
        stages = run_pipeline(payload, on_progress=update_progress)
        job_store.finalize_job(job_id, stages)
    except Exception as exc:
        job_store.fail_job(job_id, f"生成任务异常终止：{exc}")


@app.post("/api/jobs", status_code=202)
def create_job(payload: RenderJobCreate, background_tasks: BackgroundTasks):
    job = job_store.create_queued_job(payload)
    background_tasks.add_task(_execute_pipeline_job, job.job_id, payload)
    return job


@app.delete("/api/jobs/samples")
def delete_sample_jobs() -> dict[str, int]:
    return {"deleted_count": job_store.delete_sample_jobs()}


@app.delete("/api/jobs")
def delete_jobs(scope: str = "all") -> dict[str, int | str]:
    try:
        deleted_count = job_store.delete_jobs(scope)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="任务范围必须是 real、samples 或 all。"
        ) from exc
    return {"scope": scope, "deleted_count": deleted_count}


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str) -> dict[str, object]:
    try:
        deleted = job_store.delete_job(job_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail="任务正在生成，完成或失败后才能删除。") from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="任务不存在。")
    return {"job_id": job_id, "deleted": True}


@app.get("/api/ui/profiles")
def list_ui_profiles() -> dict[str, object]:
    return {"items": ui_profile_store.list_profiles()}


@app.put("/api/ui/profiles/{kind}/{key}")
def update_ui_profile(kind: str, key: str, payload: UiProfileUpdate) -> dict[str, object]:
    try:
        return {"item": ui_profile_store.update_profile(kind, key, payload)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/ui/images")
def upload_ui_image(payload: UiImageUpload) -> dict[str, str]:
    try:
        return {"image_url": ui_profile_store.save_image(payload)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/media/background-music")
def list_user_background_music() -> dict[str, object]:
    return {"items": user_media_library.list_background_music()}


@app.post("/api/media/background-music")
async def import_user_background_music(
    file: UploadFile = File(...),
    name: str = Form(default=""),
) -> dict[str, object]:
    try:
        item = await asyncio.to_thread(
            user_media_library.import_background_music,
            source=file.file,
            filename=file.filename or "background_music",
            content_type=file.content_type,
            display_name=name,
        )
        return {"item": item}
    except UserMediaError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        await file.close()


@app.delete("/api/media/background-music/{media_id}")
def delete_user_background_music(media_id: str) -> dict[str, object]:
    return {"deleted": user_media_library.delete_background_music(media_id)}


@app.post("/api/media/voice-reference")
async def prepare_voice_reference(file: UploadFile = File(...)) -> dict[str, object]:
    try:
        return await asyncio.to_thread(
            user_media_library.prepare_voice_reference,
            source=file.file,
            filename=file.filename or "voice_reference",
            content_type=file.content_type,
        )
    except UserMediaError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        await file.close()


@app.post("/api/media/video-frame")
async def extract_video_frame(payload: VideoFrameCreate) -> dict[str, object]:
    try:
        return await asyncio.to_thread(
            user_media_library.extract_video_frame,
            video_source=payload.video_source,
            time_seconds=payload.time_seconds,
        )
    except UserMediaError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/media/designed-cover")
async def design_cover(payload: CoverDesignCreate) -> dict[str, object]:
    try:
        return await asyncio.to_thread(
            create_designed_cover,
            image_source=payload.image_source,
            title_line_1=payload.title_line_1,
            title_line_2=payload.title_line_2,
            style=payload.style,
            target_format=payload.target_format,
            accent_color=payload.accent_color,
            media_root=runtime_config.output_root,
        )
    except CoverDesignError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/tts/preview")
def preview_tts(payload: TtsGenerateRequest):
    worker_response = post_tts_job_resilient(payload)
    if worker_response is not None:
        return {
            "accepted": True,
            "dry_run": payload.dry_run,
            "message": "TTS worker accepted the request.",
            "worker_job": worker_response,
        }

    return preview_tts_request(payload)


@app.post("/api/tts/legacy-preview")
def preview_legacy_tts(payload: TtsGenerateRequest):
    result = generate_legacy_audio(
        text=payload.text,
        prompt_audio=payload.prompt_audio or "",
        speed=payload.speed,
        timeout_sec=runtime_config.legacy_adapter_timeout_sec,
    )
    return {"accepted": result.get("status") == "completed", "worker_job": result}
