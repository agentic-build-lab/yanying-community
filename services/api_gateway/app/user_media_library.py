import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import BinaryIO
from urllib.parse import urlparse
from uuid import uuid4

AUDIO_EXTENSIONS = {".aac", ".flac", ".m4a", ".mp3", ".ogg", ".opus", ".wav", ".webm"}
VOICE_REFERENCE_EXTENSIONS = AUDIO_EXTENSIONS | {".avi", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg"}
MAX_BACKGROUND_MUSIC_BYTES = 300 * 1024 * 1024
MAX_VOICE_REFERENCE_BYTES = 1024 * 1024 * 1024
MIN_VOICE_REFERENCE_SECONDS = 3
MAX_VOICE_REFERENCE_SECONDS = 40


class UserMediaError(ValueError):
    pass


class UserMediaLibrary:
    def __init__(self, storage_path: Path, media_root: Path) -> None:
        self._storage_path = storage_path
        self._media_root = media_root
        self._lock = RLock()
        self._records = self._load_records()

    def list_background_music(self) -> list[dict[str, object]]:
        with self._lock:
            return json.loads(
                json.dumps(self._records.get("background_music", []), ensure_ascii=False)
            )

    def import_background_music(
        self,
        *,
        source: BinaryIO,
        filename: str,
        content_type: str | None,
        display_name: str | None,
    ) -> dict[str, object]:
        extension = _validated_extension(filename, AUDIO_EXTENSIONS, "仅支持常见音频格式。")
        media_id = f"music_{uuid4().hex[:12]}"
        safe_stem = _safe_stem(display_name or Path(filename).stem, "自定义背景音乐")
        relative_path = Path("library") / "background_music" / f"{media_id}_{safe_stem}{extension}"
        output_path = self._media_root / relative_path
        size_bytes = _copy_limited(source, output_path, MAX_BACKGROUND_MUSIC_BYTES)
        record = {
            "id": media_id,
            "name": display_name.strip()
            if display_name and display_name.strip()
            else Path(filename).stem,
            "url": f"/media/{relative_path.as_posix()}",
            "mime_type": content_type or "audio/*",
            "size_bytes": size_bytes,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source": "user_import",
        }
        with self._lock:
            self._records.setdefault("background_music", []).append(record)
            self._persist()
        return dict(record)

    def delete_background_music(self, media_id: str) -> bool:
        with self._lock:
            records = self._records.setdefault("background_music", [])
            target = next((item for item in records if item.get("id") == media_id), None)
            if target is None:
                return False
            records.remove(target)
            self._persist()
        url = str(target.get("url") or "")
        if url.startswith("/media/"):
            path = (self._media_root / url.removeprefix("/media/")).resolve()
            try:
                path.relative_to(self._media_root.resolve())
            except ValueError:
                return True
            path.unlink(missing_ok=True)
        return True

    def prepare_voice_reference(
        self,
        *,
        source: BinaryIO,
        filename: str,
        content_type: str | None,
    ) -> dict[str, object]:
        extension = _validated_extension(
            filename, VOICE_REFERENCE_EXTENSIONS, "仅支持常见音频或视频格式。"
        )
        reference_id = f"voice_reference_{uuid4().hex[:12]}"
        reference_dir = self._media_root / "library" / "voice_references" / reference_id
        source_path = reference_dir / f"source{extension}"
        size_bytes = _copy_limited(source, source_path, MAX_VOICE_REFERENCE_BYTES)
        source_duration_seconds = _probe_duration(source_path)
        if source_duration_seconds is None:
            shutil.rmtree(reference_dir, ignore_errors=True)
            raise UserMediaError("无法读取声音素材时长，请换用常见的音频或视频格式。")
        if source_duration_seconds < MIN_VOICE_REFERENCE_SECONDS:
            shutil.rmtree(reference_dir, ignore_errors=True)
            raise UserMediaError("声音素材至少需要 3 秒。")
        if source_duration_seconds > MAX_VOICE_REFERENCE_SECONDS:
            shutil.rmtree(reference_dir, ignore_errors=True)
            raise UserMediaError("声音素材不能超过 40 秒，请先截取一段纯净人声。")
        output_path = reference_dir / "reference_32k_mono.wav"
        try:
            ffmpeg_path = _find_ffmpeg()
            command = [
                str(ffmpeg_path),
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(source_path),
                "-map",
                "0:a:0",
                "-t",
                str(MAX_VOICE_REFERENCE_SECONDS),
                "-ac",
                "1",
                "-ar",
                "32000",
                "-c:a",
                "pcm_s16le",
                str(output_path),
            ]
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=180, check=False
            )
        except UserMediaError:
            shutil.rmtree(reference_dir, ignore_errors=True)
            raise
        except (OSError, subprocess.SubprocessError) as exc:
            shutil.rmtree(reference_dir, ignore_errors=True)
            raise UserMediaError(f"音视频处理失败：{exc}") from exc
        if result.returncode != 0 or not output_path.is_file() or output_path.stat().st_size == 0:
            shutil.rmtree(reference_dir, ignore_errors=True)
            detail = (result.stderr or "FFmpeg 没有生成音频。").strip().splitlines()[-1]
            raise UserMediaError(f"无法从该文件提取声音：{detail}")
        duration_seconds = _probe_duration(output_path)
        if duration_seconds is not None and duration_seconds < MIN_VOICE_REFERENCE_SECONDS:
            shutil.rmtree(reference_dir, ignore_errors=True)
            raise UserMediaError("声音样本至少需要 3 秒。")
        relative_path = output_path.relative_to(self._media_root)
        return {
            "id": reference_id,
            "name": Path(filename).stem,
            "media_url": f"/media/{relative_path.as_posix()}",
            "file_name": output_path.name,
            "mime_type": "audio/wav",
            "source_mime_type": content_type or "application/octet-stream",
            "source_size_bytes": size_bytes,
            "duration_seconds": duration_seconds,
        }

    def extract_video_frame(self, *, video_source: str, time_seconds: float) -> dict[str, object]:
        source = _validated_video_source(video_source, self._media_root)
        selected_time = max(0, min(float(time_seconds), 36000))
        frame_id = f"cover_frame_{uuid4().hex[:12]}"
        relative_path = Path("library") / "cover_frames" / f"{frame_id}.jpg"
        output_path = self._media_root / relative_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            str(_find_ffmpeg()),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{selected_time:.3f}",
            "-i",
            source,
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(output_path),
        ]
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=120, check=False
            )
        except (OSError, subprocess.SubprocessError) as exc:
            output_path.unlink(missing_ok=True)
            raise UserMediaError(f"视频取帧失败：{exc}") from exc
        if result.returncode != 0 or not output_path.is_file() or output_path.stat().st_size == 0:
            output_path.unlink(missing_ok=True)
            detail = (result.stderr or "FFmpeg 没有生成画面。").strip().splitlines()[-1]
            raise UserMediaError(f"无法截取视频画面：{detail}")
        return {
            "id": frame_id,
            "image_url": f"/media/{relative_path.as_posix()}",
            "time_seconds": selected_time,
        }

    def _load_records(self) -> dict[str, list[dict[str, object]]]:
        if not self._storage_path.is_file():
            return {"background_music": []}
        try:
            payload = json.loads(self._storage_path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {"background_music": []}
        except (OSError, json.JSONDecodeError):
            return {"background_music": []}

    def _persist(self) -> None:
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self._storage_path.with_suffix(f"{self._storage_path.suffix}.tmp")
        temporary_path.write_text(
            json.dumps(self._records, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary_path.replace(self._storage_path)


def _validated_extension(filename: str, allowed: set[str], message: str) -> str:
    extension = Path(filename or "").suffix.lower()
    if extension not in allowed:
        raise UserMediaError(message)
    return extension


def _safe_stem(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "_", value.strip()).strip("_")
    return (cleaned or fallback)[:80]


def _copy_limited(source: BinaryIO, output_path: Path, max_bytes: int) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    size_bytes = 0
    try:
        source.seek(0)
        with output_path.open("wb") as destination:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                size_bytes += len(chunk)
                if size_bytes > max_bytes:
                    raise UserMediaError("上传文件过大。")
                destination.write(chunk)
    except Exception:
        output_path.unlink(missing_ok=True)
        raise
    if size_bytes == 0:
        output_path.unlink(missing_ok=True)
        raise UserMediaError("上传文件为空。")
    return size_bytes


def _find_ffmpeg() -> Path:
    executable = shutil.which("ffmpeg")
    if executable:
        return Path(executable)
    project_root = Path(__file__).resolve().parents[3]
    candidates = [
        project_root
        / "packages"
        / "legacy_runtime"
        / "_internal"
        / "app3_server"
        / "_internal"
        / "static"
        / "ffmpeg"
        / "bin"
        / "ffmpeg.exe",
        project_root / "work" / "python_runtime" / "ffmpeg" / "bin" / "ffmpeg.exe",
    ]
    candidate = next((path for path in candidates if path.is_file()), None)
    if candidate is None:
        raise UserMediaError("未找到 FFmpeg，无法处理音视频文件。")
    return candidate


def _validated_video_source(value: str, media_root: Path) -> str:
    source = value.strip()
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"}:
        if parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise UserMediaError("只允许从本机服务截取视频画面。")
        return source
    path = Path(source).expanduser().resolve()
    try:
        path.relative_to(media_root.resolve())
    except ValueError as exc:
        raise UserMediaError("只能从项目生成目录中的视频截取画面。") from exc
    if not path.is_file():
        raise UserMediaError("没有找到可截帧的视频文件。")
    return str(path)


def _probe_duration(path: Path) -> float | None:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    try:
        return round(float(result.stdout.strip()), 3) if result.returncode == 0 else None
    except ValueError:
        return None
