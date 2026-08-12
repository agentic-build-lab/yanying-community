import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class RuntimeConfig:
    legacy_tts_url: str = os.getenv("METAHUMAN_LEGACY_TTS_URL", "http://127.0.0.1:5000/gen_single")
    enable_legacy_tts: bool = os.getenv("METAHUMAN_ENABLE_LEGACY_TTS", "0") == "1"
    default_bind_host: str = os.getenv("METAHUMAN_BIND_HOST", "127.0.0.1")
    tts_worker_url: str = os.getenv("METAHUMAN_TTS_WORKER_URL", "http://127.0.0.1:35205")
    enable_tts_worker: bool = os.getenv("METAHUMAN_ENABLE_TTS_WORKER", "1") == "1"
    tts_worker_timeout_sec: int = int(os.getenv("METAHUMAN_TTS_WORKER_TIMEOUT_SEC", "900"))
    avatar_worker_url: str = os.getenv("METAHUMAN_AVATAR_WORKER_URL", "http://127.0.0.1:35305")
    enable_avatar_worker: bool = os.getenv("METAHUMAN_ENABLE_AVATAR_WORKER", "1") == "1"
    avatar_worker_timeout_sec: int = int(os.getenv("METAHUMAN_AVATAR_WORKER_TIMEOUT_SEC", "3600"))
    render_worker_url: str = os.getenv("METAHUMAN_RENDER_WORKER_URL", "http://127.0.0.1:35405")
    enable_render_worker: bool = os.getenv("METAHUMAN_ENABLE_RENDER_WORKER", "1") == "1"
    render_worker_timeout_sec: int = int(os.getenv("METAHUMAN_RENDER_WORKER_TIMEOUT_SEC", "300"))
    legacy_adapter_url: str = os.getenv("METAHUMAN_LEGACY_ADAPTER_URL", "http://127.0.0.1:35505")
    enable_legacy_adapter: bool = os.getenv("METAHUMAN_ENABLE_LEGACY_ADAPTER", "0") == "1"
    legacy_adapter_timeout_sec: int = int(os.getenv("METAHUMAN_LEGACY_ADAPTER_TIMEOUT_SEC", "900"))
    content_worker_url: str = os.getenv("METAHUMAN_CONTENT_WORKER_URL", "http://127.0.0.1:35605")
    enable_content_worker: bool = os.getenv("METAHUMAN_ENABLE_CONTENT_WORKER", "1") == "1"
    content_worker_timeout_sec: int = int(os.getenv("METAHUMAN_CONTENT_WORKER_TIMEOUT_SEC", "180"))
    output_root: Path = Path(
        os.getenv("METAHUMAN_OUTPUT_ROOT", str(REPO_ROOT / ".runtime" / "outputs"))
    )


runtime_config = RuntimeConfig()
