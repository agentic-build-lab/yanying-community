from pydantic import BaseModel, Field


class ProjectRecord(BaseModel):
    project_id: str = Field(default="demo_project")
    title: str = Field(default="新一代数字人口播生成")
    script: str
    content_type: str = Field(default="产品讲解")
    target_format: str = Field(default="1080x1920")
    voice_id: str = Field(default="clear_male_zh")
    avatar_id: str = Field(default="business_presenter")
    review_required: bool = Field(default=True)


def demo_project() -> ProjectRecord:
    return ProjectRecord(
        script=(
            "今天我们用一个真实场景讲清楚：如何把一条产品内容，从脚本、声音、数字人、字幕到封面和成片导出，"
            "一次性稳定完成。重点不是堆功能，而是让每一步都可控、可复查、可复用。"
        )
    )
