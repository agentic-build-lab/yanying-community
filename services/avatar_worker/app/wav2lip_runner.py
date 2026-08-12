import os
import shutil
import subprocess
from pathlib import Path

from .runtime_config import avatar_worker_config


class Wav2LipError(RuntimeError):
    pass


def _assert_file(path: Path, label: str, min_size: int = 1) -> None:
    if not path.exists():
        raise Wav2LipError(f"{label} not found: {path}")
    if path.stat().st_size < min_size:
        raise Wav2LipError(f"{label} is too small: {path}")


def run_wav2lip(*, image_path: Path, audio_path: Path, output_dir: Path) -> Path:
    image_path = image_path.resolve()
    audio_path = audio_path.resolve()
    output_dir = output_dir.resolve()
    repo_path = avatar_worker_config.wav2lip_repo_path.resolve()
    checkpoint_path = avatar_worker_config.wav2lip_checkpoint_path.resolve()
    dependency_path = avatar_worker_config.wav2lip_dependency_path.resolve()
    inference_script = repo_path / "inference.py"
    output_path = output_dir / "lip_sync.mp4"

    _assert_file(image_path, "Avatar image")
    _assert_file(audio_path, "Audio file")
    _assert_file(inference_script, "Wav2Lip inference script")
    _assert_file(checkpoint_path, "Wav2Lip checkpoint", min_size=400 * 1024 * 1024)
    _assert_file(
        repo_path / "face_detection" / "detection" / "sfd" / "s3fd.pth",
        "Wav2Lip face detector",
        min_size=2 * 1024 * 1024,
    )

    output_dir.mkdir(parents=True, exist_ok=True)

    environment = os.environ.copy()
    python_path_parts = [str(dependency_path), str(repo_path)]
    if environment.get("PYTHONPATH"):
        python_path_parts.append(environment["PYTHONPATH"])
    environment["PYTHONPATH"] = os.pathsep.join(python_path_parts)

    command = [
        avatar_worker_config.wav2lip_python,
        str(inference_script),
        "--checkpoint_path",
        str(checkpoint_path),
        "--face",
        str(image_path),
        "--audio",
        str(audio_path),
        "--outfile",
        str(output_path),
        "--pads",
        "0",
        "12",
        "0",
        "0",
        "--resize_factor",
        "1",
        "--nosmooth",
    ]
    if image_path.suffix.lower() in {".jpg", ".jpeg", ".png"}:
        command.extend(["--static", "True", "--fps", str(avatar_worker_config.wav2lip_fps)])

    result = subprocess.run(
        command,
        cwd=output_dir,
        env=environment,
        capture_output=True,
        text=True,
        timeout=600,
    )

    if result.returncode != 0:
        details = (result.stderr or result.stdout or "Wav2Lip failed.").strip()
        raise Wav2LipError(details[-2400:])

    _assert_file(output_path, "Wav2Lip output", min_size=64 * 1024)
    shutil.rmtree(output_dir / "temp", ignore_errors=True)
    return output_path
