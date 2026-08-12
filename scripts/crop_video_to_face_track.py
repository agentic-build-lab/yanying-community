import argparse
import json
import math
import subprocess
from pathlib import Path

import cv2
import numpy as np


def run_command(command: list[str], timeout: int = 300) -> None:
    completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "Command failed.")[-2400:])


def read_video_frames(video_path: Path) -> tuple[list[np.ndarray], float]:
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")

    fps = capture.get(cv2.CAP_PROP_FPS) or 25.0
    frames = []
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        frames.append(frame)
    capture.release()

    if not frames:
        raise RuntimeError(f"No frames decoded from video: {video_path}")
    return frames, float(fps)


def detect_faces_s3fd(
    frames: list[np.ndarray], batch_size: int
) -> list[tuple[int, int, int, int] | None]:
    import face_detection
    import torch

    device = "cuda" if torch.cuda.is_available() else "cpu"
    detector = face_detection.FaceAlignment(
        face_detection.LandmarksType._2D, flip_input=False, device=device
    )

    current_batch = max(1, batch_size)
    while True:
        detections: list[tuple[int, int, int, int] | None] = []
        try:
            for start in range(0, len(frames), current_batch):
                batch = np.asarray(frames[start : start + current_batch])
                detections.extend(detector.get_detections_for_batch(batch))
            break
        except RuntimeError:
            if current_batch == 1:
                raise
            current_batch = max(1, current_batch // 2)

    return [tuple(int(value) for value in box) if box is not None else None for box in detections]


def detect_faces_haar(
    frames: list[np.ndarray], detection_width: int
) -> list[tuple[int, int, int, int] | None]:
    cascade_path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
    classifier = cv2.CascadeClassifier(str(cascade_path))
    if classifier.empty():
        raise RuntimeError(f"Could not load Haar cascade: {cascade_path}")

    detections: list[tuple[int, int, int, int] | None] = []
    for frame in frames:
        height, width = frame.shape[:2]
        scale = min(1.0, detection_width / width) if width else 1.0
        if scale < 1.0:
            small = cv2.resize(
                frame, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_AREA
            )
        else:
            small = frame
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        faces = classifier.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(40, 40))
        if len(faces) == 0:
            detections.append(None)
            continue
        x, y, w, h = max(faces, key=lambda item: item[2] * item[3])
        if scale < 1.0:
            x = int(x / scale)
            y = int(y / scale)
            w = int(w / scale)
            h = int(h / scale)
        detections.append((x, y, x + w, y + h))
    return detections


