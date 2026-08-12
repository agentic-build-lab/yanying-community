import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WAV2LIP_ROOT = REPO_ROOT / "packages" / "wav2lip_upstream"
DEFAULT_WAV2LIP_LSE_DIR = REPO_ROOT / "packages" / "wav2lip_upstream" / "evaluation" / "scores_LSE"
DEFAULT_SANDBOX_PYTHON = (
    REPO_ROOT / "work" / "engine_sandboxes" / "syncnet" / "venv" / "Scripts" / "python.exe"
)
DEFAULT_LEGACY_PROJECT_PYTHON = (
    REPO_ROOT / "packages" / "legacy_runtime" / "tts-1" / "wzf" / "python.exe"
)
DEFAULT_SANDBOX_PACKAGE_DIR = (
    REPO_ROOT / "work" / "engine_sandboxes" / "syncnet" / "python_packages"
)
DEFAULT_SHARED_PACKAGE_DIRS = (
    REPO_ROOT / "work" / "lip_sync_python_packages",
    REPO_ROOT / "work" / "musetalk_python_packages",
)
DEFAULT_SYNCNET_MODEL_CODE_DIR = (
    REPO_ROOT / "packages" / "experimental_engines" / "syncnet" / "source"
)
DEFAULT_SYNCNET_MODEL = REPO_ROOT / "models" / "lip_sync" / "syncnet_v2.model"


def unavailable(reason: str, **extra: object) -> dict[str, object]:
    return {
        "verdict": "unavailable",
        "reason": reason,
        "quality_bar": {
            "syncnet_lse": "unavailable",
            "perfect_sync_claim": False,
        },
        **extra,
    }


def run_command(
    command: list[str], *, cwd: Path, env: dict[str, str], timeout: int
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout
    )


def parse_scores(output: str) -> dict[str, float | None]:
    confidence_match = re.search(r"Average Confidence:\s*([-+]?\d+(?:\.\d+)?)", output)
    distance_match = re.search(r"Average Minimum Distance:\s*([-+]?\d+(?:\.\d+)?)", output)
    confidence = float(confidence_match.group(1)) if confidence_match else None
    distance = float(distance_match.group(1)) if distance_match else None
    return {
        "lse_c_confidence": confidence,
        "lse_d_min_distance": distance,
    }


