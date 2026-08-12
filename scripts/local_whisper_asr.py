from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from pathlib import Path


def configure_runtime(project_root: Path) -> None:
    site_packages = project_root / "work" / "runtime" / "python311_site_packages"
    internal = project_root / "_internal" / "app3_server" / "_internal"
    dll_dirs = [
        site_packages / "numpy" / ".libs",
        site_packages / "llvmlite" / "binding",
        internal,
        internal / "torch" / "lib",
    ]
    for dll_dir in dll_dirs:
        if dll_dir.exists():
            os.add_dll_directory(str(dll_dir))

    path_parts = [
        site_packages / "numpy" / ".libs",
        site_packages / "llvmlite" / "binding",
        internal / "torch" / "lib",
        internal / "static" / "ffmpeg" / "bin",
        internal,
    ]
    os.environ["PATH"] = (
        os.pathsep.join(str(p) for p in path_parts if p.exists())
        + os.pathsep
        + os.environ.get("PATH", "")
    )

    sys.path[:0] = [
        str(site_packages),
        str(internal),
        str(internal / "base_library.zip"),
    ]

    # The bundled app contains an incomplete scipy namespace. Whisper does not need it.
    sys.modules["scipy"] = None


def resolve_device(requested: str) -> str:
    import torch

    requested = (requested or "auto").strip().lower()
    if requested == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    if requested == "cuda" and not torch.cuda.is_available():
        return "cpu"
    if requested in {"cuda", "cpu"}:
        return requested
    return "cuda" if torch.cuda.is_available() else "cpu"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--language", default="")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    configure_runtime(project_root)

    try:
        import whisper

        media_path = Path(args.input)
        model_path = Path(args.model)
        if not media_path.exists():
            raise FileNotFoundError(f"input file not found: {media_path}")
        if not model_path.exists():
            raise FileNotFoundError(f"model file not found: {model_path}")

        device = resolve_device(args.device)
        model = whisper.load_model(str(model_path), device=device)
        result = model.transcribe(
            str(media_path),
            language=(args.language or None),
            task="transcribe",
            fp16=device == "cuda",
            verbose=False,
        )
        print(
            json.dumps(
                {
                    "text": str(result.get("text") or "").strip(),
                    "language": result.get("language"),
                    "device": device,
                    "segments": len(result.get("segments") or []),
                },
                ensure_ascii=False,
            )
        )
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
