import json
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .job_records import RenderJobCreate, RenderJobStatus, RenderJobStore
from .local_renderer import LocalRenderError, render_lip_synced_video, render_talking_video
from .media_paths import make_video_job_dir
from .runtime_config import render_worker_config

app = FastAPI(title="YanYing Render Worker", version="0.1.0")
job_store = RenderJobStore()

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^http://(127\.0\.0\.1|localhost):\d+$",
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "bind_host": render_worker_config.bind_host,
        "ffmpeg_path": render_worker_config.ffmpeg_path,
        "default_image_path": str(render_worker_config.default_image_path),
        "motion_mode": "lip_sync_package",
        "video_crf": render_worker_config.video_crf,
        "video_preset": render_worker_config.video_preset,
        "video_filter_extra": render_worker_config.video_filter_extra,
        "video_output_pattern": ".runtime/outputs/videos/<category>/<project_id>/<yyyymmdd>/<render_id>/",
    }


@app.get("/api/render/jobs")
def list_jobs():
    return job_store.list_jobs()


@app.post("/api/render/jobs")
def create_render_job(payload: RenderJobCreate):
    job_id = f"render_{uuid4().hex[:12]}"

    if payload.dry_run:
        return job_store.add(
            payload,
            status=RenderJobStatus.completed,
            progress=100,
            message="Dry-run render job completed. No export file was generated.",
            job_id=job_id,
        )

    image_path = (
        Path(payload.image_path) if payload.image_path else render_worker_config.default_image_path
    )
    if not payload.audio_path:
        return job_store.add(
            payload,
            status=RenderJobStatus.failed,
            progress=0,
            message="Real rendering requires audio_path.",
            job_id=job_id,
        )

    job_dir = make_video_job_dir(
        output_root=render_worker_config.output_root,
        output_category=payload.output_category,
        project_id=payload.project_id,
        job_id=job_id,
    )

    try:
        if payload.video_path:
            export_path, cover_path = render_lip_synced_video(
                video_path=Path(payload.video_path),
                audio_path=Path(payload.audio_path),
                subtitle_text=payload.subtitle_text or "",
                subtitle_segments=payload.subtitle_segments,
                subtitle_template=payload.subtitle_template,
                burn_subtitles=payload.burn_subtitles,
                target_format=payload.target_format,
                output_dir=job_dir,
                ffmpeg_path=render_worker_config.ffmpeg_path,
                video_crf=render_worker_config.video_crf,
                video_preset=render_worker_config.video_preset,
                video_filter_extra=render_worker_config.video_filter_extra,
            )
            message = "Lip-sync video packaged."
        else:
            export_path, cover_path = render_talking_video(
                image_path=image_path,
                audio_path=Path(payload.audio_path),
                subtitle_text=payload.subtitle_text or "",
                subtitle_segments=payload.subtitle_segments,
                subtitle_template=payload.subtitle_template,
                burn_subtitles=payload.burn_subtitles,
                target_format=payload.target_format,
                output_dir=job_dir,
                ffmpeg_path=render_worker_config.ffmpeg_path,
                video_crf=render_worker_config.video_crf,
                video_preset=render_worker_config.video_preset,
                video_filter_extra=render_worker_config.video_filter_extra,
            )
            message = "Fallback image-based MP4 render completed."
    except LocalRenderError as exc:
        return job_store.add(
            payload,
            status=RenderJobStatus.failed,
            progress=0,
            message=str(exc),
            job_id=job_id,
        )

    _write_media_manifest(
        job_dir=job_dir,
        payload=payload,
        job_id=job_id,
        export_path=export_path,
        cover_path=cover_path,
    )

    return job_store.add(
        payload,
        status=RenderJobStatus.completed,
        progress=100,
        message=message,
        job_id=job_id,
        export_path=str(export_path),
        cover_path=str(cover_path),
    )


def _write_media_manifest(
    *,
    job_dir: Path,
    payload: RenderJobCreate,
    job_id: str,
    export_path: Path,
    cover_path: Path,
) -> None:
    manifest = {
        "schema_version": 1,
        "job_id": job_id,
        "project_id": payload.project_id,
        "output_category": payload.output_category,
        "target_format": payload.target_format,
        "subtitle_template": payload.subtitle_template,
        "render_video_crf": render_worker_config.video_crf,
        "render_video_preset": render_worker_config.video_preset,
        "render_video_filter_extra": render_worker_config.video_filter_extra,
        "export_path": str(export_path),
        "cover_path": str(cover_path),
        "source_video_path": payload.video_path,
        "source_image_path": payload.image_path,
        "source_audio_path": payload.audio_path,
    }
    (job_dir / "media_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
