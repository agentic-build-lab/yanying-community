from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for dependency_path in (
    REPO_ROOT / "work" / "lip_sync_python_packages",
    REPO_ROOT / "work" / "musetalk_python_packages",
    REPO_ROOT / "work" / "face_enhancement_python_packages",
):
    if dependency_path.exists():
        sys.path.insert(0, str(dependency_path))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from crop_video_to_face_track import (  # noqa: E402
    detect_faces_haar,
    fill_missing_boxes,
    smooth_boxes,
)


def read_video_frames(video_path: Path) -> tuple[list[np.ndarray], float]:
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")

    fps = float(capture.get(cv2.CAP_PROP_FPS) or 25.0)
    frames: list[np.ndarray] = []
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        frames.append(frame)
    capture.release()
    if not frames:
        raise RuntimeError(f"No frames decoded from video: {video_path}")
    return frames, fps


def parse_box(value: str) -> tuple[float, float, float, float]:
    parts = [float(part.strip()) for part in value.split(",")]
    if len(parts) != 4:
        raise ValueError("Box must be x1,y1,x2,y2")
    x1, y1, x2, y2 = parts
    if not (0.0 <= x1 < x2 <= 1.0 and 0.0 <= y1 < y2 <= 1.0):
        raise ValueError("Box values must be normalized and ascending")
    return x1, y1, x2, y2


def clamp_box(
    box: tuple[int, int, int, int],
    width: int,
    height: int,
) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = box
    x1 = max(0, min(width - 1, x1))
    y1 = max(0, min(height - 1, y1))
    x2 = max(x1 + 1, min(width, x2))
    y2 = max(y1 + 1, min(height, y2))
    return x1, y1, x2, y2


def mouth_box_from_face(
    face_box: np.ndarray,
    frame_shape: tuple[int, int, int],
    mouth_rel_box: tuple[float, float, float, float],
    expand: float,
) -> tuple[int, int, int, int]:
    height, width = frame_shape[:2]
    fx1, fy1, fx2, fy2 = [float(value) for value in face_box.tolist()]
    face_width = max(1.0, fx2 - fx1)
    face_height = max(1.0, fy2 - fy1)
    rx1, ry1, rx2, ry2 = mouth_rel_box
    mx1 = fx1 + face_width * rx1
    my1 = fy1 + face_height * ry1
    mx2 = fx1 + face_width * rx2
    my2 = fy1 + face_height * ry2

    center_x = (mx1 + mx2) / 2.0
    center_y = (my1 + my2) / 2.0
    mouth_width = (mx2 - mx1) * expand
    mouth_height = (my2 - my1) * expand
    return clamp_box(
        (
            int(round(center_x - mouth_width / 2.0)),
            int(round(center_y - mouth_height / 2.0)),
            int(round(center_x + mouth_width / 2.0)),
            int(round(center_y + mouth_height / 2.0)),
        ),
        width,
        height,
    )


def build_soft_mask(
    frame_shape: tuple[int, int, int],
    box: tuple[int, int, int, int],
    strength: float,
    blur: int,
) -> np.ndarray:
    height, width = frame_shape[:2]
    x1, y1, x2, y2 = box
    mask = np.zeros((height, width), dtype=np.float32)
    cv2.rectangle(mask, (x1, y1), (x2, y2), color=1.0, thickness=-1)
    blur = max(0, int(blur))
    if blur > 0:
        if blur % 2 == 0:
            blur += 1
        mask = cv2.GaussianBlur(mask, (blur, blur), 0)
    mask = np.clip(mask * max(0.0, min(1.0, strength)), 0.0, 1.0)
    return mask[..., None]


