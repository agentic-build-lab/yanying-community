import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from threading import RLock
from uuid import uuid4

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    qa_required = "qa_required"
    approved = "approved"
    exported = "exported"
    failed = "failed"


class RenderJobCreate(BaseModel):
    project_id: str = Field(default="demo_project")
    output_category: str = Field(default="talking_videos")
    script: str
    voice_id: str = Field(default="clear_male_zh")
    voice_source: str = Field(default="native_tts")
    legacy_prompt_audio: str | None = Field(default=None)
    avatar_id: str = Field(default="business_presenter")
    avatar_name: str = Field(default="")
    avatar_source: str = Field(default="legacy_video_avatar")
    image_prompt: str | None = Field(default=None)
    image_path: str | None = Field(default=None)
    target_format: str = Field(default="1080x1920")
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    burn_subtitles: bool = Field(default=True)
    make_cover: bool = Field(default=True)
    cover_title_line_1: str = Field(default="", max_length=30)
    cover_title_line_2: str = Field(default="", max_length=30)
    cover_style: str = Field(default="studio")
    cover_accent_color: str = Field(default="#f2c94c", max_length=16)
    subtitle_template: str = Field(default="clean")
    background_music_id: str | None = Field(default=None)
    video_quality: str = Field(default="high")
    dry_run: bool = Field(default=False)


class RenderJobRecord(BaseModel):
    job_id: str
    project_id: str
    title: str
    description: str
    status: JobStatus
    progress: int = Field(ge=0, le=100)
    created_at: str
    started_at: str | None = None
    updated_at: str | None = None
    completed_at: str | None = None
    current_stage: str | None = None
    avatar_id: str = ""
    avatar_name: str = ""
    avatar_source: str = ""
    dry_run: bool
    stages: list[dict[str, object]] = Field(default_factory=list)
    export_path: str | None = None
    cover_path: str | None = None


