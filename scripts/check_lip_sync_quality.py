import argparse
import json
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

DEFAULT_ROIS = {
    "portrait_right_mouth": (0.42, 0.39, 0.72, 0.58),
    "portrait_center_face": (0.32, 0.30, 0.70, 0.60),
    "portrait_upper_center": (0.34, 0.22, 0.68, 0.50),
    "landscape_center_face": (0.35, 0.18, 0.65, 0.55),
}


@dataclass(frozen=True)
class AudioTrack:
    samples: np.ndarray
    sample_rate: int

    @property
    def duration_sec(self) -> float:
        return float(len(self.samples) / self.sample_rate) if self.sample_rate else 0.0


def run_command(command: list[str], timeout: int = 180) -> None:
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout or f"Command failed: {' '.join(command)}")


def convert_to_wav(input_path: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run_command(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(input_path),
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(output_path),
        ],
        timeout=180,
    )


def read_wav(path: Path) -> AudioTrack:
    with wave.open(str(path), "rb") as audio_file:
        sample_rate = audio_file.getframerate()
        frames = audio_file.readframes(audio_file.getnframes())
    samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    return AudioTrack(samples=samples, sample_rate=sample_rate)


def rms(samples: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(samples)))) if len(samples) else 0.0


def pearson(a: np.ndarray, b: np.ndarray) -> float:
    size = min(len(a), len(b))
    if size <= 1:
        return 0.0
    a = a[:size] - np.mean(a[:size])
    b = b[:size] - np.mean(b[:size])
    denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denominator <= 1e-12:
        return 0.0
    return float(np.dot(a, b) / denominator)


def audio_envelope(track: AudioTrack, fps: float, count: int) -> np.ndarray:
    values = np.zeros(count, dtype=np.float32)
    half_window = max(1, int(track.sample_rate / fps / 2))
    for index in range(count):
        center = int(index / fps * track.sample_rate)
        start = max(0, center - half_window)
        end = min(len(track.samples), center + half_window)
        values[index] = rms(track.samples[start:end])
    return values


def extract_frames(video_path: Path, frames_dir: Path, fps: float, width: int) -> list[Path]:
    frames_dir.mkdir(parents=True, exist_ok=True)
    pattern = frames_dir / "frame_%05d.jpg"
    run_command(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(video_path),
            "-vf",
            f"fps={fps},scale={width}:-1",
            "-q:v",
            "3",
            str(pattern),
        ],
        timeout=240,
    )
    return sorted(frames_dir.glob("frame_*.jpg"))


def parse_roi(value: str | None) -> dict[str, tuple[float, float, float, float]]:
    if not value or value == "auto":
        return DEFAULT_ROIS
    parts = [float(part.strip()) for part in value.split(",")]
    if len(parts) != 4:
        raise ValueError("--mouth-roi must be x1,y1,x2,y2 using 0..1 frame fractions")
    x1, y1, x2, y2 = parts
    if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
        raise ValueError("--mouth-roi values must be normalized frame fractions in ascending order")
    return {"custom": (x1, y1, x2, y2)}


