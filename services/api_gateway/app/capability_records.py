CAPABILITY_DEFINITIONS = [
    ("copywriting", "文案仿写", "legacy", "内容生产"),
    ("douyin_extraction", "抖音文案提取", "legacy", "内容生产"),
    ("title_topics", "标题与话题", "legacy", "内容生产"),
    ("speech_recognition", "语音转文字", "legacy", "内容生产"),
    ("tts", "语音生成", "native", "声音"),
    ("voice_assets", "音色管理与克隆", "legacy", "声音"),
    ("digital_human_video", "数字人口型视频", "native", "数字人"),
    ("legacy_digital_human", "旧版数字人模板与服务控制", "legacy", "数字人"),
    ("subtitle_generation", "字幕生成与样式", "legacy", "后期"),
    ("background_music", "背景音乐", "legacy", "后期"),
    ("video_editing", "模板剪辑", "legacy", "后期"),
    ("cover_generation", "封面生成", "legacy", "后期"),
    ("multi_format_export", "多尺寸导出", "native", "后期"),
    ("platform_publish", "平台发布", "legacy_review_gate", "发布"),
]


def build_capabilities(*, native_ready: bool, legacy_ready: bool) -> dict[str, object]:
    items = []
    for capability_id, label, source, group in CAPABILITY_DEFINITIONS:
        if source == "native":
            status = "available" if native_ready else "unavailable"
        elif source == "legacy_review_gate":
            status = "review_required" if legacy_ready else "configured"
        else:
            status = "available" if legacy_ready else "configured"
        items.append(
            {
                "id": capability_id,
                "label": label,
                "source": source,
                "group": group,
                "status": status,
            }
        )
    return {
        "items": items,
        "summary": {
            "native_ready": native_ready,
            "legacy_engine_ready": legacy_ready,
            "old_frontend_required": False,
            "publish_review_required": True,
        },
    }
