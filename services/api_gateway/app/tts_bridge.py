from pydantic import BaseModel, Field


class TtsGenerateRequest(BaseModel):
    text: str
    prompt_audio: str | None = Field(default=None)
    output_path: str | None = Field(default=None)
    voice_id: str = Field(default="clear_male_zh")
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    dry_run: bool = Field(default=True)


class TtsGenerateResponse(BaseModel):
    accepted: bool
    dry_run: bool
    message: str


def preview_tts_request(payload: TtsGenerateRequest) -> TtsGenerateResponse:
    if payload.dry_run:
        return TtsGenerateResponse(
            accepted=True,
            dry_run=True,
            message="TTS dry-run accepted. Real worker invocation is disabled in this skeleton.",
        )

    from .legacy_tts_client import LegacyTtsError, call_legacy_tts

    try:
        result = call_legacy_tts(payload)
    except LegacyTtsError as exc:
        return TtsGenerateResponse(
            accepted=False,
            dry_run=False,
            message=str(exc),
        )

    return TtsGenerateResponse(
        accepted=True,
        dry_run=False,
        message=f"Legacy TTS request completed with status {result['status_code']}.",
    )
