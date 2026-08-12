import asyncio
import re
import subprocess
import time
import wave
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .runtime_config import tts_worker_config

VOICE_PROFILES = {
    "conversational_male_zh": {"label": "日常对话男声", "edge_voice": "zh-CN-YunjianNeural"},
    "realistic_male_zh": {"label": "自然口播男声", "edge_voice": "zh-CN-YunxiNeural"},
    "clear_male_zh": {"label": "清晰男声", "edge_voice": "zh-CN-YunyangNeural"},
    "serious_male_zh": {"label": "稳重男声", "edge_voice": "zh-CN-YunjianNeural"},
    "warm_female_zh": {"label": "自然女声", "edge_voice": "zh-CN-XiaoxiaoNeural"},
    "lively_female_zh": {"label": "活力女声", "edge_voice": "zh-CN-XiaoyiNeural"},
}


class TtsJobCreate(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    voice_id: str = Field(default="clear_male_zh")
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    dry_run: bool = Field(default=False)


app = FastAPI(title="YanYing TTS Worker", version="0.1.0")
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
        "bind_host": tts_worker_config.bind_host,
        "provider": tts_worker_config.provider,
        "edge_voice": tts_worker_config.edge_voice,
        "enhance_audio": False,
        "enhancement_preset": None,
        "voice_profiles": [
            {"voice_id": voice_id, **profile} for voice_id, profile in VOICE_PROFILES.items()
        ],
    }


@app.get("/api/tts/voices")
def list_voices() -> dict[str, object]:
    return {
        "items": [{"voice_id": voice_id, **profile} for voice_id, profile in VOICE_PROFILES.items()]
    }


@app.post("/api/tts/jobs")
def create_tts_job(payload: TtsJobCreate) -> dict[str, object]:
    job_id = f"tts_{uuid4().hex[:12]}"
    if payload.dry_run:
        return {
            "job_id": job_id,
            "status": "completed",
            "progress": 100,
            "dry_run": True,
            "voice_id": payload.voice_id,
            "audio_path": None,
            "message": "Dry-run TTS job completed.",
        }

    date_folder = datetime.now().strftime("%Y%m%d")
    job_dir = tts_worker_config.output_root / "audio" / date_folder / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    output_path = job_dir / "speech.wav"
    profile = VOICE_PROFILES.get(payload.voice_id, VOICE_PROFILES["clear_male_zh"])

    provider_used = "edge_neural"
    edge_error = None
    subtitle_segments: list[dict[str, object]] = []
    for attempt in range(1, 4):
        try:
            subtitle_segments = _synthesize_edge(
                text=payload.text,
                voice=str(profile["edge_voice"]),
                speed=payload.speed,
                output_path=output_path,
            )
            if not _is_valid_wave(output_path):
                raise RuntimeError("Edge TTS produced an invalid WAV file.")
            edge_error = None
            break
        except Exception as exc:
            edge_error = f"attempt {attempt}/3: {exc}"
            if attempt < 3:
                time.sleep(attempt)

    if edge_error:
        provider_used = "windows_sapi"
        try:
            _synthesize_windows_sapi(
                text=payload.text, speed=payload.speed, output_path=output_path
            )
            if not _is_valid_wave(output_path):
                raise RuntimeError("Windows SAPI produced an invalid WAV file.")
        except Exception as fallback_exc:
            return {
                "job_id": job_id,
                "status": "failed",
                "progress": 0,
                "dry_run": False,
                "voice_id": payload.voice_id,
                "audio_path": None,
                "message": f"Edge TTS failed ({edge_error}); Windows SAPI failed ({fallback_exc}).",
            }

    if not subtitle_segments:
        subtitle_segments = _approximate_subtitle_segments(
            payload.text, _wave_duration(output_path)
        )

    _cleanup_success_artifacts(output_path)

    return {
        "job_id": job_id,
        "status": "completed",
        "progress": 100,
        "dry_run": False,
        "voice_id": payload.voice_id,
        "provider": provider_used,
        "audio_path": str(output_path),
        "subtitle_segments": subtitle_segments,
        "message": "Speech audio generated.",
    }


def _synthesize_edge(
    *, text: str, voice: str, speed: float, output_path: Path
) -> list[dict[str, object]]:
    import edge_tts

    mp3_path = output_path.with_suffix(".mp3")
    _remove_if_exists(mp3_path)
    _remove_if_exists(output_path)
    rate_percent = round((speed - 1.0) * 100)
    rate = f"{rate_percent:+d}%"
    boundaries: list[dict[str, object]] = []

    async def synthesize() -> None:
        communicate = edge_tts.Communicate(text, voice, rate=rate)
        with mp3_path.open("wb") as audio_file:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_file.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    boundaries.append(
                        {
                            "start": float(chunk["offset"]) / 10_000_000,
                            "end": float(chunk["offset"] + chunk["duration"]) / 10_000_000,
                            "text": str(chunk["text"]),
                        }
                    )

    asyncio.run(synthesize())
    if not mp3_path.exists() or mp3_path.stat().st_size < 1024:
        raise RuntimeError("Edge TTS returned an empty audio stream.")
    command = [
        tts_worker_config.ffmpeg_path,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(mp3_path),
        "-ac",
        "1",
        "-ar",
        "24000",
        "-c:a",
        "pcm_s16le",
        str(output_path),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=180, check=False)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "ffmpeg could not convert Edge TTS audio.")
    return _group_word_boundaries(boundaries)