class JobStore:
    def __init__(self, storage_path: Path | None = None) -> None:
        self._storage_path = storage_path
        self._lock = RLock()
        self._jobs = self._load_jobs()
        self._recover_interrupted_jobs()

    def list_jobs(self) -> list[RenderJobRecord]:
        with self._lock:
            return [job.model_copy(deep=True) for job in self._jobs]

    def get_job(self, job_id: str) -> RenderJobRecord | None:
        with self._lock:
            job = next((item for item in self._jobs if item.job_id == job_id), None)
            return job.model_copy(deep=True) if job is not None else None

    def delete_sample_jobs(self) -> int:
        with self._lock:
            retained = [
                job
                for job in self._jobs
                if not self.is_sample_job(job)
                or job.status in {JobStatus.queued, JobStatus.running}
            ]
            deleted_count = len(self._jobs) - len(retained)
            if deleted_count:
                self._jobs = retained
                self._persist()
            return deleted_count

    def delete_jobs(self, scope: str) -> int:
        if scope not in {"real", "samples", "all"}:
            raise ValueError("Unsupported job scope.")
        with self._lock:
            retained: list[RenderJobRecord] = []
            for job in self._jobs:
                active = job.status in {JobStatus.queued, JobStatus.running}
                selected = (
                    scope == "all"
                    or (scope == "samples" and self.is_sample_job(job))
                    or (scope == "real" and not self.is_sample_job(job))
                )
                if active or not selected:
                    retained.append(job)
            deleted_count = len(self._jobs) - len(retained)
            if deleted_count:
                self._jobs = retained
                self._persist()
            return deleted_count

    def delete_job(self, job_id: str) -> bool:
        with self._lock:
            job = next((item for item in self._jobs if item.job_id == job_id), None)
            if job is None:
                return False
            if job.status in {JobStatus.queued, JobStatus.running}:
                raise RuntimeError("Active jobs cannot be deleted.")
            self._jobs.remove(job)
            self._persist()
            return True

    @staticmethod
    def is_sample_job(job: RenderJobRecord) -> bool:
        return job.dry_run or job.project_id == "demo_project" or job.job_id.startswith("demo_")

    def create_queued_job(self, payload: RenderJobCreate) -> RenderJobRecord:
        now = datetime.now(timezone.utc).isoformat()
        script_title = " ".join(payload.script.split())
        if len(script_title) > 26:
            script_title = f"{script_title[:26]}..."
        job = RenderJobRecord(
            job_id=f"job_{uuid4().hex[:12]}",
            project_id=payload.project_id,
            title=script_title or "数字人口播生成",
            description="任务已进入生成队列。",
            status=JobStatus.queued,
            progress=0,
            created_at=now,
            updated_at=now,
            avatar_id=payload.avatar_id,
            avatar_name=payload.avatar_name,
            avatar_source=payload.avatar_source,
            dry_run=payload.dry_run,
            stages=[
                {"stage": "tts", "status": "queued", "progress": 0, "message": "等待生成语音"},
                {"stage": "avatar", "status": "queued", "progress": 0, "message": "等待口型匹配"},
                {"stage": "render", "status": "queued", "progress": 0, "message": "等待字幕与合成"},
            ],
        )
        with self._lock:
            self._jobs.insert(0, job)
            self._persist()
        return job

    def update_stage(
        self,
        job_id: str,
        *,
        stage: str,
        stage_status: str,
        progress: int,
        message: str,
        result: dict[str, object] | None = None,
    ) -> RenderJobRecord | None:
        with self._lock:
            job = next((item for item in self._jobs if item.job_id == job_id), None)
            if job is None:
                return None
            now = datetime.now(timezone.utc).isoformat()
            if job.started_at is None:
                job.started_at = now
            job.status = JobStatus.running
            job.progress = max(job.progress, min(99, max(0, int(progress))))
            job.updated_at = now
            job.current_stage = stage
            job.description = message
            stage_record = next((item for item in job.stages if item.get("stage") == stage), None)
            if stage_record is None:
                stage_record = {"stage": stage}
                job.stages.append(stage_record)
            stage_record.update(
                {
                    "status": stage_status,
                    "progress": job.progress,
                    "message": message,
                    "updated_at": now,
                }
            )
            if stage_status == "running" and not stage_record.get("started_at"):
                stage_record["started_at"] = now
            if stage_status in {"completed", "failed", "skipped"}:
                stage_record["completed_at"] = now
            if result is not None:
                stage_record["result"] = result
            self._persist()
            return job.model_copy(deep=True)

    def finalize_job(self, job_id: str, stages: list[dict[str, object]]) -> RenderJobRecord | None:
        with self._lock:
            job = next((item for item in self._jobs if item.job_id == job_id), None)
            if job is None:
                return None
            now = datetime.now(timezone.utc).isoformat()
            failed_stages = [stage for stage in stages if stage.get("status") == "failed"]
            completed_stages = [stage for stage in stages if stage.get("status") == "completed"]
            render_result = next(
                (stage.get("result") for stage in stages if stage.get("stage") == "render"), None
            )
            job.status = (
                JobStatus.failed
                if failed_stages
                else JobStatus.qa_required
                if len(completed_stages) == 3
                else JobStatus.failed
            )
            job.progress = 100 if job.status == JobStatus.qa_required else max(job.progress, 1)
            job.updated_at = now
            job.completed_at = now
            job.current_stage = None
            for incoming_stage in stages:
                stage_name = incoming_stage.get("stage")
                stage_record = next(
                    (item for item in job.stages if item.get("stage") == stage_name), None
                )
                if stage_record is None:
                    stage_record = {"stage": stage_name}
                    job.stages.append(stage_record)
                stage_record.update(incoming_stage)
                stage_record["completed_at"] = stage_record.get("completed_at") or now
                stage_record["updated_at"] = now
            job.export_path = (
                render_result.get("export_path") if isinstance(render_result, dict) else None
            )
            job.cover_path = (
                render_result.get("cover_path") if isinstance(render_result, dict) else None
            )
            if job.status == JobStatus.qa_required:
                job.description = "视频已经生成，等待人工审片。"
            else:
                failed_message = next(
                    (
                        str(stage.get("result", {}).get("message"))
                        for stage in failed_stages
                        if isinstance(stage.get("result"), dict)
                        and stage.get("result", {}).get("message")
                    ),
                    "生成失败，请检查阶段详情。",
                )
                job.description = failed_message
            self._persist()
            return job.model_copy(deep=True)

    def fail_job(self, job_id: str, message: str) -> RenderJobRecord | None:
        with self._lock:
            job = next((item for item in self._jobs if item.job_id == job_id), None)
            if job is None:
                return None
            now = datetime.now(timezone.utc).isoformat()
            job.status = JobStatus.failed
            job.description = message
            job.updated_at = now
            job.completed_at = now
            job.current_stage = None
            for stage in job.stages:
                stage_status = stage.get("status")
                if stage_status == "running":
                    stage["status"] = "failed"
                    stage["message"] = message
                    stage["completed_at"] = now
                elif stage_status == "queued":
                    stage["status"] = "skipped"
                    stage["message"] = "任务提前终止，未执行此阶段"
                    stage["completed_at"] = now
                stage["updated_at"] = now
            self._persist()
            return job.model_copy(deep=True)

    def _load_jobs(self) -> list[RenderJobRecord]:
        if self._storage_path is None or not self._storage_path.is_file():
            return []
        try:
            payload = json.loads(self._storage_path.read_text(encoding="utf-8"))
            if not isinstance(payload, list):
                raise ValueError("Job record storage must contain a JSON list.")
            return [RenderJobRecord.model_validate(item) for item in payload]
        except (OSError, json.JSONDecodeError, ValueError):
            self._preserve_invalid_storage()
            return []

    def _persist(self) -> None:
        if self._storage_path is None:
            return
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self._storage_path.with_suffix(f"{self._storage_path.suffix}.tmp")
        temporary_path.write_text(
            json.dumps(
                [job.model_dump(mode="json") for job in self._jobs], ensure_ascii=False, indent=2
            ),
            encoding="utf-8",
        )
        temporary_path.replace(self._storage_path)

    def _recover_interrupted_jobs(self) -> None:
        interrupted = [
            job for job in self._jobs if job.status in {JobStatus.queued, JobStatus.running}
        ]
        if not interrupted:
            return
        now = datetime.now(timezone.utc).isoformat()
        for job in interrupted:
            job.status = JobStatus.failed
            job.description = "服务曾在任务运行期间重启，请重新提交该任务。"
            job.updated_at = now
            job.completed_at = now
            job.current_stage = None
            for stage in job.stages:
                stage_status = stage.get("status")
                if stage_status == "running":
                    stage["status"] = "failed"
                    stage["message"] = "服务重启，当前阶段已中断"
                    stage["completed_at"] = now
                elif stage_status == "queued":
                    stage["status"] = "skipped"
                    stage["message"] = "服务重启，未执行此阶段"
                    stage["completed_at"] = now
                stage["updated_at"] = now
        self._persist()

    def _preserve_invalid_storage(self) -> None:
        if self._storage_path is None or not self._storage_path.exists():
            return
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = self._storage_path.with_name(
            f"{self._storage_path.stem}.corrupt_{timestamp}.json"
        )
        try:
            self._storage_path.replace(backup_path)
        except OSError:
            pass

    @staticmethod
    def _demo_job() -> RenderJobRecord:
        return RenderJobRecord(
            job_id="demo_job_001",
            project_id="demo_project",
            title="产品卖点讲解",
            description="样例任务，等待一键生成真实视频。",
            status=JobStatus.qa_required,
            progress=76,
            created_at=datetime.now(timezone.utc).isoformat(),
            dry_run=True,
        )
