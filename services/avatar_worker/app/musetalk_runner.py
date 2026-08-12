import json
import os
import shutil
import subprocess
from pathlib import Path

from .runtime_config import avatar_worker_config


class MuseTalkError(RuntimeError):
    pass


def _process_details(result: subprocess.CompletedProcess[str], fallback: str) -> str:
    sections = []
    if result.stdout and result.stdout.strip():
        sections.append(f"stdout:\n{result.stdout.strip()}")
    if result.stderr and result.stderr.strip():
        sections.append(f"stderr:\n{result.stderr.strip()}")
    return "\n\n".join(sections) or fallback


def _assert_file(path: Path, label: str, min_size: int = 1) -> None:
    if not path.exists():
        raise MuseTalkError(f"{label} not found: {path}")
    if path.stat().st_size < min_size:
        raise MuseTalkError(f"{label} is too small: {path}")


def _json_path(path: Path) -> str:
    return json.dumps(str(path.resolve()).replace("\\", "/"))


def run_musetalk(*, image_path: Path, audio_path: Path, output_dir: Path) -> Path:
    image_path = image_path.resolve()
    audio_path = audio_path.resolve()
    output_dir = output_dir.resolve()
    repo_path = avatar_worker_config.musetalk_repo_path.resolve()
    version = avatar_worker_config.musetalk_version.strip().lower()
    model_dir_name = "musetalkV15" if version == "v15" else "musetalk"
    model_file_name = "unet.pth" if version == "v15" else "pytorch_model.bin"
    unet_model_path = repo_path / "models" / model_dir_name / model_file_name
    unet_config_path = repo_path / "models" / model_dir_name / "musetalk.json"
    sd_vae_dir = repo_path / "models" / "sd-vae"
    whisper_dir = repo_path / "models" / "whisper"
    face_parse_dir = repo_path / "models" / "face-parse-bisent"

    _assert_file(image_path, "Avatar image")
    _assert_file(audio_path, "Audio file")
    _assert_file(repo_path / "scripts" / "inference.py", "MuseTalk inference script")
    _assert_file(unet_model_path, "MuseTalk model", min_size=50 * 1024 * 1024)
    _assert_file(unet_config_path, "MuseTalk config")
    _assert_file(sd_vae_dir / "config.json", "MuseTalk SD-VAE config")
    _assert_file(
        sd_vae_dir / "diffusion_pytorch_model.bin",
        "MuseTalk SD-VAE model",
        min_size=50 * 1024 * 1024,
    )
    _assert_file(whisper_dir / "config.json", "MuseTalk whisper config")
    _assert_file(
        whisper_dir / "pytorch_model.bin", "MuseTalk whisper model", min_size=50 * 1024 * 1024
    )
    _assert_file(whisper_dir / "preprocessor_config.json", "MuseTalk whisper preprocessor")
    _assert_file(
        face_parse_dir / "79999_iter.pth", "MuseTalk face parsing model", min_size=10 * 1024 * 1024
    )
    _assert_file(
        face_parse_dir / "resnet18-5c106cde.pth",
        "MuseTalk face parsing backbone",
        min_size=10 * 1024 * 1024,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    inference_config_path = output_dir / "musetalk_inference.yaml"
    result_dir = output_dir / "musetalk_results"
    output_path = output_dir / "musetalk_lip_sync.mp4"

    inference_config_path.write_text(
        "\n".join(
            [
                "task_0:",
                f" video_path: {_json_path(image_path)}",
                f" audio_path: {_json_path(audio_path)}",
                ' result_name: "musetalk_lip_sync.mp4"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    environment = os.environ.copy()
    python_path_parts = [
        str(repo_path),
        str(avatar_worker_config.wav2lip_dependency_path.resolve()),
        str(avatar_worker_config.musetalk_dependency_path.resolve()),
    ]
    if environment.get("PYTHONPATH"):
        python_path_parts.append(environment["PYTHONPATH"])
    environment["PYTHONPATH"] = os.pathsep.join(python_path_parts)
    musetalk_torch_home = avatar_worker_config.musetalk_torch_home.resolve()
    musetalk_torch_home.mkdir(parents=True, exist_ok=True)
    environment.setdefault("TORCH_HOME", str(musetalk_torch_home))

    command = [
        avatar_worker_config.musetalk_python,
        "-m",
        "scripts.inference",
        "--inference_config",
        str(inference_config_path.resolve()),
        "--result_dir",
        str(result_dir.resolve()),
        "--unet_model_path",
        str(unet_model_path),
        "--unet_config",
        str(unet_config_path),
        "--whisper_dir",
        str(whisper_dir),
        "--version",
        version,
        "--fps",
        str(avatar_worker_config.musetalk_fps),
        "--batch_size",
        str(avatar_worker_config.musetalk_batch_size),
        "--extra_margin",
        str(avatar_worker_config.musetalk_extra_margin),
        "--parsing_mode",
        avatar_worker_config.musetalk_parsing_mode,
        "--left_cheek_width",
        str(avatar_worker_config.musetalk_left_cheek_width),
        "--right_cheek_width",
        str(avatar_worker_config.musetalk_right_cheek_width),
        "--audio_padding_length_left",
        str(avatar_worker_config.musetalk_audio_padding_left),
        "--audio_padding_length_right",
        str(avatar_worker_config.musetalk_audio_padding_right),
        "--output_vid_name",
        "musetalk_lip_sync.mp4",
    ]
    if avatar_worker_config.musetalk_ffmpeg_path:
        command.extend(["--ffmpeg_path", avatar_worker_config.musetalk_ffmpeg_path])
    if avatar_worker_config.musetalk_use_float16:
        command.append("--use_float16")

    result = subprocess.run(
        command,
        cwd=repo_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=avatar_worker_config.musetalk_timeout_sec,
    )

    produced_path = result_dir / version / "musetalk_lip_sync.mp4"
    if result.returncode != 0:
        details = _process_details(result, "MuseTalk failed.")
        raise MuseTalkError(details[-6000:])
    if not produced_path.exists():
        details = _process_details(result, "MuseTalk did not produce an output video.")
        raise MuseTalkError(details[-6000:])

    shutil.copy2(produced_path, output_path)
    _assert_file(output_path, "MuseTalk output", min_size=64 * 1024)
    shutil.rmtree(result_dir, ignore_errors=True)
    inference_config_path.unlink(missing_ok=True)
    return output_path
