from __future__ import annotations

import argparse
import os
from pathlib import Path

from huggingface_hub import snapshot_download

REPO_ROOT = Path(__file__).resolve().parents[1]


def download_repo(repo_id: str, local_dir: Path, patterns: list[str]) -> None:
    local_dir.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=repo_id,
        local_dir=str(local_dir),
        allow_patterns=patterns,
        local_dir_use_symlinks=False,
        resume_download=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Download MuseTalk 1.5 inference weights.")
    parser.add_argument(
        "--models-dir",
        type=Path,
        default=REPO_ROOT / "packages" / "lip_sync_engines" / "musetalk" / "models",
    )
    parser.add_argument("--hf-endpoint", default=os.getenv("HF_ENDPOINT", ""))
    args = parser.parse_args()

    if args.hf_endpoint:
        os.environ["HF_ENDPOINT"] = args.hf_endpoint

    models_dir = args.models_dir.resolve()
    models_dir.mkdir(parents=True, exist_ok=True)

    download_repo(
        "TMElyralab/MuseTalk",
        models_dir,
        ["musetalkV15/musetalk.json", "musetalkV15/unet.pth"],
    )
    download_repo(
        "stabilityai/sd-vae-ft-mse",
        models_dir / "sd-vae",
        ["config.json", "diffusion_pytorch_model.bin"],
    )
    download_repo(
        "openai/whisper-tiny",
        models_dir / "whisper",
        ["config.json", "pytorch_model.bin", "preprocessor_config.json"],
    )
    download_repo(
        "ManyOtherFunctions/face-parse-bisent",
        models_dir / "face-parse-bisent",
        ["79999_iter.pth", "resnet18-5c106cde.pth"],
    )
    download_repo(
        "yzd-v/DWPose",
        models_dir / "dwpose",
        ["dw-ll_ucoco_384.pth"],
    )

    required_files = [
        models_dir / "musetalkV15" / "musetalk.json",
        models_dir / "musetalkV15" / "unet.pth",
        models_dir / "sd-vae" / "config.json",
        models_dir / "sd-vae" / "diffusion_pytorch_model.bin",
        models_dir / "whisper" / "config.json",
        models_dir / "whisper" / "pytorch_model.bin",
        models_dir / "whisper" / "preprocessor_config.json",
        models_dir / "face-parse-bisent" / "79999_iter.pth",
        models_dir / "face-parse-bisent" / "resnet18-5c106cde.pth",
    ]
    missing = [str(path) for path in required_files if not path.exists()]
    if missing:
        raise SystemExit("Missing files after download:\n" + "\n".join(missing))

    print(f"MuseTalk weights ready: {models_dir}")


if __name__ == "__main__":
    main()
