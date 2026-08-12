from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

SAFE_SEGMENT_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")
MAX_SEGMENT_LENGTH = 80


def safe_path_segment(value: str | None, fallback: str) -> str:
    normalized = (value or "").strip().replace("\\", "/")
    normalized = normalized.split("/")[-1]
    normalized = SAFE_SEGMENT_PATTERN.sub("_", normalized)
    normalized = normalized.strip("._-")

    if not normalized or normalized in {".", ".."}:
        normalized = fallback

    return normalized[:MAX_SEGMENT_LENGTH]


def make_video_job_dir(
    *,
    output_root: Path,
    output_category: str | None,
    project_id: str | None,
    job_id: str,
    created_at: datetime | None = None,
) -> Path:
    created_at = created_at or datetime.now()
    day_segment = created_at.strftime("%Y%m%d")
    category_segment = safe_path_segment(output_category, "talking_videos")
    project_segment = safe_path_segment(project_id, "default_project")
    job_segment = safe_path_segment(job_id, "render_job")

    return output_root / "videos" / category_segment / project_segment / day_segment / job_segment
