from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

import cv2
import numpy as np
from apply_mouth_region_preservation import (
    build_soft_mask,
    mouth_box_from_face,
    parse_box,
    read_video_frames,
)
from crop_video_to_face_track import detect_faces_haar, fill_missing_boxes, smooth_boxes


def smoothstep(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


def read_neutral_image(neutral_image_path: Path) -> np.ndarray:
    image = cv2.imread(str(neutral_image_path), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f"Could not read neutral image: {neutral_image_path}")
    return image


def detect_neutral_mouth_crop(
    neutral_frame: np.ndarray,
    mouth_rel_box: tuple[float, float, float, float],
    mouth_expand: float,
    detection_width: int,
) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    detections = detect_faces_haar([neutral_frame], detection_width)
    boxes, _ = fill_missing_boxes([neutral_frame], detections)
    mouth_box = mouth_box_from_face(boxes[0], neutral_frame.shape, mouth_rel_box, mouth_expand)
    x1, y1, x2, y2 = mouth_box
    crop = neutral_frame[y1:y2, x1:x2].copy()
    if crop.size == 0:
        raise RuntimeError("Neutral mouth crop is empty")
    return crop, mouth_box


def match_patch_color(patch: np.ndarray, target: np.ndarray) -> np.ndarray:
    patch_f = patch.astype(np.float32)
    target_f = target.astype(np.float32)
    for channel in range(3):
        patch_channel = patch_f[..., channel]
        target_channel = target_f[..., channel]
        patch_std = float(np.std(patch_channel))
        target_std = float(np.std(target_channel))
        if patch_std < 1e-4 or target_std < 1e-4:
            patch_f[..., channel] += float(np.mean(target_channel) - np.mean(patch_channel))
        else:
            patch_f[..., channel] = (patch_channel - float(np.mean(patch_channel))) * (
                target_std / patch_std
            ) + float(np.mean(target_channel))
    return np.clip(patch_f, 0, 255).astype(np.uint8)


def write_video_preserving_frames(
    frames_dir: Path,
    input_video: Path,
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
        str(input_video),
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
        description="Blend a neutral closed-mouth reference into the final silent outro."
    )
    parser.add_argument("--input-video", type=Path, required=True)
    parser.add_argument("--neutral-image", type=Path, required=True)
    parser.add_argument("--output-video", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--report-json", type=Path, default=None)
    parser.add_argument("--outro-sec", type=float, default=0.8)
    parser.add_argument("--full-strength-sec", type=float, default=0.25)
    parser.add_argument("--mouth-rel-box", default="0.22,0.58,0.78,0.86")
    parser.add_argument("--mouth-expand", type=float, default=1.26)
    parser.add_argument("--blend-strength", type=float, default=0.92)
    parser.add_argument("--mask-blur", type=int, default=35)
    parser.add_argument("--smoothing-window", type=int, default=7)
    parser.add_argument("--detection-width", type=int, default=640)
    parser.add_argument("--video-crf", type=int, default=12)
    parser.add_argument("--video-preset", default="slow")
    parser.add_argument("--timeout-sec", type=int, default=900)
    parser.add_argument("--keep-frames", action="store_true")
    args = parser.parse_args()

    input_video = args.input_video.resolve()
    neutral_image = args.neutral_image.resolve()
    output_video = args.output_video.resolve()
    work_dir = args.work_dir.resolve()
    report_json = args.report_json.resolve() if args.report_json else None
    mouth_rel_box = parse_box(args.mouth_rel_box)

    frames, fps = read_video_frames(input_video)
    neutral_frame = read_neutral_image(neutral_image)
    neutral_mouth_crop, neutral_mouth_box = detect_neutral_mouth_crop(
        neutral_frame,
        mouth_rel_box,
        args.mouth_expand,
        args.detection_width,
    )

    detections = detect_faces_haar(frames, args.detection_width)
    boxes, fallback_count = fill_missing_boxes(frames, detections)
    boxes = smooth_boxes(boxes, args.smoothing_window)

    frame_count = len(frames)
    outro_frames = max(1, int(round(args.outro_sec * fps)))
    full_strength_frames = max(0, int(round(args.full_strength_sec * fps)))
    start_index = max(0, frame_count - outro_frames)
    ramp_frames = max(1, outro_frames - full_strength_frames)

    frames_dir = work_dir / "neutral_mouth_outro_frames"
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    frames_dir.mkdir(parents=True, exist_ok=True)

    applied_frames = 0
    blend_values: list[float] = []
    mouth_boxes: list[list[int]] = []
    for index, (frame, face_box) in enumerate(zip(frames, boxes)):
        output = frame.copy()
        if index >= start_index:
            progress = (index - start_index + 1) / ramp_frames
            if index >= frame_count - full_strength_frames:
                progress = 1.0
            strength = args.blend_strength * smoothstep(progress)
            mouth_box = mouth_box_from_face(face_box, frame.shape, mouth_rel_box, args.mouth_expand)
            x1, y1, x2, y2 = mouth_box
            target_width = max(1, x2 - x1)
            target_height = max(1, y2 - y1)
            resized_neutral = cv2.resize(
                neutral_mouth_crop,
                (target_width, target_height),
                interpolation=cv2.INTER_AREA,
            )
            resized_neutral = match_patch_color(resized_neutral, output[y1:y2, x1:x2])
            neutral_layer = output.copy()
            neutral_layer[y1:y2, x1:x2] = resized_neutral
            mask = build_soft_mask(frame.shape, mouth_box, strength, args.mask_blur)
            output = (
                output.astype(np.float32) * (1.0 - mask) + neutral_layer.astype(np.float32) * mask
            )
            output = np.clip(output, 0, 255).astype(np.uint8)
            applied_frames += 1
            blend_values.append(float(strength))
            mouth_boxes.append([int(value) for value in mouth_box])

        cv2.imwrite(
            str(frames_dir / f"{index + 1:06d}.png"), output, [int(cv2.IMWRITE_PNG_COMPRESSION), 2]
        )

    output_video.parent.mkdir(parents=True, exist_ok=True)
    write_video_preserving_frames(
        frames_dir,
        input_video,
        output_video,
        fps,
        args.video_crf,
        args.video_preset,
        args.timeout_sec,
    )

    if not args.keep_frames:
        shutil.rmtree(frames_dir, ignore_errors=True)

    report = {
        "input_video": str(input_video),
        "neutral_image": str(neutral_image),
        "output_video": str(output_video),
        "fps": fps,
        "frame_count": frame_count,
        "outro_sec": args.outro_sec,
        "outro_frames": outro_frames,
        "start_frame_index_zero_based": start_index,
        "applied_frames": applied_frames,
        "blend_strength": args.blend_strength,
        "average_applied_strength": round(float(np.mean(blend_values)), 6) if blend_values else 0.0,
        "final_applied_strength": round(float(blend_values[-1]), 6) if blend_values else 0.0,
        "neutral_mouth_box": [int(value) for value in neutral_mouth_box],
        "fallback_detection_count": fallback_count,
        "fallback_detection_ratio": round(fallback_count / frame_count, 4) if frame_count else 0.0,
        "average_target_mouth_box": [
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
