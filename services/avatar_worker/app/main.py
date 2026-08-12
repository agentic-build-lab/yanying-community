from pathlib import Path
from shutil import copy2
from uuid import uuid4

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .audio_tail import AudioTailError, prepare_lip_sync_audio
from .face_enhancer import FaceEnhancementError, enhance_face_video
from .job_records import AvatarJobCreate, AvatarJobStatus, AvatarJobStore
from .musetalk_runner import MuseTalkError, run_musetalk
from .original_engine_runner import (
    OriginalEngineError,
    import_original_meta_human,
    is_original_engine_available,
    list_original_meta_humans,
    run_original_engine,
)
from .runtime_config import avatar_worker_config
from .wav2lip_runner import Wav2LipError, run_wav2lip

app = FastAPI(title="YanYing Avatar Worker", version="0.1.0")
job_store = AvatarJobStore()

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^http://(127\.0\.0\.1|localhost):\d+$",
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class OriginalMetaHumanImportCreate(BaseModel):
    video_path: str = Field(min_length=1)
    name: str = Field(min_length=1)
    type: str = Field(default="sync")


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "bind_host": avatar_worker_config.bind_host,
        "legacy_bridge_enabled": avatar_worker_config.enable_legacy_avatar,
        "lip_sync_mode": avatar_worker_config.lip_sync_mode,
        "image_avatar_lip_sync_mode": avatar_worker_config.image_avatar_lip_sync_mode,
        "default_image_path": str(avatar_worker_config.default_image_path),
        "wav2lip_available": avatar_worker_config.wav2lip_checkpoint_path.exists(),
        "lip_sync_tail_silence_ms": avatar_worker_config.lip_sync_tail_silence_ms,
        "musetalk_available": (
            avatar_worker_config.musetalk_repo_path / "models" / "musetalkV15" / "unet.pth"
        ).exists(),
        "musetalk_version": avatar_worker_config.musetalk_version,
        "musetalk_extra_margin": avatar_worker_config.musetalk_extra_margin,
        "musetalk_parsing_mode": avatar_worker_config.musetalk_parsing_mode,
        "musetalk_cheek_width": [
            avatar_worker_config.musetalk_left_cheek_width,
            avatar_worker_config.musetalk_right_cheek_width,
        ],
        "face_enhancement_mode": avatar_worker_config.face_enhancement_mode,
        "face_enhancement_required": avatar_worker_config.face_enhancement_required,
        "enhance_original_engine_video": avatar_worker_config.enhance_original_engine_video,
        "codeformer_available": (
            avatar_worker_config.codeformer_repo_path / "inference_codeformer.py"
        ).exists(),
        "codeformer_fidelity_weight": avatar_worker_config.codeformer_fidelity_weight,
        "codeformer_mouth_preserve_enabled": avatar_worker_config.codeformer_mouth_preserve_enabled,
        "original_engine_url": avatar_worker_config.original_engine_url,
        "original_engine_available": is_original_engine_available(),
        "original_engine_super_resolution": avatar_worker_config.original_engine_use_super_resolution,
        "original_engine_action_generalization": avatar_worker_config.original_engine_use_action_generalization,
    }


@app.get("/api/avatar/jobs")
def list_jobs():
    return job_store.list_jobs()


@app.get("/api/avatar/original-engine/meta-humans")
def list_original_engine_meta_humans() -> dict[str, object]:
    try:
        items = list_original_meta_humans()
    except OriginalEngineError as exc:
        return {
            "available": False,
            "items": [],
            "message": str(exc),
        }

    return {
        "available": True,
        "items": items,
        "message": "Original engine meta-human list loaded.",
    }


@app.post("/api/avatar/original-engine/meta-humans/import-from-path")
def import_original_engine_meta_human(payload: OriginalMetaHumanImportCreate) -> dict[str, object]:
    try:
        result = import_original_meta_human(
            video_path=Path(payload.video_path),
            name=payload.name,
            meta_human_type=payload.type,
        )
        items = list_original_meta_humans()
    except OriginalEngineError as exc:
        return {
            "status": "failed",
            "message": str(exc),
            "item": None,
            "items": [],
        }

    expected_names = {
        payload.name,
        payload.name if payload.name.lower().endswith(".mp4") else f"{payload.name}.mp4",
    }
    imported_item = next((item for item in items if item.get("name") in expected_names), None)
    return {
        "status": "completed",
        "message": "Original engine meta-human imported.",
        "item": imported_item,
        "items": items,
        "engine_response": result["response"],
    }