def write_video_with_audio(
    frames_dir: Path,
    enhanced_video: Path,
    output_video: Path,
    fps: float,
    crf: int,
    preset: str,
    timeout: int,
) -> None:
    temp_video = output_video.with_name(f"{output_video.stem}.tmp{output_video.suffix}")
    if temp_video.exists():
        temp_video.unlink()
    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-framerate",
        f"{fps:.6f}",
        "-i",
        str(frames_dir / "%06d.png"),
        "-i",
        str(enhanced_video),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0?",
        "-c:v",
        "libx264",
        "-crf",
        str(crf),
        "-preset",
        preset,
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-shortest",
        str(temp_video),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "ffmpeg encode failed")[-2400:])
    if output_video.exists():
        output_video.unlink()
    temp_video.replace(output_video)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Blend original lip-sync mouth pixels back into a restored video."
    )
    parser.add_argument("--original-video", type=Path, required=True)
    parser.add_argument("--enhanced-video", type=Path, required=True)
    parser.add_argument("--output-video", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--report-json", type=Path, default=None)
    parser.add_argument("--mouth-rel-box", default="0.22,0.58,0.78,0.86")
    parser.add_argument("--mouth-expand", type=float, default=1.18)
    parser.add_argument("--preserve-strength", type=float, default=0.88)
    parser.add_argument("--mask-blur", type=int, default=31)
    parser.add_argument("--smoothing-window", type=int, default=7)
    parser.add_argument("--detection-width", type=int, default=640)
    parser.add_argument("--video-crf", type=int, default=12)
    parser.add_argument("--video-preset", default="slow")
    parser.add_argument("--timeout-sec", type=int, default=900)
    parser.add_argument("--keep-frames", action="store_true")
    args = parser.parse_args()

    original_video = args.original_video.resolve()
    enhanced_video = args.enhanced_video.resolve()
    output_video = args.output_video.resolve()
    work_dir = args.work_dir.resolve()
    report_json = args.report_json.resolve() if args.report_json else None
    mouth_rel_box = parse_box(args.mouth_rel_box)

    original_frames, _ = read_video_frames(original_video)
    enhanced_frames, fps = read_video_frames(enhanced_video)
    frame_count = min(len(original_frames), len(enhanced_frames))
    if frame_count <= 0:
        raise RuntimeError("No overlapping frames between original and enhanced videos")

    original_frames = original_frames[:frame_count]
    enhanced_frames = enhanced_frames[:frame_count]
    detections = detect_faces_haar(enhanced_frames, args.detection_width)
    boxes, fallback_count = fill_missing_boxes(enhanced_frames, detections)
    boxes = smooth_boxes(boxes, args.smoothing_window)

    frames_dir = work_dir / "mouth_preserved_frames"
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    frames_dir.mkdir(parents=True, exist_ok=True)

    mask_coverages = []
    mouth_boxes: list[list[int]] = []
    for index, (original, enhanced, face_box) in enumerate(
        zip(original_frames, enhanced_frames, boxes), start=1
    ):
        if original.shape[:2] != enhanced.shape[:2]:
            original = cv2.resize(
                original, (enhanced.shape[1], enhanced.shape[0]), interpolation=cv2.INTER_AREA
            )
        mouth_box = mouth_box_from_face(face_box, enhanced.shape, mouth_rel_box, args.mouth_expand)
        mask = build_soft_mask(enhanced.shape, mouth_box, args.preserve_strength, args.mask_blur)
        blended = enhanced.astype(np.float32) * (1.0 - mask) + original.astype(np.float32) * mask
        blended = np.clip(blended, 0, 255).astype(np.uint8)
        cv2.imwrite(
            str(frames_dir / f"{index:06d}.png"), blended, [int(cv2.IMWRITE_PNG_COMPRESSION), 2]
        )
        mask_coverages.append(float(np.mean(mask)))
        mouth_boxes.append([int(value) for value in mouth_box])

    output_video.parent.mkdir(parents=True, exist_ok=True)
    write_video_with_audio(
        frames_dir,
        enhanced_video,
        output_video,
        fps,
        args.video_crf,
        args.video_preset,
        args.timeout_sec,
    )

    if not args.keep_frames:
        shutil.rmtree(frames_dir, ignore_errors=True)

    report = {
        "original_video": str(original_video),
        "enhanced_video": str(enhanced_video),
        "output_video": str(output_video),
        "fps": fps,
        "frame_count": frame_count,
        "mouth_rel_box": [round(value, 4) for value in mouth_rel_box],
        "mouth_expand": args.mouth_expand,
        "preserve_strength": args.preserve_strength,
        "mask_blur": args.mask_blur,
        "smoothing_window": args.smoothing_window,
        "fallback_detection_count": fallback_count,
        "fallback_detection_ratio": round(fallback_count / frame_count, 4) if frame_count else 0.0,
        "average_mask_coverage": round(float(np.mean(mask_coverages)), 6)
        if mask_coverages
        else 0.0,
        "average_mouth_box": [
            int(round(value))
            for value in np.asarray(mouth_boxes, dtype=np.float32).mean(axis=0).tolist()
        ]
        if mouth_boxes
        else None,
    }
    if report_json:
        report_json.parent.mkdir(parents=True, exist_ok=True)
        report_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
