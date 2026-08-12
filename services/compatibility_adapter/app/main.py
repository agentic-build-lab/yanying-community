import asyncio
import json

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from .legacy_client import LegacyEngineRequestError, request_legacy, request_legacy_json
from .route_catalog import LEGACY_ROUTES, normalize_legacy_path, public_capabilities
from .runtime_config import legacy_adapter_config

app = FastAPI(title="MetaHuman Legacy Engine Adapter", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^http://(127\.0\.0\.1|localhost):\d+$",
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "X-Metahuman-Review-Approved"],
)


@app.get("/health")
async def health() -> dict[str, object]:
    version, algorithm = await asyncio.gather(
        asyncio.to_thread(
            request_legacy_json, "/version/", timeout=legacy_adapter_config.probe_timeout_sec
        ),
        asyncio.to_thread(
            request_legacy_json,
            "/algorithm/status/",
            timeout=legacy_adapter_config.probe_timeout_sec,
        ),
    )
    available = version is not None or algorithm is not None
    return {
        "status": "ok" if available else "degraded",
        "bind_host": legacy_adapter_config.bind_host,
        "legacy_engine": {
            "available": available,
            "url": legacy_adapter_config.legacy_engine_url,
            "version": version,
            "algorithm": algorithm,
        },
        "authorization": {
            "activation_proxy_enabled": False,
            "local_entry_only": True,
            "publish_review_required": True,
        },
    }


@app.get("/api/legacy/capabilities")
def capabilities() -> dict[str, object]:
    return {"items": public_capabilities()}


@app.get("/api/legacy/catalog")
async def catalog() -> dict[str, object]:
    (
        voices,
        meta_humans,
        music,
        templates,
        fonts,
        assets,
        reference_audio,
        covers,
        algorithm,
        tts_info,
        config,
        prompt_config,
    ) = await asyncio.gather(
        asyncio.to_thread(request_legacy_json, "/voices/", timeout=4),
        asyncio.to_thread(request_legacy_json, "/meta_human/", timeout=4),
        asyncio.to_thread(request_legacy_json, "/background_music/", timeout=4),
        asyncio.to_thread(request_legacy_json, "/video/clip_template/", timeout=4),
        asyncio.to_thread(request_legacy_json, "/video/fonts/", timeout=4),
        asyncio.to_thread(request_legacy_json, "/assets/", timeout=4),
        asyncio.to_thread(request_legacy_json, "/audio/ref_audio/", timeout=4),
        asyncio.to_thread(request_legacy_json, "/cover/", timeout=4),
        asyncio.to_thread(request_legacy_json, "/algorithm/status/", timeout=4),
        asyncio.to_thread(request_legacy_json, "/algorithm/tts/info/", timeout=4),
        asyncio.to_thread(request_legacy_json, "/config/?key=api", timeout=4),
        asyncio.to_thread(request_legacy_json, "/config/prompt/", timeout=4),
    )
    raw_config = config.get("data") if isinstance(config, dict) else None
    public_config = {}
    if isinstance(raw_config, dict):
        public_config = {
            key: raw_config.get(key)
            for key in (
                "wordService",
                "titleService",
                "voiceModelType",
                "videoServiceType",
                "batchSize",
                "videoClipEncoder",
            )
        }
    return {
        "available": any(
            item is not None for item in (voices, meta_humans, music, templates, fonts, assets)
        ),
        "voices": voices,
        "meta_humans": meta_humans,
        "background_music": music,
        "clip_templates": templates,
        "fonts": fonts,
        "assets": assets,
        "reference_audio": reference_audio,
        "cover_templates": covers,
        "algorithm": algorithm,
        "tts_info": tts_info,
        "runtime_config": public_config,
        "prompt_config": prompt_config,
    }


@app.post("/api/legacy/runtime-config")
async def update_runtime_config(request: Request) -> dict[str, object]:
    payload = await request.json()
    allowed_keys = {
        "wordService",
        "titleService",
        "voiceModelType",
        "videoServiceType",
        "batchSize",
        "videoClipEncoder",
    }
    updates = {key: payload[key] for key in allowed_keys if key in payload}
    current = await asyncio.to_thread(request_legacy_json, "/config/?key=api", timeout=4)
    current_data = current.get("data") if isinstance(current, dict) else None
    if not isinstance(current_data, dict):
        raise HTTPException(
            status_code=502, detail="Legacy runtime configuration could not be read."
        )
    merged = {**current_data, **updates}
    status, body, _ = await asyncio.to_thread(
        request_legacy,
        "/config/",
        method="POST",
        body=json.dumps({"key": "api", "value": merged}, ensure_ascii=False).encode("utf-8"),
        content_type="application/json; charset=utf-8",
    )
    if status >= 400:
        raise HTTPException(
            status_code=502, detail="Legacy runtime configuration could not be saved."
        )
    try:
        result = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=502, detail="Legacy runtime configuration returned invalid JSON."
        ) from exc
    return result


@app.api_route(
    "/api/legacy/proxy/{route_path:path}",
    methods=["GET", "POST", "PUT", "DELETE"],
)
async def proxy_legacy_route(route_path: str, request: Request) -> Response:
    try:
        normalized_path = normalize_legacy_path(route_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    route = LEGACY_ROUTES.get(normalized_path)
    if route is None:
        raise HTTPException(
            status_code=404, detail="Legacy route is not in the migration allowlist."
        )
    if request.method not in route.methods:
        raise HTTPException(status_code=405, detail="Method is not allowed for this legacy route.")
    if (
        route.review_required
        and request.headers.get("X-Metahuman-Review-Approved", "").lower() != "true"
    ):
        raise HTTPException(
            status_code=409, detail="Publishing requires an explicit completed review."
        )

    body = await request.body()
    if len(body) > legacy_adapter_config.max_request_bytes:
        raise HTTPException(status_code=413, detail="Request body exceeds the adapter limit.")

    try:
        status, response_body, media_type = await asyncio.to_thread(
            request_legacy,
            normalized_path,
            method=request.method,
            query=request.url.query,
            body=body or None,
            content_type=request.headers.get("content-type"),
        )
    except LegacyEngineRequestError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return Response(content=response_body, status_code=status, media_type=media_type)
