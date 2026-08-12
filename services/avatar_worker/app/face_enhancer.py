import os
import subprocess
from pathlib import Path

from .runtime_config import avatar_worker_config


class FaceEnhancementError(RuntimeError):
    pass


def _assert_file(path: Path, label: str, min_size: int = 1) -> None:
    if not path.exists():
        raise FaceEnhancementError(f"{label} not found: {path}")
    if path.stat().st_size < min_size:
        raise FaceEnhancementError(f"{label} is too small: {path}")


def _run_mouth_preservation(
    *, original_video_path: Path, enhanced_video_path: Path, output_dir: Path
) -> Path:
    wrapper_path = avatar_worker_config.codeformer_mouth_preserve_wrapper_path
    output_path = output_dir / "face_enhanced_codeformer_mouth_preserved.mp4"
    report_path = output_dir / "mouth_preservation_report.json"
    work_dir = output_dir / "mouth_preservation"

    _assert_file(wrapper_path, "CodeFormer mouth preservation wrapper")
    _assert_file(original_video_path, "Original lip-sync video", min_size=64 * 1024)
    _assert_file(enhanced_video_path, "CodeFormer output", min_size=64 * 1024)

    environment = os.environ.copy()
    python_path_parts = [
        str(avatar_worker_config.wav2lip_dependency_path),
        str(avatar_worker_config.musetalk_dependency_path),
        str(avatar_worker_config.codeformer_dependency_path),
    ]
    if environment.get("PYTHONPATH"):
        python_path_parts.append(environment["PYTHONPATH"])
    environment["PYTHONPATH"] = os.pathsep.join(python_path_parts)

    command = [
        avatar_worker_config.face_enhancement_python,
        str(wrapper_path),
        "--original-video",
        str(original_video_path),
        "--enhanced-video",
        str(enhanced_video_path),
        "--output-video",
        str(output_path),
        "--work-dir",
        str(work_dir),
        "--report-json",
        str(report_path),
        "--mouth-rel-box",
        avatar_worker_config.codeformer_mouth_preserve_rel_box,
        "--mouth-expand",
        str(avatar_worker_config.codeformer_mouth_preserve_expand),
        "--preserve-strength",
        str(avatar_worker_config.codeformer_mouth_preserve_strength),
        "--mask-blur",
        str(avatar_worker_config.codeformer_mouth_preserve_mask_blur),
        "--video-crf",
        str(avatar_worker_config.codeformer_video_crf),
        "--video-preset",
        avatar_worker_config.codeformer_video_preset,
        "--timeout-sec",
        str(avatar_worker_config.codeformer_mouth_preserve_timeout_sec),
    ]

    result = subprocess.run(
        command,
        cwd=output_dir,
        env=environment,
        capture_output=True,
        text=True,
        timeout=avatar_worker_config.codeformer_mouth_preserve_timeout_sec + 60,
    )
    if result.returncode != 0:
        details = (
            result.stderr or result.stdout or "CodeFormer mouth preservation failed."
        ).strip()
        raise FaceEnhancementError(details[-2400:])

    _assert_file(output_path, "CodeFormer mouth-preserved output", min_size=64 * 1024)
    return output_path


def enhance_face_video(
    *, input_video_path: Path, output_dir: Path, fps: float | None = None
) -> Path:
    input_video_path = input_video_path.resolve()
    output_dir = output_dir.resolve()
    mode = avatar_worker_config.face_enhancement_mode.strip().lower()
    if mode in {"", "off", "none", "disabled"}:
        return input_video_path
    if mode != "codeformer":
        raise FaceEnhancementError(
            f"Unsupported face enhancement mode: {avatar_worker_config.face_enhancement_mode}"
        )

    repo_path = avatar_worker_config.codeformer_repo_path
    wrapper_path = avatar_worker_config.codeformer_wrapper_path
    dependency_path = avatar_worker_config.codeformer_dependency_path
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / "face_enhanced_codeformer.mp4"
    codeformer_work_dir = output_dir / "codeformer"

    _assert_file(input_video_path, "Input video", min_size=64 * 1024)
    _assert_file(wrapper_path, "CodeFormer wrapper")
    _assert_file(repo_path / "inference_codeformer.py", "CodeFormer inference script")

    environment = os.environ.copy()
    python_path_parts = [
        str(repo_path),
        str(avatar_worker_config.wav2lip_dependency_path),
        str(dependency_path),
    ]
    if environment.get("PYTHONPATH"):
        python_path_parts.append(environment["PYTHONPATH"])
    environment["PYTHONPATH"] = os.pathsep.join(python_path_parts)

    command = [
        avatar_worker_config.face_enhancement_python,
        str(wrapper_path),
        "--codeformer-repo",
        str(repo_path),
        "--dependency-path",
        str(avatar_worker_config.wav2lip_dependency_path),
        "--dependency-path",
        str(dependency_path),
        "--input-video",
        str(input_video_path),
        "--output-dir",
        str(codeformer_work_dir),
        "--output-video",
        str(output_path),
        "--fidelity-weight",
        str(avatar_worker_config.codeformer_fidelity_weight),
        "--upscale",
        str(avatar_worker_config.codeformer_upscale),
        "--detection-model",
        avatar_worker_config.codeformer_detection_model,
        "--video-crf",
        str(avatar_worker_config.codeformer_video_crf),
        "--video-preset",
        avatar_worker_config.codeformer_video_preset,
    ]
    if avatar_worker_config.codeformer_only_center_face:
        command.append("--only-center-face")
    if fps:
        command.extend(["--fps", str(fps)])

    result = subprocess.run(
        command,
        cwd=output_dir,
        env=environment,
        capture_output=True,
        text=True,
        timeout=avatar_worker_config.face_enhancement_timeout_sec,
    )

    if result.returncode != 0:
        details = (result.stderr or result.stdout or "CodeFormer face enhancement failed.").strip()
        raise FaceEnhancementError(details[-2400:])

    _assert_file(output_path, "CodeFormer output", min_size=64 * 1024)
    if avatar_worker_config.codeformer_mouth_preserve_enabled:
        return _run_mouth_preservation(
            original_video_path=input_video_path,
            enhanced_video_path=output_path,
            output_dir=output_dir,
        )
    return output_path
