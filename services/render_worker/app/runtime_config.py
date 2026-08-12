import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class RenderWorkerConfig:
    bind_host: str = os.getenv("METAHUMAN_RENDER_BIND_HOST", "127.0.0.1")
    ffmpeg_path: str = os.getenv("METAHUMAN_FFMPEG_PATH", "ffmpeg")
    video_crf: int = int(os.getenv("METAHUMAN_RENDER_VIDEO_CRF", "12"))
    video_preset: str = os.getenv("METAHUMAN_RENDER_VIDEO_PRESET", "slow")
    video_filter_extra: str = os.getenv(
        "METAHUMAN_RENDER_VIDEO_FILTER_EXTRA", "unsharp=5:5:0.7:3:3:0.3"
    )
    output_root: Path = Path(
        os.getenv("METAHUMAN_OUTPUT_ROOT", str(REPO_ROOT / ".runtime" / "outputs"))
    )
    default_image_path: Path = Path(
        os.getenv(
            "METAHUMAN_DEFAULT_AVATAR_IMAGE",
            str(REPO_ROOT / "apps" / "studio_web" / "assets" / "presenter-placeholder.svg"),
        )
    )


render_worker_config = RenderWorkerConfig()
