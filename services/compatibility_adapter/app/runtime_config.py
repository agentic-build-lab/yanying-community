import os
from dataclasses import dataclass


@dataclass(frozen=True)
class LegacyAdapterConfig:
    bind_host: str = os.getenv("METAHUMAN_LEGACY_ADAPTER_BIND_HOST", "127.0.0.1")
    legacy_engine_url: str = os.getenv("METAHUMAN_LEGACY_ENGINE_URL", "http://127.0.0.1:35005")
    request_timeout_sec: int = int(os.getenv("METAHUMAN_LEGACY_REQUEST_TIMEOUT_SEC", "900"))
    probe_timeout_sec: float = float(os.getenv("METAHUMAN_LEGACY_PROBE_TIMEOUT_SEC", "1.5"))
    max_request_bytes: int = int(
        os.getenv("METAHUMAN_LEGACY_MAX_REQUEST_BYTES", str(512 * 1024 * 1024))
    )


legacy_adapter_config = LegacyAdapterConfig()
