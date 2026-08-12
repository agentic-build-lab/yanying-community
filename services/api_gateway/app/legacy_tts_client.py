import json
from urllib.error import URLError
from urllib.request import Request, urlopen

from .runtime_config import runtime_config
from .tts_bridge import TtsGenerateRequest


class LegacyTtsError(RuntimeError):
    pass


def call_legacy_tts(payload: TtsGenerateRequest) -> dict[str, object]:
    if not runtime_config.enable_legacy_tts:
        raise LegacyTtsError(
            "Legacy TTS bridge is disabled. Set METAHUMAN_ENABLE_LEGACY_TTS=1 to enable it."
        )

    request_body = {
        "prompt_audio": payload.prompt_audio,
        "text": payload.text,
        "output_path": payload.output_path,
        "args": {
            "do_sample": True,
            "top_p": 0.8,
            "top_k": 30,
            "temperature": 1.0,
            "length_penalty": 0.0,
            "num_beams": 3,
            "repetition_penalty": 10.0,
            "max_mel_tokens": 600,
            "max_text_tokens_per_sentence": 120,
        },
    }

    request = Request(
        runtime_config.legacy_tts_url,
        data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=10) as response:
            raw_body = response.read().decode("utf-8", errors="replace")
            return {
                "status_code": response.status,
                "body": raw_body,
            }
    except URLError as exc:
        raise LegacyTtsError(str(exc)) from exc
