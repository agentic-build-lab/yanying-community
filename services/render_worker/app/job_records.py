from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


class RenderJobStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class RenderJobCreate(BaseModel):
    project_id: str = Field(default="demo_project")
    output_category: str = Field(default="talking_videos")
    video_path: str | None = Field(default=None)
    image_path: str | None = Field(default=None)
    audio_path: str | None = Field(default=None)
    subtitle_text: str | None = Field(default=None)
    subtitle_segments: list[dict[str, object]] = Field(default_factory=list)
    subtitle_template: str = Field(default="clean")
    target_format: str = Field(default="1080x1920")
    burn_subtitles: bool = Field(default=True)
    make_cover: bool = Field(default=True)
    dry_run: bool = Field(default=True)


class RenderJobRecord(BaseModel):
    job_id: str
    project_id: str
    output_category: str
    status: RenderJobStatus
    progress: int = Field(ge=0, le=100)
    target_format: str
    dry_run: bool
    export_path: str | None = None
    cover_path: str | None = None
    message: str
    created_at: str


class RenderJobStore:
    def __init__(self) -> None:
        self._jobs: list[RenderJobRecord] = []

    def list_jobs(self) -> list[RenderJobRecord]:
        return list(self._jobs)

    def add(
        self,
        payload: RenderJobCreate,
        *,
        status: RenderJobStatus,
        progress: int,
        message: str,
        job_id: str | None = None,
        export_path: str | None = None,
        cover_path: str | None = None,
    ) -> RenderJobRecord:
        record = RenderJobRecord(
            job_id=job_id or f"render_{uuid4().hex[:12]}",
            project_id=payload.project_id,
            output_category=payload.output_category,
            status=status,
            progress=progress,
            target_format=payload.target_format,
            dry_run=payload.dry_run,
            export_path=export_path,
            cover_path=cover_path,
            message=message,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self._jobs.insert(0, record)
        return record
