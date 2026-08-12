from __future__ import annotations

import argparse
import os
import runpy
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


class CodeFormerEnhancementError(RuntimeError):
    pass


def _assert_file(path: Path, label: str, min_size: int = 1) -> None:
    if not path.exists():
        raise CodeFormerEnhancementError(f"{label} not found: {path}")
    if path.stat().st_size < min_size:
        raise CodeFormerEnhancementError(f"{label} is too small: {path}")


def _prepend_sys_path(paths: list[Path]) -> None:
    for path in reversed(paths):
        if path.exists():
            sys.path.insert(0, str(path.resolve()))


def _patch_dev_torch_version() -> None:
    import torch

    if ".dev" in torch.__version__:
        torch.__version__ = torch.__version__.split(".dev", 1)[0]


def _find_video(output_dir: Path, input_video: Path) -> Path:
    expected_path = output_dir / f"{input_video.stem}.mp4"
    if expected_path.exists():
        return expected_path

    candidates = sorted(
        output_dir.rglob("*.mp4"), key=lambda item: item.stat().st_mtime, reverse=True
    )
    if not candidates:
        raise CodeFormerEnhancementError(f"CodeFormer did not produce a video under {output_dir}")
    return candidates[0]


def _reencode_video(input_video: Path, output_video: Path, crf: int, preset: str) -> Path:
    temp_video = output_video.with_name(f"{output_video.stem}.tmp{output_video.suffix}")
    if temp_video.exists():
        temp_video.unlink()

    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(input_video),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-preset",
        preset,
        "-crf",
        str(crf),
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(temp_video),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=900)
    if result.returncode != 0:
        details = (result.stderr or result.stdout or "ffmpeg re-encode failed.").strip()
        raise CodeFormerEnhancementError(details[-2400:])

    if output_video.exists():
        output_video.unlink()
    temp_video.replace(output_video)
    return output_video


def main() -> None:
    parser = argparse.ArgumentParser(description="Enhance video faces with local CodeFormer.")
    parser.add_argument(
        "--codeformer-repo",
        type=Path,
        default=REPO_ROOT / "packages" / "face_enhancers" / "codeformer",
    )
    parser.add_argument("--dependency-path", type=Path, action="append", default=[])
    parser.add_argument("--input-video", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--output-video", type=Path, default=None)
    parser.add_argument("--fidelity-weight", type=float, default=0.72)
    parser.add_argument("--upscale", type=int, default=1)
    parser.add_argument("--detection-model", type=str, default="retinaface_resnet50")
    parser.add_argument("--fps", type=float, default=None)
    parser.add_argument("--only-center-face", action="store_true")
    parser.add_argument("--video-crf", type=int, default=12)
    parser.add_argument("--video-preset", type=str, default="slow")
    parser.add_argument("--keep-intermediates", action="store_true")
    args = parser.parse_args()

    codeformer_repo = args.codeformer_repo.resolve()
    input_video = args.input_video.resolve()
    output_dir = args.output_dir.resolve()
    output_video = args.output_video.resolve() if args.output_video else None
    inference_script = codeformer_repo / "inference_codeformer.py"
    default_dependency_paths = [
        REPO_ROOT / "work" / "lip_sync_python_packages",
        REPO_ROOT / "work" / "face_enhancement_python_packages",
    ]

    _assert_file(input_video, "Input video", min_size=64 * 1024)
    _assert_file(inference_script, "CodeFormer inference script")
    output_dir.mkdir(parents=True, exist_ok=True)
    if output_video:
        output_video.parent.mkdir(parents=True, exist_ok=True)

    _prepend_sys_path([codeformer_repo, *default_dependency_paths, *args.dependency_path])
    _patch_dev_torch_version()

    original_argv = sys.argv[:]
    original_cwd = Path.cwd()
    try:
        sys.argv = [
            str(inference_script),
            "--input_path",
            str(input_video),
            "--output_path",
            str(output_dir),
            "--fidelity_weight",
            str(args.fidelity_weight),
            "--upscale",
            str(args.upscale),
            "--detection_model",
            args.detection_model,
            "--bg_upsampler",
            "None",
        ]
        if args.only_center_face:
            sys.argv.append("--only_center_face")
        if args.fps:
            sys.argv.extend(["--save_video_fps", str(args.fps)])

        os.chdir(codeformer_repo)
        runpy.run_path(str(inference_script), run_name="__main__")
    finally:
        sys.argv = original_argv
        os.chdir(original_cwd)

    produced_video = _find_video(output_dir, input_video)
    final_video = output_video or produced_video
    if produced_video.resolve() == final_video.resolve():
        high_quality_video = produced_video.with_name(
            f"{produced_video.stem}_hq{produced_video.suffix}"
        )
        produced_video = _reencode_video(
            produced_video, high_quality_video, args.video_crf, args.video_preset
        )
        shutil.copy2(produced_video, final_video)
        if produced_video != final_video:
            produced_video.unlink(missing_ok=True)
        produced_video = final_video
    else:
        produced_video = _reencode_video(
            produced_video, final_video, args.video_crf, args.video_preset
        )

    _assert_file(produced_video, "Enhanced video", min_size=64 * 1024)
    if output_video and not args.keep_intermediates:
        try:
            output_video.relative_to(output_dir)
        except ValueError:
            shutil.rmtree(output_dir, ignore_errors=True)
    print(f"Enhanced video: {produced_video}")


if __name__ == "__main__":
    main()
