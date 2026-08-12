import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

AssetLicenseStatus = Literal["commercial_ok", "prototype_only", "test_only", "unknown"]
REPO_ROOT = Path(__file__).resolve().parents[3]
TEMPLATE_MANIFEST_PATH = (
    REPO_ROOT
    / "outputs"
    / "generated_media"
    / "template_videos"
    / "local_presenter_v1"
    / "template_manifest.json"
)


class DigitalHumanAsset(BaseModel):
    asset_id: str
    display_name: str
    asset_type: str
    license_status: AssetLicenseStatus
    usage: str
    notes: str = Field(default="")
    engine_name: str = Field(default="")
    pose: str = Field(default="")
    duration_seconds: float | None = Field(default=None)
    preview_url: str = Field(default="")
    cover_url: str = Field(default="")
    semantic_role: str = Field(default="")
    semantic_tags: list[str] = Field(default_factory=list)
    recommendation_keywords: list[str] = Field(default_factory=list)
    action_sequence: list[str] = Field(default_factory=list)
    speed_tier: str = Field(default="base")
    transition_group: str = Field(default="")
    max_continuous_speech_seconds: float | None = Field(default=None)
    loop_allowed: bool = Field(default=True)
    requires_broll_for_longer_script: bool = Field(default=False)
    motion_safety_note: str = Field(default="")


def _curated_template_assets() -> list[DigitalHumanAsset]:
    if not TEMPLATE_MANIFEST_PATH.exists():
        return []
    payload = json.loads(TEMPLATE_MANIFEST_PATH.read_text(encoding="utf-8"))
    return [DigitalHumanAsset.model_validate(item) for item in payload.get("templates", [])]


def default_assets() -> list[DigitalHumanAsset]:
    return [
        DigitalHumanAsset(
            asset_id="business_presenter",
            display_name="AI 口播主持人",
            asset_type="generated_presenter_image",
            license_status="prototype_only",
            usage="产品讲解、课程口播、知识科普",
            notes="新版工作台默认主视觉，不含旧版测试水印。",
        ),
        *_curated_template_assets(),
    ]
