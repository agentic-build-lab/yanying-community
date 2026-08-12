from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


class AvatarJobStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class AvatarJobCreate(BaseModel):
    project_id: str = Field(default="demo_project")
    script: str = Field(min_length=1)
    avatar_id: str = Field(default="business_presenter")
    avatar_source: str = Field(default="legacy_video_avatar")
    audio_path: str | None = Field(default=None)
    image_prompt: str | None = Field(default=None)
    image_path: str | None = Field(default=None)
    dry_run: bool = Field(default=True)


class AvatarJobRecord(BaseModel):
    job_id: str
    project_id: str
    avatar_id: str
    avatar_source: str
    status: AvatarJobStatus
    progress: int = Field(ge=0, le=100)
    dry_run: bool
    video_path: str | None = None
    image_path: str | None = None
    audio_path: str | None = None
    message: str
    created_at: str


class AvatarJobStore:
    def __init__(self) -> None:
        self._jobs: list[AvatarJobRecord] = []

    def list_jobs(self) -> list[AvatarJobRecord]:
        return list(self._jobs)

    def add(
        self,
        payload: AvatarJobCreate,
        *,
        status: AvatarJobStatus,
        progress: int,
        message: str,
        job_id: str | None = None,
        image_path: str | None = None,
        video_path: str | None = None,
        audio_path: str | None = None,
    ) -> AvatarJobRecord:
        record = AvatarJobRecord(
            job_id=job_id or f"avatar_{uuid4().hex[:12]}",
            project_id=payload.project_id,
            avatar_id=payload.avatar_id,
            avatar_source=payload.avatar_source,
            status=status,
            progress=progress,
            dry_run=payload.dry_run,
            video_path=video_path,
            image_path=image_path or payload.image_path,
            audio_path=audio_path or payload.audio_path,
            message=message,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self._jobs.insert(0, record)
        return record