def fallback_box(frame: np.ndarray) -> tuple[int, int, int, int]:
    height, width = frame.shape[:2]
    side = int(min(width, height) * 0.55)
    center_x = width // 2
    center_y = int(height * 0.38)
    x1 = max(0, center_x - side // 2)
    y1 = max(0, center_y - side // 2)
    x2 = min(width, x1 + side)
    y2 = min(height, y1 + side)
    return x1, y1, x2, y2


def fill_missing_boxes(
    frames: list[np.ndarray], detections: list[tuple[int, int, int, int] | None]
) -> tuple[np.ndarray, int]:
    boxes = []
    fallback_count = 0
    previous: tuple[int, int, int, int] | None = None
    for frame, detection in zip(frames, detections):
        if detection is None:
            fallback_count += 1
            detection = previous or fallback_box(frame)
        boxes.append(detection)
        previous = detection
    return np.asarray(boxes, dtype=np.float32), fallback_count


def smooth_boxes(boxes: np.ndarray, window: int) -> np.ndarray:
    if window <= 1 or len(boxes) < 3:
        return boxes
    radius = window // 2
    smoothed = boxes.copy()
    for index in range(len(boxes)):
        start = max(0, index - radius)
        end = min(len(boxes), index + radius + 1)
        smoothed[index] = np.mean(boxes[start:end], axis=0)
    return smoothed


def crop_square(
    frame: np.ndarray, box: np.ndarray, context_scale: float, target_size: int
) -> np.ndarray:
    height, width = frame.shape[:2]
    x1, y1, x2, y2 = box.tolist()
    center_x = (x1 + x2) / 2
    center_y = (y1 + y2) / 2
    side = max(x2 - x1, y2 - y1) * context_scale
    half = side / 2

    left = int(math.floor(center_x - half))
    right = int(math.ceil(center_x + half))
    top = int(math.floor(center_y - half))
    bottom = int(math.ceil(center_y + half))

    pad_left = max(0, -left)
    pad_top = max(0, -top)
    pad_right = max(0, right - width)
    pad_bottom = max(0, bottom - height)

    safe_left = max(0, left)
    safe_right = min(width, right)
    safe_top = max(0, top)
    safe_bottom = min(height, bottom)
    crop = frame[safe_top:safe_bottom, safe_left:safe_right]
    if any(value > 0 for value in (pad_left, pad_top, pad_right, pad_bottom)):
        crop = cv2.copyMakeBorder(
            crop, pad_top, pad_bottom, pad_left, pad_right, cv2.BORDER_REPLICATE
        )
    return cv2.resize(crop, (target_size, target_size), interpolation=cv2.INTER_AREA)


def write_cropped_video(
    input_video: Path,
    output_video: Path,
    frames_dir: Path,
    fps: float,
    timeout: int,
) -> None:
    output_video.parent.mkdir(parents=True, exist_ok=True)
    run_command(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-framerate",
            f"{fps:.6f}",
            "-i",
            str(frames_dir / "%06d.jpg"),
            "-i",
            str(input_video),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0?",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "15",
            "-preset",
            "slow",
            "-c:a",
            "aac",
            "-shortest",
            str(output_video),
        ],
        timeout=timeout,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a stable face-track crop video for SyncNet evaluation."
    )
    parser.add_argument("--input-video", required=True, type=Path)
    parser.add_argument("--output-video", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--report-json", type=Path, default=None)
    parser.add_argument("--target-size", type=int, default=224)
    parser.add_argument("--context-scale", type=float, default=1.45)
    parser.add_argument("--smoothing-window", type=int, default=7)
    parser.add_argument("--face-det-batch-size", type=int, default=16)
    parser.add_argument("--detector", choices=["haar", "s3fd"], default="haar")
    parser.add_argument("--detection-width", type=int, default=640)
    parser.add_argument("--timeout-sec", type=int, default=600)
    args = parser.parse_args()

    args.input_video = args.input_video.resolve()
    args.output_video = args.output_video.resolve()
    args.work_dir = args.work_dir.resolve()
    if args.report_json:
        args.report_json = args.report_json.resolve()

    frames, fps = read_video_frames(args.input_video)
    if args.detector == "s3fd":
        detections = detect_faces_s3fd(frames, args.face_det_batch_size)
        detector_device = "s3fd_cuda"
    else:
        detections = detect_faces_haar(frames, args.detection_width)
        detector_device = "haar_cpu"
    boxes, fallback_count = fill_missing_boxes(frames, detections)
    boxes = smooth_boxes(boxes, args.smoothing_window)

    frames_dir = args.work_dir / "cropped_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    for index, (frame, box) in enumerate(zip(frames, boxes), start=1):
        cropped = crop_square(frame, box, args.context_scale, args.target_size)
        cv2.imwrite(
            str(frames_dir / f"{index:06d}.jpg"), cropped, [int(cv2.IMWRITE_JPEG_QUALITY), 95]
        )

    write_cropped_video(args.input_video, args.output_video, frames_dir, fps, args.timeout_sec)

    result = {
        "input_video": str(args.input_video),
        "output_video": str(args.output_video),
        "fps": fps,
        "frame_count": len(frames),
        "target_size": args.target_size,
        "context_scale": args.context_scale,
        "smoothing_window": args.smoothing_window,
        "detector": args.detector,
        "detection_width": args.detection_width,
        "fallback_detection_count": fallback_count,
        "fallback_detection_ratio": round(fallback_count / len(frames), 4) if frames else 0.0,
        "device": detector_device,
    }
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.report_json:
        args.report_json.parent.mkdir(parents=True, exist_ok=True)
        args.report_json.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