def read_gray(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        return np.asarray(image.convert("L"), dtype=np.float32) / 255.0


def crop_roi(frame: np.ndarray, roi: tuple[float, float, float, float]) -> np.ndarray:
    height, width = frame.shape[:2]
    x1, y1, x2, y2 = roi
    left = max(0, min(width - 1, int(width * x1)))
    right = max(left + 1, min(width, int(width * x2)))
    top = max(0, min(height - 1, int(height * y1)))
    bottom = max(top + 1, min(height, int(height * y2)))
    return frame[top:bottom, left:right]


def moving_average(values: np.ndarray, window: int) -> np.ndarray:
    if window <= 1 or len(values) < window:
        return values
    kernel = np.ones(window, dtype=np.float32) / window
    return np.convolve(values, kernel, mode="same")


def roi_motion(frames: list[Path], roi: tuple[float, float, float, float]) -> np.ndarray:
    if len(frames) < 3:
        return np.zeros(0, dtype=np.float32)

    previous = crop_roi(read_gray(frames[0]), roi)
    values: list[float] = []
    for frame_path in frames[1:]:
        current = crop_roi(read_gray(frame_path), roi)
        if current.shape != previous.shape:
            previous = current
            continue
        values.append(float(np.mean(np.abs(current - previous))))
        previous = current

    motion = np.asarray(values, dtype=np.float32)
    return moving_average(motion, window=3)


def best_offset(
    motion: np.ndarray,
    envelope: np.ndarray,
    fps: float,
    max_offset_ms: int,
) -> dict[str, float]:
    count = min(len(motion), len(envelope))
    if count <= 4:
        return {"offset_ms": 0.0, "correlation": 0.0}

    motion = motion[:count]
    envelope = moving_average(envelope[:count], window=3)
    max_lag = max(1, int(round(max_offset_ms / 1000 * fps)))
    best = {"offset_ms": 0.0, "correlation": -1.0}

    for lag in range(-max_lag, max_lag + 1):
        if lag > 0:
            corr = pearson(motion[lag:], envelope[:-lag])
        elif lag < 0:
            corr = pearson(motion[:lag], envelope[-lag:])
        else:
            corr = pearson(motion, envelope)
        if corr > best["correlation"]:
            best = {"offset_ms": round(lag / fps * 1000, 1), "correlation": round(corr, 4)}

    return best


def score_visual_sync(
    video_path: Path,
    final_audio: AudioTrack,
    work_dir: Path,
    fps: float,
    frame_width: int,
    rois: dict[str, tuple[float, float, float, float]],
    max_offset_ms: int,
) -> dict[str, object]:
    frames = extract_frames(video_path, work_dir / "frames", fps=fps, width=frame_width)
    if len(frames) < 4:
        return {
            "frames_analyzed": len(frames),
            "status": "insufficient_frames",
            "message": "Not enough frames for visual lip-sync analysis.",
        }

    envelope = audio_envelope(final_audio, fps=fps, count=len(frames) - 1)
    roi_results = []
    for name, roi in rois.items():
        motion = roi_motion(frames, roi)
        offset = best_offset(motion, envelope, fps=fps, max_offset_ms=max_offset_ms)
        roi_results.append(
            {
                "roi": name,
                "roi_box": [round(value, 4) for value in roi],
                "motion_mean": round(float(np.mean(motion)), 5) if len(motion) else 0.0,
                "motion_std": round(float(np.std(motion)), 5) if len(motion) else 0.0,
                "best_offset_ms": offset["offset_ms"],
                "motion_audio_correlation": offset["correlation"],
            }
        )

    best = max(roi_results, key=lambda item: item["motion_audio_correlation"])
    status = "pass"
    if best["motion_std"] < 0.0008:
        status = "fail_no_mouth_motion"
    elif abs(float(best["best_offset_ms"])) > 220:
        status = "needs_review_offset"
    elif float(best["motion_audio_correlation"]) < 0.12:
        status = "needs_review_low_correlation"

    return {
        "status": status,
        "frames_analyzed": len(frames),
        "sample_fps": fps,
        "frame_width": frame_width,
        "selected_roi": best,
        "roi_results": roi_results,
        "note": "This is a lightweight mouth-region motion check, not a full SyncNet LSE score.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check generated talking-head audio and lightweight lip sync quality."
    )
    parser.add_argument("--source-audio", type=Path, default=None)
    parser.add_argument("--final-video", required=True, type=Path)
    parser.add_argument("--work-dir", type=Path, default=Path("work/lip_sync_quality"))
    parser.add_argument(
        "--mouth-roi", default="auto", help="auto or x1,y1,x2,y2 normalized frame fractions"
    )
    parser.add_argument("--sample-fps", type=float, default=12.0)
    parser.add_argument("--frame-width", type=int, default=360)
    parser.add_argument("--max-offset-ms", type=int, default=500)
    args = parser.parse_args()

    args.work_dir.mkdir(parents=True, exist_ok=True)
    final_wav = args.work_dir / "final_video_audio_16k.wav"
    convert_to_wav(args.final_video, final_wav)
    final_audio = read_wav(final_wav)

    audio_result: dict[str, object] = {
        "final_video": str(args.final_video),
        "final_audio_duration_sec": round(final_audio.duration_sec, 3),
        "final_rms": round(rms(final_audio.samples), 5),
    }

    if args.source_audio:
        source_wav = args.work_dir / "source_audio_16k.wav"
        convert_to_wav(args.source_audio, source_wav)
        source_audio = read_wav(source_wav)
        audio_result.update(
            {
                "source_audio": str(args.source_audio),
                "source_duration_sec": round(source_audio.duration_sec, 3),
                "duration_delta_sec": round(
                    abs(source_audio.duration_sec - final_audio.duration_sec), 3
                ),
                "waveform_correlation": round(
                    pearson(source_audio.samples, final_audio.samples), 4
                ),
                "source_rms": round(rms(source_audio.samples), 5),
            }
        )

    visual_result = score_visual_sync(
        video_path=args.final_video,
        final_audio=final_audio,
        work_dir=args.work_dir,
        fps=args.sample_fps,
        frame_width=args.frame_width,
        rois=parse_roi(args.mouth_roi),
        max_offset_ms=args.max_offset_ms,
    )

    verdict = "pass"
    if args.source_audio:
        duration_delta = float(audio_result.get("duration_delta_sec", 999))
        waveform_correlation = float(audio_result.get("waveform_correlation", 0))
        if duration_delta > 0.1 or waveform_correlation < 0.98:
            verdict = "fail_audio_mismatch"

    if visual_result.get("status") not in {"pass"} and verdict == "pass":
        verdict = str(visual_result.get("status"))

    result = {
        "verdict": verdict,
        "audio": audio_result,
        "visual": visual_result,
        "quality_bar": {
            "audio_track_match": "pass"
            if not args.source_audio
            or (
                float(audio_result.get("duration_delta_sec", 999)) <= 0.1
                and float(audio_result.get("waveform_correlation", 0)) >= 0.98
            )
            else "fail",
            "visual_sync": visual_result.get("status"),
            "perfect_sync_claim": False,
        },
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
