from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {
    ".css",
    ".html",
    ".js",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".svg",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
IGNORED_PARTS = {".git", ".runtime", ".venv", "__pycache__"}

BANNED_TEXT = {
    "C:" + "\\Users\\Admin" + "istrator": "local Windows profile",
    "D:" + "\\metahuman_next" + "_project": "private project path",
    "yi" + "sihai": "private account identifier",
    "cod" + "ex_": "temporary automation identifier",
    "kr" + "longai": "private executable identifier",
}

SECRET_PATTERNS = {
    "OpenAI-style API key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}


def tracked_candidates() -> list[Path]:
    return [
        path
        for path in ROOT.rglob("*")
        if path.is_file()
        and not any(part in IGNORED_PARTS for part in path.parts)
        and path.suffix.lower() in TEXT_SUFFIXES
    ]


def validate_public_surface() -> list[str]:
    errors: list[str] = []
    required = [
        ROOT / "README.md",
        ROOT / "README.zh-CN.md",
        ROOT / "LICENSE",
        ROOT / "SECURITY.md",
        ROOT / "apps" / "studio_web" / "index.html",
        ROOT / "services" / "api_gateway" / "app" / "main.py",
    ]
    for path in required:
        if not path.is_file():
            errors.append(f"missing required file: {path.relative_to(ROOT)}")

    for path in tracked_candidates():
        content = path.read_text(encoding="utf-8", errors="replace")
        relative = path.relative_to(ROOT)
        for needle, description in BANNED_TEXT.items():
            if needle.lower() in content.lower():
                errors.append(f"{relative}: contains {description}")
        for description, pattern in SECRET_PATTERNS.items():
            if pattern.search(content):
                errors.append(f"{relative}: contains possible {description}")

    oversized = [
        path.relative_to(ROOT)
        for path in ROOT.rglob("*")
        if path.is_file()
        and not any(part in IGNORED_PARTS for part in path.parts)
        and path.stat().st_size > 10 * 1024 * 1024
    ]
    errors.extend(f"unexpected file over 10 MiB: {path}" for path in oversized)
    return errors


if __name__ == "__main__":
    failures = validate_public_surface()
    if failures:
        print("Public surface validation failed:")
        for failure in failures:
            print(f"- {failure}")
        sys.exit(1)
    print("Public surface validation passed.")


def test_repository_has_no_private_surface() -> None:
    assert validate_public_surface() == []