def _join_boundary_text(current: str, addition: str) -> str:
    addition = addition.strip()
    if not current or not addition:
        return current + addition
    needs_space = (
        current[-1].isascii()
        and current[-1].isalnum()
        and addition[0].isascii()
        and addition[0].isalnum()
    )
    return f"{current} {addition}" if needs_space else current + addition


def _group_word_boundaries(
    boundaries: list[dict[str, object]], max_chars: int = 14
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    current_text = ""
    current_start = 0.0
    current_end = 0.0
    for boundary in boundaries:
        text = str(boundary.get("text") or "").strip()
        if not text:
            continue
        if not current_text:
            current_start = float(boundary.get("start") or 0.0)
        current_text = _join_boundary_text(current_text, text)
        current_end = float(boundary.get("end") or current_start)
        visible_length = len(re.sub(r"\s+", "", current_text))
        hard_stop = bool(re.search(r"[。！？!?；;]$", current_text))
        soft_stop = visible_length >= 6 and bool(re.search(r"[，,：:]$", current_text))
        if visible_length >= max_chars or hard_stop or soft_stop:
            rows.append(
                {
                    "start": round(current_start, 3),
                    "end": round(current_end, 3),
                    "text": current_text,
                }
            )
            current_text = ""
    if current_text:
        rows.append(
            {"start": round(current_start, 3), "end": round(current_end, 3), "text": current_text}
        )
    for index in range(len(rows) - 1):
        rows[index]["end"] = round(
            max(float(rows[index]["end"]), float(rows[index + 1]["start"])), 3
        )
    return rows


def _split_subtitle_text(text: str, max_chars: int = 14) -> list[str]:
    normalized = re.sub(r"\s+", " ", text).strip()
    rows: list[str] = []
    current = ""
    for char in normalized:
        current += char
        visible_length = len(current.replace(" ", ""))
        if (
            visible_length >= max_chars
            or char in "。！？!?；;"
            or (visible_length >= 6 and char in "，,：:")
        ):
            rows.append(current.strip())
            current = ""
    if current.strip():
        rows.append(current.strip())
    return rows


def _approximate_subtitle_segments(text: str, duration: float) -> list[dict[str, object]]:
    rows = _split_subtitle_text(text)
    if not rows or duration <= 0:
        return []
    weights = [max(1, len(row.replace(" ", ""))) for row in rows]
    total_weight = sum(weights)
    cursor = 0.0
    segments: list[dict[str, object]] = []
    for index, (row, weight) in enumerate(zip(rows, weights)):
        end = duration if index == len(rows) - 1 else cursor + duration * weight / total_weight
        segments.append({"start": round(cursor, 3), "end": round(end, 3), "text": row})
        cursor = end
    return segments


def _wave_duration(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as audio:
            return audio.getnframes() / float(audio.getframerate())
    except (wave.Error, OSError, ZeroDivisionError):
        return 0.0


def _synthesize_windows_sapi(*, text: str, speed: float, output_path: Path) -> None:
    text_path = output_path.with_name("speech_text.txt")
    script_path = output_path.with_name("synthesize_sapi.ps1")
    _remove_if_exists(output_path)
    text_path.write_text(text, encoding="utf-8")
    sapi_rate = max(-10, min(10, round((speed - 1.0) * 10)))
    script = "\n".join(
        [
            "Add-Type -AssemblyName System.Speech",
            "$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer",
            "$zhVoice = $speaker.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -eq 'zh-CN' } | Select-Object -First 1",
            "if ($null -ne $zhVoice) { $speaker.SelectVoice($zhVoice.VoiceInfo.Name) }",
            f"$speaker.Rate = {sapi_rate}",
            f"$text = [System.IO.File]::ReadAllText('{_ps_quote(text_path)}', [System.Text.Encoding]::UTF8)",
            f"$speaker.SetOutputToWaveFile('{_ps_quote(output_path)}')",
            "$speaker.Speak($text)",
            "$speaker.Dispose()",
        ]
    )
    script_path.write_text(script, encoding="utf-8-sig")
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script_path)],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "Windows SAPI synthesis failed.")


def _ps_quote(path: Path) -> str:
    return str(path).replace("'", "''")


def _is_valid_wave(path: Path) -> bool:
    if not path.exists() or path.stat().st_size < 1024:
        return False
    try:
        with wave.open(str(path), "rb") as audio:
            return audio.getnframes() > 100 and audio.getnchannels() >= 1
    except (wave.Error, OSError):
        return False


def _cleanup_success_artifacts(output_path: Path) -> None:
    for path in (
        output_path.with_suffix(".mp3"),
        output_path.with_name("speech_text.txt"),
        output_path.with_name("synthesize_sapi.ps1"),
    ):
        _remove_if_exists(path)


def _remove_if_exists(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