def load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def choose_python(requested_python: Path) -> Path:
    if requested_python.exists():
        return requested_python
    if DEFAULT_LEGACY_PROJECT_PYTHON.exists():
        return DEFAULT_LEGACY_PROJECT_PYTHON
    return Path(sys.executable)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run optional SyncNet LSE-C/LSE-D style quality scoring."
    )
    parser.add_argument("--final-video", required=True, type=Path)
    parser.add_argument("--work-dir", type=Path, default=REPO_ROOT / "work" / "syncnet_lse_quality")
    parser.add_argument("--syncnet-dir", type=Path, default=DEFAULT_WAV2LIP_LSE_DIR)
    parser.add_argument(
        "--syncnet-model-code-dir", type=Path, default=DEFAULT_SYNCNET_MODEL_CODE_DIR
    )
    parser.add_argument("--syncnet-model", type=Path, default=DEFAULT_SYNCNET_MODEL)
    parser.add_argument("--python", type=Path, default=DEFAULT_SANDBOX_PYTHON)
    parser.add_argument("--sandbox-package-dir", type=Path, default=DEFAULT_SANDBOX_PACKAGE_DIR)
    parser.add_argument(
        "--shared-package-dir",
        action="append",
        type=Path,
        default=list(DEFAULT_SHARED_PACKAGE_DIRS),
    )
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--vshift", type=int, default=15)
    parser.add_argument("--crop-mode", choices=["none", "face"], default="none")
    parser.add_argument("--face-crop-detector", choices=["haar", "s3fd"], default="haar")
    parser.add_argument("--face-crop-context-scale", type=float, default=1.45)
    parser.add_argument("--face-crop-target-size", type=int, default=224)
    parser.add_argument("--timeout-sec", type=int, default=900)
    parser.add_argument("--report-json", type=Path, default=None)
    args = parser.parse_args()

    args.final_video = args.final_video.resolve()
    args.work_dir = args.work_dir.resolve()
    args.syncnet_dir = args.syncnet_dir.resolve()
    args.syncnet_model_code_dir = args.syncnet_model_code_dir.resolve()
    args.syncnet_model = args.syncnet_model.resolve()
    args.sandbox_package_dir = args.sandbox_package_dir.resolve()
    args.shared_package_dir = [path.resolve() for path in args.shared_package_dir]
    if args.report_json:
        args.report_json = args.report_json.resolve()

    if not args.final_video.exists():
        result = unavailable("missing_final_video", final_video=str(args.final_video))
        print_result(result, args.report_json)
        return

    score_script = args.syncnet_dir / "calculate_scores_LRS.py"
    instance_script = args.syncnet_dir / "SyncNetInstance_calc_scores.py"
    model_script = args.syncnet_model_code_dir / "SyncNetModel.py"
    crop_script = REPO_ROOT / "scripts" / "crop_video_to_face_track.py"
    missing_files = [
        str(path)
        for path in (score_script, instance_script, model_script, args.syncnet_model)
        if not path.exists()
    ]
    if args.crop_mode == "face" and not crop_script.exists():
        missing_files.append(str(crop_script))
    if missing_files:
        result = unavailable(
            "missing_syncnet_runtime_files",
            missing_files=missing_files,
            expected_model_path=str(args.syncnet_model),
            syncnet_dir=str(args.syncnet_dir),
            note=(
                "The current repository has Wav2Lip LSE scoring scripts, but the SyncNet model code/weights "
                "must be supplied inside the isolated syncnet sandbox before strict LSE scoring can run."
            ),
        )
        print_result(result, args.report_json)
        return

    env = os.environ.copy()
    python_path_parts = []
    if args.sandbox_package_dir.exists():
        python_path_parts.append(str(args.sandbox_package_dir))
    python_path_parts.extend(str(path) for path in args.shared_package_dir if path.exists())
    python_path_parts.extend(
        [str(args.syncnet_model_code_dir), str(args.syncnet_dir), str(DEFAULT_WAV2LIP_ROOT)]
    )
    if env.get("PYTHONPATH"):
        python_path_parts.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(python_path_parts)

    python_path = choose_python(args.python)
    args.work_dir.mkdir(parents=True, exist_ok=True)
    data_root = args.work_dir / "videos"
    tmp_dir = args.work_dir / "tmp"
    data_root.mkdir(parents=True, exist_ok=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    evaluation_video = data_root / "final_video.mp4"
    crop_report = None
    if args.crop_mode == "face":
        cropped_video = args.work_dir / "face_crop" / "final_video_face_track.mp4"
        crop_report_path = args.work_dir / "face_crop" / "face_crop_report.json"
        crop_completed = run_command(
            [
                str(python_path),
                str(crop_script),
                "--input-video",
                str(args.final_video),
                "--output-video",
                str(cropped_video),
                "--work-dir",
                str(args.work_dir / "face_crop_work"),
                "--report-json",
                str(crop_report_path),
                "--target-size",
                str(args.face_crop_target_size),
                "--context-scale",
                str(args.face_crop_context_scale),
                "--detector",
                args.face_crop_detector,
                "--timeout-sec",
                str(args.timeout_sec),
            ],
            cwd=REPO_ROOT,
            env=env,
            timeout=args.timeout_sec,
        )
        if crop_completed.returncode != 0 or not cropped_video.exists():
            result = unavailable(
                "face_crop_failed",
                command=crop_completed.args,
                stdout=crop_completed.stdout[-4000:],
                stderr=crop_completed.stderr[-4000:],
            )
            print_result(result, args.report_json)
            return
        shutil.copy2(cropped_video, evaluation_video)
        crop_report = load_json(crop_report_path) if crop_report_path.exists() else None
    else:
        shutil.copy2(args.final_video, evaluation_video)

    command = [
        str(python_path),
        str(score_script),
        "--initial_model",
        str(args.syncnet_model),
        "--batch_size",
        str(args.batch_size),
        "--vshift",
        str(args.vshift),
        "--data_root",
        str(data_root),
        "--tmp_dir",
        str(tmp_dir),
        "--reference",
        "final_video",
    ]
    completed = run_command(command, cwd=args.syncnet_dir, env=env, timeout=args.timeout_sec)
    if completed.returncode != 0:
        result = unavailable(
            "syncnet_execution_failed",
            command=command,
            stdout=completed.stdout[-4000:],
            stderr=completed.stderr[-4000:],
        )
        print_result(result, args.report_json)
        return

    scores = parse_scores(completed.stdout + "\n" + completed.stderr)
    result = {
        "verdict": "pass" if scores["lse_c_confidence"] is not None else "needs_review",
        "final_video": str(args.final_video),
        "syncnet_dir": str(args.syncnet_dir),
        "syncnet_model_code_dir": str(args.syncnet_model_code_dir),
        "syncnet_model": str(args.syncnet_model),
        "python": str(python_path),
        "crop_mode": args.crop_mode,
        "face_crop": crop_report,
        "scores": scores,
        "raw_output": (completed.stdout + "\n" + completed.stderr)[-4000:],
        "quality_bar": {
            "syncnet_lse": "pass" if scores["lse_c_confidence"] is not None else "needs_review",
            "perfect_sync_claim": False,
        },
    }
    print_result(result, args.report_json)


def print_result(result: dict[str, object], report_json: Path | None) -> None:
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if report_json:
        report_json.parent.mkdir(parents=True, exist_ok=True)
        report_json.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
