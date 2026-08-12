import json
import wave
from pathlib import Path

from .runtime_config import avatar_worker_config


class AudioTailError(RuntimeError):
    pass


def prepare_lip_sync_audio(audio_path: Path, output_dir: Path) -> Path:
    tail_silence_ms = max(0, avatar_worker_config.lip_sync_tail_silence_ms)
    if tail_silence_ms <= 0:
        return audio_path

    if not audio_path.exists():
        raise AudioTailError(f"Audio not found: {audio_path}")

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "lip_sync_audio_tail_padded.wav"
    metadata_path = output_dir / "lip_sync_audio_tail_padded.json"

    try:
        with wave.open(str(audio_path), "rb") as source:
            params = source.getparams()
            if params.comptype != "NONE":
                raise AudioTailError(
                    f"Compressed WAV is not supported for tail padding: {audio_path}"
                )
            frames = source.readframes(params.nframes)
            tail_frames = int(round(params.framerate * tail_silence_ms / 1000))
            silence = _silence_bytes(params.nchannels, params.sampwidth, tail_frames)

        with wave.open(str(output_path), "wb") as target:
            target.setparams(params)
            target.writeframes(frames)
            target.writeframes(silence)
    except wave.Error as exc:
        raise AudioTailError(f"Could not prepare lip-sync tail audio: {audio_path}") from exc

    metadata = {
        "source_audio_path": str(audio_path),
        "output_audio_path": str(output_path),
        "tail_silence_ms": tail_silence_ms,
        "reason": "Let lip-sync models see a short silence tail so the mouth can settle closed after speech.",
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def _silence_bytes(channel_count: int, sample_width: int, frame_count: int) -> bytes:
    if frame_count <= 0:
        return b""
    if sample_width == 1:
        return bytes([128]) * channel_count * frame_count
    return b"\x00" * sample_width * channel_count * frame_count
