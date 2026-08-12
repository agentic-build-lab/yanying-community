from dataclasses import dataclass


@dataclass(frozen=True)
class LegacyRoute:
    methods: frozenset[str]
    capability: str
    review_required: bool = False


LEGACY_ROUTES: dict[str, LegacyRoute] = {
    "/version/": LegacyRoute(frozenset({"GET"}), "engine_status"),
    "/algorithm/status/": LegacyRoute(frozenset({"GET"}), "engine_status"),
    "/algorithm/tts/info/": LegacyRoute(frozenset({"GET"}), "voice_engine"),
    "/algorithm/start/": LegacyRoute(frozenset({"POST"}), "engine_control"),
    "/algorithm/stop/": LegacyRoute(frozenset({"POST"}), "engine_control"),
    "/assets/": LegacyRoute(frozenset({"GET", "POST", "PUT", "DELETE"}), "media_assets"),
    "/audio/generate/": LegacyRoute(frozenset({"POST"}), "audio_generation"),
    "/audio/progress/": LegacyRoute(frozenset({"GET"}), "audio_generation"),
    "/audio/cancel/": LegacyRoute(frozenset({"POST"}), "audio_generation"),
    "/audio/ref_audio/": LegacyRoute(frozenset({"GET", "POST", "DELETE"}), "voice_clone"),
    "/audio/ref_audio/rename/": LegacyRoute(frozenset({"POST"}), "voice_clone"),
    "/background_music/": LegacyRoute(frozenset({"GET"}), "background_music"),
    "/config/": LegacyRoute(frozenset({"GET", "POST"}), "legacy_settings"),
    "/config/prompt/": LegacyRoute(frozenset({"GET", "POST"}), "prompt_settings"),
    "/cover/": LegacyRoute(frozenset({"GET", "POST"}), "cover_generation"),
    "/cover/v2/": LegacyRoute(frozenset({"POST"}), "cover_generation"),
    "/files/upload/": LegacyRoute(frozenset({"POST"}), "file_upload"),
    "/meta_human/": LegacyRoute(frozenset({"GET", "POST", "DELETE"}), "digital_human_assets"),
    "/meta_human/rename/": LegacyRoute(frozenset({"POST"}), "digital_human_assets"),
    "/srt/": LegacyRoute(frozenset({"POST"}), "subtitle_generation"),
    "/text/asr/": LegacyRoute(frozenset({"POST"}), "speech_recognition"),
    "/text/bailian_app/": LegacyRoute(frozenset({"POST"}), "copywriting"),
    "/text/douyin/": LegacyRoute(frozenset({"POST"}), "douyin_extraction"),
    "/text/rewrite/": LegacyRoute(frozenset({"POST"}), "copywriting"),
    "/title/": LegacyRoute(frozenset({"POST"}), "title_topics"),
    "/title/v2/": LegacyRoute(frozenset({"POST"}), "title_topics"),
    "/video/clip_template/": LegacyRoute(frozenset({"GET"}), "editing_templates"),
    "/video/clip_v3/": LegacyRoute(frozenset({"POST"}), "video_editing"),
    "/video/clip_v3/progress/": LegacyRoute(frozenset({"GET"}), "video_editing"),
    "/video/clip_v3/cancel/": LegacyRoute(frozenset({"POST"}), "video_editing"),
    "/video/fonts/": LegacyRoute(frozenset({"GET"}), "subtitle_fonts"),
    "/video/meta_human_video/": LegacyRoute(frozenset({"POST"}), "digital_human_video"),
    "/video/meta_human_video/progress/": LegacyRoute(frozenset({"GET"}), "digital_human_video"),
    "/video/meta_human_video/cancel/": LegacyRoute(frozenset({"POST"}), "digital_human_video"),
    "/video/publish_v2/": LegacyRoute(
        frozenset({"POST"}), "platform_publish", review_required=True
    ),
    "/voices/": LegacyRoute(frozenset({"GET", "POST", "PUT", "DELETE"}), "voice_assets"),
}


def normalize_legacy_path(route_path: str) -> str:
    segments = [segment for segment in route_path.replace("\\", "/").split("/") if segment]
    if any(segment in {".", ".."} for segment in segments):
        raise ValueError("Invalid legacy route path.")
    return f"/{'/'.join(segments)}/"


def public_capabilities() -> list[dict[str, object]]:
    grouped: dict[str, list[str]] = {}
    for path, route in LEGACY_ROUTES.items():
        grouped.setdefault(route.capability, []).append(path)

    return [
        {
            "id": capability,
            "routes": sorted(paths),
            "review_required": any(LEGACY_ROUTES[path].review_required for path in paths),
        }
        for capability, paths in sorted(grouped.items())
    ]
