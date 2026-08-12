import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class TtsWorkerConfig:
    bind_host: str = os.getenv("METAHUMAN_TTS_BIND_HOST", "127.0.0.1")
    provider: str = os.getenv("METAHUMAN_TTS_PROVIDER", "edge_neural")
    edge_voice: str = os.getenv("METAHUMAN_TTS_EDGE_VOICE", "zh-CN-YunjianNeural")
    ffmpeg_path: str = os.getenv("METAHUMAN_FFMPEG_PATH", "ffmpeg")
    output_root: Path = Path(
        os.getenv("METAHUMAN_OUTPUT_ROOT", str(REPO_ROOT / ".runtime" / "outputs"))
    )


tts_worker_config = TtsWorkerConfig()