@app.post("/api/avatar/jobs")
def create_avatar_job(payload: AvatarJobCreate):
    job_id = f"avatar_{uuid4().hex[:12]}"

    if payload.dry_run:
        return job_store.add(
            payload,
            status=AvatarJobStatus.completed,
            progress=100,
            message="Dry-run avatar job completed. No video file was generated.",
            job_id=job_id,
        )

    source_image = (
        Path(payload.image_path) if payload.image_path else avatar_worker_config.default_image_path
    )
    if not source_image.exists():
        return job_store.add(
            payload,
            status=AvatarJobStatus.failed,
            progress=0,
            message=f"Avatar image not found: {source_image}",
            job_id=job_id,
        )

    job_dir = avatar_worker_config.output_root / "avatar" / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    prepared_image = job_dir / "presenter.png"
    copy2(source_image, prepared_image)
    lip_sync_audio_path = Path(payload.audio_path) if payload.audio_path else None
    if lip_sync_audio_path:
        try:
            lip_sync_audio_path = prepare_lip_sync_audio(lip_sync_audio_path, job_dir / "audio")
        except AudioTailError as exc:
            return job_store.add(
                payload,
                status=AvatarJobStatus.failed,
                progress=0,
                message=str(exc),
                job_id=job_id,
                image_path=str(prepared_image),
            )

    mode = _resolve_lip_sync_mode(payload.avatar_source)
    video_path = None
    video_stage = None
    engine_message = "AI presenter image prepared for render."

    if mode in {"original_engine", "original_then_wav2lip", "original_then_musetalk_then_wav2lip"}:
        if not payload.audio_path:
            return job_store.add(
                payload,
                status=AvatarJobStatus.failed,
                progress=0,
                message="Original engine requires audio_path.",
                job_id=job_id,
                image_path=str(prepared_image),
            )

        try:
            video_path = run_original_engine(
                audio_path=lip_sync_audio_path,
                avatar_id=payload.avatar_id,
                output_dir=job_dir,
            )
            video_stage = "original_engine"
            engine_message = (
                "Original engine digital-human video generated with enhancement enabled."
            )
        except OriginalEngineError as exc:
            if mode == "original_engine" or _is_video_avatar_source(payload.avatar_source):
                return job_store.add(
                    payload,
                    status=AvatarJobStatus.failed,
                    progress=0,
                    message=str(exc),
                    job_id=job_id,
                    image_path=str(prepared_image),
                )
            engine_message = f"Original engine unavailable, fell back to Wav2Lip: {exc}"

    if video_path is None and mode in {
        "musetalk",
        "musetalk_then_wav2lip",
        "original_then_musetalk_then_wav2lip",
    }:
        if not payload.audio_path:
            return job_store.add(
                payload,
                status=AvatarJobStatus.failed,
                progress=0,
                message="MuseTalk requires audio_path.",
                job_id=job_id,
                image_path=str(prepared_image),
            )

        try:
            video_path = run_musetalk(
                image_path=prepared_image,
                audio_path=lip_sync_audio_path,
                output_dir=job_dir,
            )
            video_stage = "musetalk"
            engine_message = "MuseTalk high-quality lip-sync video generated."
        except MuseTalkError as exc:
            if mode == "musetalk":
                return job_store.add(
                    payload,
                    status=AvatarJobStatus.failed,
                    progress=0,
                    message=str(exc),
                    job_id=job_id,
                    image_path=str(prepared_image),
                )
            engine_message = f"MuseTalk unavailable, fell back to Wav2Lip: {exc}"

    if video_path is None and mode in {
        "wav2lip",
        "original_then_wav2lip",
        "musetalk_then_wav2lip",
        "original_then_musetalk_then_wav2lip",
    }:
        if not payload.audio_path:
            return job_store.add(
                payload,
                status=AvatarJobStatus.failed,
                progress=0,
                message="Wav2Lip requires audio_path.",
                job_id=job_id,
                image_path=str(prepared_image),
            )

        try:
            video_path = run_wav2lip(
                image_path=prepared_image,
                audio_path=lip_sync_audio_path,
                output_dir=job_dir,
            )
            video_stage = "wav2lip"
            if mode == "wav2lip":
                engine_message = "Wav2Lip lip-sync video generated."
        except Wav2LipError as exc:
            return job_store.add(
                payload,
                status=AvatarJobStatus.failed,
                progress=0,
                message=str(exc),
                job_id=job_id,
                image_path=str(prepared_image),
            )

    should_enhance_face = video_path is not None and (
        video_stage != "original_engine" or avatar_worker_config.enhance_original_engine_video
    )
    if should_enhance_face:
        try:
            enhanced_video_path = enhance_face_video(
                input_video_path=Path(video_path),
                output_dir=job_dir / "face_enhancement",
                fps=avatar_worker_config.wav2lip_fps if video_stage == "wav2lip" else None,
            )
            if enhanced_video_path != video_path:
                video_path = enhanced_video_path
                if avatar_worker_config.codeformer_mouth_preserve_enabled:
                    engine_message = f"{engine_message} CodeFormer face enhancement and mouth preservation applied."
                else:
                    engine_message = f"{engine_message} CodeFormer face enhancement applied."
        except FaceEnhancementError as exc:
            if avatar_worker_config.face_enhancement_required:
                return job_store.add(
                    payload,
                    status=AvatarJobStatus.failed,
                    progress=0,
                    message=str(exc),
                    job_id=job_id,
                    image_path=str(prepared_image),
                )
            engine_message = f"{engine_message} Face enhancement skipped: {exc}"
    elif video_path is not None and video_stage == "original_engine":
        engine_message = (
            "Original engine digital-human video generated. "
            "Extra frame-by-frame face enhancement was skipped for this video template."
        )

    return job_store.add(
        payload,
        status=AvatarJobStatus.completed,
        progress=100,
        message=engine_message,
        job_id=job_id,
        image_path=str(prepared_image),
        audio_path=str(lip_sync_audio_path) if lip_sync_audio_path else payload.audio_path,
        video_path=str(video_path) if video_path else None,
    )


def _resolve_lip_sync_mode(avatar_source: str) -> str:
    normalized = (avatar_source or "").strip().lower()
    if normalized in {"image_avatar", "generated_image", "single_image"}:
        return avatar_worker_config.image_avatar_lip_sync_mode.lower()
    if normalized in {"legacy_video_avatar", "original_engine", "legacy_template"}:
        return avatar_worker_config.lip_sync_mode.lower()
    return avatar_worker_config.lip_sync_mode.lower()


def _is_video_avatar_source(avatar_source: str) -> bool:
    return (avatar_source or "").strip().lower() in {
        "legacy_video_avatar",
        "original_engine",
        "legacy_template",
    }
