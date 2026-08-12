import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_AVATAR_PYTHON = REPO_ROOT / ".runtime" / "python" / "python.exe"


@dataclass(frozen=True)
class AvatarWorkerConfig:
    bind_host: str = os.getenv("METAHUMAN_AVATAR_BIND_HOST", "127.0.0.1")
    enable_legacy_avatar: bool = os.getenv("METAHUMAN_AVATAR_ENABLE_LEGACY", "0") == "1"
    lip_sync_mode: str = os.getenv("METAHUMAN_AVATAR_LIPSYNC_MODE", "wav2lip")
    image_avatar_lip_sync_mode: str = os.getenv("METAHUMAN_IMAGE_AVATAR_LIPSYNC_MODE", "wav2lip")
    output_root: Path = Path(
        os.getenv("METAHUMAN_OUTPUT_ROOT", str(REPO_ROOT / ".runtime" / "outputs"))
    )
    default_image_path: Path = Path(
        os.getenv(
            "METAHUMAN_DEFAULT_AVATAR_IMAGE",
            str(REPO_ROOT / "apps" / "studio_web" / "assets" / "presenter-placeholder.svg"),
        )
    )
    wav2lip_python: str = os.getenv(
        "METAHUMAN_WAV2LIP_PYTHON",
        str(DEFAULT_AVATAR_PYTHON) if DEFAULT_AVATAR_PYTHON.exists() else "python",
    )
    wav2lip_repo_path: Path = Path(
        os.getenv("METAHUMAN_WAV2LIP_REPO", str(REPO_ROOT / "packages" / "wav2lip_upstream"))
    )
    wav2lip_checkpoint_path: Path = Path(
        os.getenv(
            "METAHUMAN_WAV2LIP_CHECKPOINT",
            str(REPO_ROOT / "models" / "lip_sync" / "wav2lip_gan.pth"),
        )
    )
    wav2lip_dependency_path: Path = Path(
        os.getenv(
            "METAHUMAN_WAV2LIP_DEPENDENCY_PATH",
            str(REPO_ROOT / ".runtime" / "packages" / "wav2lip"),
        )
    )
    wav2lip_fps: int = int(os.getenv("METAHUMAN_WAV2LIP_FPS", "18"))
    lip_sync_tail_silence_ms: int = int(os.getenv("METAHUMAN_LIPSYNC_TAIL_SILENCE_MS", "420"))
    musetalk_python: str = os.getenv(
        "METAHUMAN_MUSETALK_PYTHON",
        str(DEFAULT_AVATAR_PYTHON) if DEFAULT_AVATAR_PYTHON.exists() else "python",
    )
    musetalk_repo_path: Path = Path(
        os.getenv(
            "METAHUMAN_MUSETALK_REPO", str(REPO_ROOT / "packages" / "lip_sync_engines" / "musetalk")
        )
    )
    musetalk_dependency_path: Path = Path(
        os.getenv(
            "METAHUMAN_MUSETALK_DEPENDENCY_PATH",
            str(REPO_ROOT / ".runtime" / "packages" / "musetalk"),
        )
    )
    musetalk_torch_home: Path = Path(
        os.getenv("METAHUMAN_MUSETALK_TORCH_HOME", str(REPO_ROOT / ".runtime" / "cache" / "torch"))
    )
    musetalk_version: str = os.getenv("METAHUMAN_MUSETALK_VERSION", "v15")
    musetalk_fps: int = int(os.getenv("METAHUMAN_MUSETALK_FPS", "25"))
    musetalk_batch_size: int = int(os.getenv("METAHUMAN_MUSETALK_BATCH_SIZE", "4"))
    musetalk_use_float16: bool = os.getenv("METAHUMAN_MUSETALK_USE_FLOAT16", "1") == "1"
    musetalk_extra_margin: int = int(os.getenv("METAHUMAN_MUSETALK_EXTRA_MARGIN", "20"))
    musetalk_parsing_mode: str = os.getenv("METAHUMAN_MUSETALK_PARSING_MODE", "jaw")
    musetalk_left_cheek_width: int = int(os.getenv("METAHUMAN_MUSETALK_LEFT_CHEEK_WIDTH", "110"))
    musetalk_right_cheek_width: int = int(os.getenv("METAHUMAN_MUSETALK_RIGHT_CHEEK_WIDTH", "110"))
    musetalk_audio_padding_left: int = int(os.getenv("METAHUMAN_MUSETALK_AUDIO_PADDING_LEFT", "2"))
    musetalk_audio_padding_right: int = int(
        os.getenv("METAHUMAN_MUSETALK_AUDIO_PADDING_RIGHT", "2")
    )
    musetalk_timeout_sec: int = int(os.getenv("METAHUMAN_MUSETALK_TIMEOUT_SEC", "1800"))
    musetalk_ffmpeg_path: str = os.getenv("METAHUMAN_MUSETALK_FFMPEG_PATH", "")
    face_enhancement_mode: str = os.getenv("METAHUMAN_FACE_ENHANCEMENT_MODE", "off")
    face_enhancement_required: bool = os.getenv("METAHUMAN_FACE_ENHANCEMENT_REQUIRED", "0") == "1"
    enhance_original_engine_video: bool = (
        os.getenv("METAHUMAN_ENHANCE_ORIGINAL_ENGINE_VIDEO", "0") == "1"
    )
    face_enhancement_python: str = os.getenv(
        "METAHUMAN_FACE_ENHANCEMENT_PYTHON",
        str(DEFAULT_AVATAR_PYTHON) if DEFAULT_AVATAR_PYTHON.exists() else "python",
    )
    codeformer_repo_path: Path = Path(
        os.getenv(
            "METAHUMAN_CODEFORMER_REPO",
            str(REPO_ROOT / "packages" / "face_enhancers" / "codeformer"),
        )
    )
    codeformer_dependency_path: Path = Path(
        os.getenv(
            "METAHUMAN_CODEFORMER_DEPENDENCY_PATH",
            str(REPO_ROOT / ".runtime" / "packages" / "codeformer"),
        )
    )
    codeformer_wrapper_path: Path = Path(
        os.getenv(
            "METAHUMAN_CODEFORMER_WRAPPER",
            str(REPO_ROOT / "scripts" / "enhance_video_faces_codeformer.py"),
        )
    )
    codeformer_fidelity_weight: float = float(
        os.getenv("METAHUMAN_CODEFORMER_FIDELITY_WEIGHT", "0.90")
    )
    codeformer_upscale: int = int(os.getenv("METAHUMAN_CODEFORMER_UPSCALE", "1"))
    codeformer_detection_model: str = os.getenv(
        "METAHUMAN_CODEFORMER_DETECTION_MODEL", "retinaface_resnet50"
    )
    codeformer_only_center_face: bool = (
        os.getenv("METAHUMAN_CODEFORMER_ONLY_CENTER_FACE", "1") == "1"
    )
    codeformer_video_crf: int = int(os.getenv("METAHUMAN_CODEFORMER_VIDEO_CRF", "12"))
    codeformer_video_preset: str = os.getenv("METAHUMAN_CODEFORMER_VIDEO_PRESET", "slow")
    codeformer_mouth_preserve_enabled: bool = (
        os.getenv("METAHUMAN_CODEFORMER_MOUTH_PRESERVE_ENABLED", "1") == "1"
    )
    codeformer_mouth_preserve_wrapper_path: Path = Path(
        os.getenv(
            "METAHUMAN_CODEFORMER_MOUTH_PRESERVE_WRAPPER",
            str(REPO_ROOT / "scripts" / "apply_mouth_region_preservation.py"),
        )
    )
    codeformer_mouth_preserve_rel_box: str = os.getenv(
        "METAHUMAN_CODEFORMER_MOUTH_PRESERVE_REL_BOX", "0.22,0.58,0.78,0.86"
    )
    codeformer_mouth_preserve_expand: float = float(
        os.getenv("METAHUMAN_CODEFORMER_MOUTH_PRESERVE_EXPAND", "1.18")
    )
    codeformer_mouth_preserve_strength: float = float(
        os.getenv("METAHUMAN_CODEFORMER_MOUTH_PRESERVE_STRENGTH", "0.88")
    )
    codeformer_mouth_preserve_mask_blur: int = int(
        os.getenv("METAHUMAN_CODEFORMER_MOUTH_PRESERVE_MASK_BLUR", "31")
    )
    codeformer_mouth_preserve_timeout_sec: int = int(
        os.getenv("METAHUMAN_CODEFORMER_MOUTH_PRESERVE_TIMEOUT_SEC", "900")
    )
    face_enhancement_timeout_sec: int = int(
        os.getenv("METAHUMAN_FACE_ENHANCEMENT_TIMEOUT_SEC", "1800")
    )
    original_engine_url: str = os.getenv("METAHUMAN_ORIGINAL_ENGINE_URL", "http://127.0.0.1:35005")
    original_engine_batch_size: int = int(os.getenv("METAHUMAN_ORIGINAL_ENGINE_BATCH_SIZE", "4"))
    original_engine_use_super_resolution: bool = (
        os.getenv("METAHUMAN_ORIGINAL_ENGINE_USE_SUPER_RESOLUTION", "1") == "1"
    )
    original_engine_use_action_generalization: bool = (
        os.getenv("METAHUMAN_ORIGINAL_ENGINE_USE_ACTION_GENERALIZATION", "1") == "1"
    )
    original_engine_timeout_sec: int = int(
        os.getenv("METAHUMAN_ORIGINAL_ENGINE_TIMEOUT_SEC", "900")
    )
    original_engine_poll_interval_sec: float = float(
        os.getenv("METAHUMAN_ORIGINAL_ENGINE_POLL_INTERVAL_SEC", "2")
    )


avatar_worker_config = AvatarWorkerConfig()
