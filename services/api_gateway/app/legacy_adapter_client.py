from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from .runtime_config import runtime_config


class LegacyAdapterRequestError(RuntimeError):
    pass


def request_legacy_adapter(
    path: str,
    *,
    method: str = "GET",
    query: str = "",
    body: bytes | None = None,
    content_type: str | None = None,
    review_approved: str | None = None,
) -> tuple[int, bytes, str]:
    url = urljoin(runtime_config.legacy_adapter_url.rstrip("/") + "/", path.lstrip("/"))
    if query:
        url = f"{url}?{query}"
    headers = {"Accept": "application/json"}
    if content_type:
        headers["Content-Type"] = content_type
    if review_approved:
        headers["X-Metahuman-Review-Approved"] = review_approved
    request = Request(url, data=body, headers=headers, method=method)

    try:
        with urlopen(request, timeout=runtime_config.legacy_adapter_timeout_sec) as response:
            return response.status, response.read(), response.headers.get_content_type()
    except HTTPError as exc:
        return exc.code, exc.read(), exc.headers.get_content_type()
    except (URLError, OSError, TimeoutError) as exc:
        raise LegacyAdapterRequestError(f"Legacy adapter request failed: {exc}") from exc
