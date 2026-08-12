import json
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from .runtime_config import legacy_adapter_config


class LegacyEngineRequestError(RuntimeError):
    pass


def request_legacy(
    path: str,
    *,
    method: str = "GET",
    query: str = "",
    body: bytes | None = None,
    content_type: str | None = None,
    timeout: float | None = None,
) -> tuple[int, bytes, str]:
    url = urljoin(legacy_adapter_config.legacy_engine_url.rstrip("/") + "/", path.lstrip("/"))
    if query:
        url = f"{url}?{query}"

    headers = {"Accept": "application/json"}
    if content_type:
        headers["Content-Type"] = content_type
    request = Request(url, data=body, headers=headers, method=method)

    try:
        with urlopen(
            request, timeout=timeout or legacy_adapter_config.request_timeout_sec
        ) as response:
            return response.status, response.read(), response.headers.get_content_type()
    except HTTPError as exc:
        return exc.code, exc.read(), exc.headers.get_content_type()
    except (URLError, OSError, TimeoutError) as exc:
        raise LegacyEngineRequestError(f"Legacy engine request failed: {exc}") from exc


def request_legacy_json(path: str, *, timeout: float | None = None) -> dict[str, object] | None:
    try:
        status, body, _ = request_legacy(path, timeout=timeout)
    except LegacyEngineRequestError:
        return None
    if status >= 400:
        return None
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else {"data": parsed}
