from __future__ import annotations

import argparse
import html
import json
import logging
import os
import re
import subprocess
import tempfile
from copy import deepcopy
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import requests
from flask import Flask, jsonify, make_response, request

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENGINE_RUNTIME_ROOT = Path(
    os.getenv(
        "METAHUMAN_ENGINE_RUNTIME_ROOT",
        str(PROJECT_ROOT / "packages" / "engine_runtime"),
    )
)
RUNTIME_DIR = Path(
    os.getenv("METAHUMAN_CONTENT_RUNTIME_DIR", str(PROJECT_ROOT / ".runtime" / "private"))
)
LOG_DIR = Path(
    os.getenv("METAHUMAN_CONTENT_LOG_DIR", str(PROJECT_ROOT / ".runtime" / "logs" / "content"))
)
CONFIG_FILE = Path(
    os.getenv("METAHUMAN_CONTENT_CONFIG_FILE", str(RUNTIME_DIR / "content_api_config.json"))
)
APP_SERVER_INTERNAL = ENGINE_RUNTIME_ROOT / "_internal" / "app3_server" / "_internal"
CHROME_EXE = APP_SERVER_INTERNAL / "static" / "chrome" / "Chrome-bin" / "chrome.exe"
LOCAL_WHISPER_PYTHON = Path(
    os.getenv(
        "METAHUMAN_LOCAL_WHISPER_PYTHON",
        "python",
    )
)
LOCAL_WHISPER_SCRIPT = Path(
    os.getenv(
        "METAHUMAN_LOCAL_WHISPER_SCRIPT",
        str(PROJECT_ROOT / "scripts" / "local_whisper_asr.py"),
    )
)
LOCAL_WHISPER_MODEL = Path(
    os.getenv(
        "METAHUMAN_LOCAL_WHISPER_MODEL", str(PROJECT_ROOT / "models" / "asr" / "whisper-medium.pt")
    )
)
BROWSER_PROFILE_DIR = Path(
    os.getenv(
        "METAHUMAN_CONTENT_BROWSER_PROFILE", str(PROJECT_ROOT / ".runtime" / "browser-profile")
    )
)
DEFAULT_PORT = 35605
USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 "
    "Mobile/15E148 Safari/604.1"
)

DEFAULT_CONFIG: dict[str, Any] = {
    "version": 1,
    "douyin": {
        "browser_fallback": True,
        "request_timeout": 20,
        "browser_timeout": 25,
        "return_description_without_asr": True,
    },
    "asr": {
        "enabled": False,
        "provider": "dashscope",
        "base_url": "https://api.openai.com/v1",
        "api_key": "",
        "model": "paraformer-v2",
        "workspace": "",
        "local_model_path": str(LOCAL_WHISPER_MODEL),
        "local_device": "auto",
        "language": "zh",
        "timeout": 900,
    },
    "llm": {
        "enabled": False,
        "provider": "openai_compatible",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key": "",
        "model": "qwen-plus",
        "app_id": "",
        "deepseek_thinking": "disabled",
        "deepseek_reasoning_effort": "high",
        "temperature": 0.7,
        "timeout": 120,
    },
    "term_corrections": {
        "enabled": True,
        "items": [
            {"from": "A件", "to": "Agent"},
            {"from": "A 件", "to": "Agent"},
            {"from": "Obonai", "to": "OpenAI"},
            {"from": "PBT", "to": "PPT"},
            {"from": "智能体集形", "to": "智能体集群"},
            {"from": "调餐", "to": "调参"},
            {"from": "门开", "to": "门槛"},
            {"from": "铺绘", "to": "普惠"},
            {"from": "一件部署", "to": "一键部署"},
            {"from": "一件欠一付", "to": "一键部署"},
        ],
    },
}

PROVIDER_TEMPLATES = [
    {
        "name": "通义千问/百炼 OpenAI 兼容",
        "provider": "openai_compatible",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
    },
    {
        "name": "DeepSeek V4 Flash",
        "provider": "openai_compatible",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-v4-flash",
    },
    {
        "name": "DeepSeek V4 Pro",
        "provider": "openai_compatible",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-v4-pro",
    },
    {
        "name": "OpenAI 官方兼容",
        "provider": "openai_compatible",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4.1-mini",
    },
    {
        "name": "Moonshot/Kimi OpenAI 兼容",
        "provider": "openai_compatible",
        "base_url": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-8k",
    },
    {
        "name": "智谱 GLM OpenAI 兼容",
        "provider": "openai_compatible",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-flash",
    },
    {
        "name": "MiniMax OpenAI 兼容",
        "provider": "openai_compatible",
        "base_url": "https://api.minimax.chat/v1",
        "model": "MiniMax-Text-01",
    },
    {
        "name": "Ollama 本地 OpenAI 兼容",
        "provider": "openai_compatible",
        "base_url": "http://127.0.0.1:11434/v1",
        "model": "qwen2.5:7b",
    },
    {
        "name": "百炼应用 APP_ID 模式",
        "provider": "dashscope_application",
        "base_url": "",
        "model": "",
    },
]


def setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("yanying.content")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.FileHandler(LOG_DIR / "content_worker.log", encoding="utf-8")
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        logger.addHandler(console)
    return logger


logger = setup_logging()
app = Flask(__name__)


class UserFacingError(RuntimeError):
    pass


def deep_merge(base: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in (update or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config() -> dict[str, Any]:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists():
        save_config(DEFAULT_CONFIG)
        return deepcopy(DEFAULT_CONFIG)
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to read config, using defaults: %s", exc)
        return deepcopy(DEFAULT_CONFIG)
    config = deep_merge(DEFAULT_CONFIG, data)
    configured_model = Path(str(config["asr"].get("local_model_path") or ""))
    if not configured_model.exists():
        config["asr"]["local_model_path"] = str(LOCAL_WHISPER_MODEL)
        save_config(config)
    return config


def save_config(config: dict[str, Any]) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def masked_secret(value: str) -> dict[str, Any]:
    value = value or ""
    if not value:
        return {"set": False, "hint": ""}
    if len(value) <= 8:
        hint = "*" * len(value)
    else:
        hint = value[:3] + "*" * max(4, len(value) - 7) + value[-4:]
    return {"set": True, "hint": hint}


def public_config(config: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(config)
    result["asr"]["api_key"] = ""
    result["asr"]["api_key_info"] = masked_secret(config["asr"].get("api_key", ""))
    result["llm"]["api_key"] = ""
    result["llm"]["api_key_info"] = masked_secret(config["llm"].get("api_key", ""))
    result["provider_templates"] = PROVIDER_TEMPLATES
    return result


def success(data: Any = None):
    return jsonify({"code": 0, "message": "success", "data": data})


def error_response(message: str, status: int = 200):
    response = jsonify({"code": 1, "message": message, "data": ""})
    response.status_code = status
    return response


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    return response


@app.route("/", methods=["GET"])
@app.route("/health", methods=["GET"])
def health():
    return success(
        {
            "name": "yanying_content_worker",
            "status": "ok",
            "port": DEFAULT_PORT,
            "provider": load_config().get("llm", {}).get("provider", "local"),
        }
    )


@app.route("/api/config", methods=["GET", "POST", "OPTIONS"])
def api_config():
    if request.method == "OPTIONS":
        return make_response("", 204)
    current = load_config()
    if request.method == "GET":
        return success(public_config(current))

    payload = request.get_json(silent=True) or {}
    next_config = deep_merge(current, payload)

    clear_asr_key = bool(payload.get("asr", {}).pop("clear_api_key", False))
    clear_llm_key = bool(payload.get("llm", {}).pop("clear_api_key", False))
    next_config["asr"].pop("clear_api_key", None)
    next_config["llm"].pop("clear_api_key", None)

    # Empty secret fields mean "keep existing" so the config page can avoid echoing keys.
    if clear_asr_key:
        next_config["asr"]["api_key"] = ""
    elif not payload.get("asr", {}).get("api_key"):
        next_config["asr"]["api_key"] = current["asr"].get("api_key", "")
    if clear_llm_key:
        next_config["llm"]["api_key"] = ""
    elif not payload.get("llm", {}).get("api_key"):
        next_config["llm"]["api_key"] = current["llm"].get("api_key", "")

    next_config["version"] = DEFAULT_CONFIG["version"]
    save_config(next_config)
    return success(public_config(next_config))


@app.route("/api/config/templates", methods=["GET"])
def api_config_templates():
    return success(PROVIDER_TEMPLATES)


@app.route("/api/llm/test", methods=["POST", "OPTIONS"])
def api_llm_test():
    if request.method == "OPTIONS":
        return make_response("", 204)
    try:
        text = call_llm(
            [
                {"role": "system", "content": "你是一个接口连通性测试助手。"},
                {"role": "user", "content": "请只回复：连接成功"},
            ],
            temperature=0,
            max_tokens=32,
        )
        return success({"text": text})
    except Exception as exc:
        logger.exception("LLM test failed")
        return error_response(str(exc), 500)


@app.route("/api/douyin/parse", methods=["POST", "OPTIONS"])
def api_douyin_parse():
    if request.method == "OPTIONS":
        return make_response("", 204)
    payload = request.get_json(silent=True) or {}
    try:
        result = parse_douyin_share(payload.get("text", ""))
        return success(result)
    except Exception as exc:
        logger.exception("Douyin parse failed")
        return error_response(str(exc), 500)


@app.route("/text/douyin/", methods=["POST", "OPTIONS"])
def text_douyin():
    if request.method == "OPTIONS":
        return make_response("", 204)
    payload = request.get_json(silent=True) or {}
    try:
        config = load_config()
        parsed = parse_douyin_share(payload.get("text", ""))
        video_url = parsed.get("video_url", "")
        desc = parsed.get("description", "")
        transcript = ""

        asr_error = ""
        if config["asr"].get("enabled") and video_url:
            try:
                transcript = transcribe_media_url(video_url, config)
            except Exception as exc:
                asr_error = str(exc)
                logger.exception("Douyin ASR failed; returning page description when available")

        if transcript:
            text = transcript.strip()
        elif desc and config["douyin"].get("return_description_without_asr", True):
            if not config["asr"].get("enabled"):
                reason = (
                    "已解析到抖音页面，但还没有启用语音识别 ASR。\n"
                    "DeepSeek Token 只负责文案改写、标题生成和 AI 对话，不能把视频声音转成文字。\n"
                    "如果要提取视频口播，请在增强配置页启用 ASR，并填写 DashScope 或 OpenAI 兼容转写 API_KEY。\n\n"
                    "先返回抖音页面描述：\n\n"
                )
            elif not video_url:
                reason = (
                    "已解析到抖音页面，但没有拿到可转写的视频直链。\n"
                    "这通常是抖音反爬、图文内容或页面数据缺失导致的。\n\n"
                    "先返回抖音页面描述：\n\n"
                )
            elif asr_error:
                reason = "视频口播识别暂时失败，已先提取作品页面文案；可以继续改写和创作。\n\n"
            else:
                reason = "语音识别未完成，先返回抖音页面描述：\n\n"
            text = reason + desc.strip()
        else:
            raise UserFacingError("已解析到抖音链接，但没有可识别的视频音频或描述。")

        text = apply_term_corrections(text, config)
        return success(text)
    except Exception as exc:
        logger.exception("Enhanced Douyin extraction failed")
        return error_response(str(exc), 500)


@app.route("/text/rewrite/", methods=["POST", "OPTIONS"])
def text_rewrite():
    if request.method == "OPTIONS":
        return make_response("", 204)
    payload = request.get_json(silent=True) or {}
    try:
        text = str(payload.get("text", "")).strip()
        if not text:
            raise UserFacingError("待改写文案为空。")
        text = apply_term_corrections(text)
        prompt1 = str(payload.get("prompt1", "") or "").strip()
        prompt2 = str(payload.get("prompt2", "") or "").strip()
        rewritten = rewrite_copywriting(text, prompt1, prompt2)
        return success(rewritten)
    except Exception as exc:
        logger.exception("Enhanced rewrite failed")
        return error_response(str(exc), 500)


@app.route("/title/", methods=["POST", "OPTIONS"])
def title_v1():
    if request.method == "OPTIONS":
        return make_response("", 204)
    payload = request.get_json(silent=True) or {}
    try:
        text = str(payload.get("text", "")).strip()
        text = apply_term_corrections(text)
        data = generate_title_topics(text)
        return success(data)
    except Exception as exc:
        logger.exception("Enhanced title failed")
        return error_response(str(exc), 500)


@app.route("/title/v2/", methods=["POST", "OPTIONS"])
def title_v2():
    if request.method == "OPTIONS":
        return make_response("", 204)
    payload = request.get_json(silent=True) or {}
    try:
        text = str(payload.get("text", "")).strip()
        text = apply_term_corrections(text)
        title_lines = generate_visual_title_lines(text)
        return success(title_lines)
    except Exception as exc:
        logger.exception("Enhanced title v2 failed")
        return error_response(str(exc), 500)


@app.route("/text/bailian_app/", methods=["POST", "OPTIONS"])
def text_bailian_app():
    if request.method == "OPTIONS":
        return make_response("", 204)
    payload = request.get_json(silent=True) or {}
    try:
        prompt = str(payload.get("prompt", "") or "").strip()
        messages = payload.get("messages") or []
        if messages:
            llm_messages = normalize_messages(messages)
        else:
            llm_messages = [{"role": "user", "content": prompt}]
        text = call_llm(llm_messages)
        return success({"text": text, "session_id": payload.get("session_id", "")})
    except Exception as exc:
        logger.exception("Enhanced chat failed")
        return error_response(str(exc), 500)


@app.route("/chat/aliyun/", methods=["POST", "OPTIONS"])
def chat_aliyun():
    if request.method == "OPTIONS":
        return make_response("", 204)
    payload = request.get_json(silent=True) or {}
    try:
        prompt = str(payload.get("prompt", "") or "").strip()
        messages = payload.get("messages") or []
        if messages:
            llm_messages = normalize_messages(messages)
        else:
            llm_messages = [{"role": "user", "content": prompt}]
        text = call_llm(llm_messages)
        return success({"text": text, "session_id": payload.get("session_id", "")})
    except Exception as exc:
        logger.exception("Enhanced aliyun-compatible chat failed")
        return error_response(str(exc), 500)


def extract_first_url(text: str) -> str:
    match = re.search(r"https?://[^\s\"'<>，。]+", str(text or ""))
    if not match:
        raise UserFacingError("未找到 http/https 开头的抖音分享链接。")
    return match.group(0).rstrip(").,;，。")


def new_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }
    )
    return session


def request_get(session: requests.Session, url: str, timeout: int) -> requests.Response:
    try:
        return session.get(url, allow_redirects=True, timeout=timeout)
    except requests.exceptions.SSLError:
        logger.warning("SSL verification failed for %s, retrying without verification", url)
        return session.get(url, allow_redirects=True, timeout=timeout, verify=False)


def parse_douyin_share(share_text: str) -> dict[str, Any]:
    config = load_config()
    timeout = int(config["douyin"].get("request_timeout") or 20)
    input_url = extract_first_url(share_text)
    session = new_session()
    stages: list[dict[str, Any]] = []

    first = request_get(session, input_url, timeout)
    final_url = first.url
    stages.append(
        {
            "stage": "follow_redirect",
            "input_url": input_url,
            "final_url": final_url,
            "status": first.status_code,
        }
    )

    content_id = extract_content_id(final_url) or extract_content_id(first.text)
    content_type = detect_content_type(final_url)
    if not content_id:
        raise UserFacingError(f"抖音跳转成功，但未识别到视频/图文 ID：{final_url}")

    candidate_urls = build_candidate_urls(content_id, content_type, final_url)
    last_error = ""
    for candidate in candidate_urls:
        try:
            page = request_get(session, candidate, timeout)
            stages.append(
                {
                    "stage": "fetch_share_page",
                    "url": candidate,
                    "final_url": page.url,
                    "status": page.status_code,
                    "length": len(page.text or ""),
                }
            )
            parsed = parse_douyin_html(page.text, content_id)
            parsed.update(
                {
                    "input_url": input_url,
                    "final_url": final_url,
                    "content_id": content_id,
                    "content_type": content_type,
                    "share_page_url": candidate,
                    "stages": stages,
                    "parser": "requests",
                }
            )
            return parsed
        except Exception as exc:
            last_error = str(exc)
            stages.append(
                {"stage": "parse_share_page_failed", "url": candidate, "error": last_error}
            )

    if config["douyin"].get("browser_fallback", True):
        try:
            parsed = parse_with_browser(
                candidate_urls[0], content_id, int(config["douyin"].get("browser_timeout") or 25)
            )
            parsed.update(
                {
                    "input_url": input_url,
                    "final_url": final_url,
                    "content_id": content_id,
                    "content_type": content_type,
                    "share_page_url": candidate_urls[0],
                    "stages": stages + parsed.get("stages", []),
                    "parser": "browser",
                }
            )
            return parsed
        except Exception as exc:
            last_error = f"{last_error}; browser fallback failed: {exc}"
            stages.append({"stage": "browser_fallback_failed", "error": str(exc)})

    raise UserFacingError(f"未能从抖音页面提取视频信息。最后错误：{last_error}")


def extract_content_id(text: str) -> str:
    text = unquote(str(text or ""))
    patterns = [
        r"/video/(\d+)",
        r"/note/(\d+)",
        r"modal_id=(\d+)",
        r"aweme_id=(\d+)",
        r"video_id=(\d+)",
        r"note_id=(\d+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return ""


def detect_content_type(url: str) -> str:
    url = str(url or "").lower()
    if "/note/" in url or "note_id=" in url:
        return "note"
    return "video"


def build_candidate_urls(content_id: str, content_type: str, final_url: str) -> list[str]:
    urls: list[str] = []
    if content_type == "note":
        urls.extend(
            [
                f"https://www.iesdouyin.com/share/note/{content_id}",
                f"https://www.douyin.com/note/{content_id}",
            ]
        )
    urls.extend(
        [
            f"https://www.iesdouyin.com/share/video/{content_id}",
            f"https://www.douyin.com/video/{content_id}",
        ]
    )
    if final_url:
        urls.append(final_url)

    unique: list[str] = []
    for url in urls:
        if url and url not in unique:
            unique.append(url)
    return unique


def parse_douyin_html(page_text: str, content_id: str) -> dict[str, Any]:
    if not page_text:
        raise UserFacingError("抖音页面为空。")

    router_data = extract_router_data(page_text)
    item = find_video_item(router_data)
    if not item:
        raise UserFacingError("页面中没有找到 videoInfoRes/item_list 数据。")

    raw_description = str(item.get("desc") or item.get("item_title") or "").strip()
    if not raw_description:
        share_info = item.get("share_info") or {}
        raw_description = str(share_info.get("share_title") or "").strip()
    description = clean_description(raw_description)
    source_hashtags = extract_hashtags(raw_description)

    video_url = extract_video_url(item)
    image_urls = extract_image_urls(item)
    if not video_url and not image_urls:
        raise UserFacingError("找到了内容数据，但没有视频地址或图文图片地址。")

    return {
        "description": description,
        "source_description_raw": raw_description,
        "source_hashtags": source_hashtags,
        "video_url": video_url,
        "image_urls": image_urls,
        "has_video": bool(video_url),
        "raw_type": item.get("aweme_type"),
    }


def extract_router_data(page_text: str) -> Any:
    patterns = [
        r"window\._ROUTER_DATA\s*=\s*(.*?)</script>",
        r"window\.__INITIAL_STATE__\s*=\s*(.*?)</script>",
    ]
    for pattern in patterns:
        match = re.search(pattern, page_text, flags=re.S)
        if match:
            raw = match.group(1).strip()
            raw = raw.rstrip(";")
            return json.loads(html.unescape(raw))

    render_match = re.search(
        r'<script[^>]+id=["\']RENDER_DATA["\'][^>]*>(.*?)</script>',
        page_text,
        flags=re.S | re.I,
    )
    if render_match:
        raw = html.unescape(unquote(render_match.group(1).strip()))
        return json.loads(raw)

    raise UserFacingError("页面没有 window._ROUTER_DATA，可能需要登录、验证码或内容不可访问。")


def find_video_item(data: Any) -> dict[str, Any] | None:
    if isinstance(data, dict):
        if isinstance(data.get("item_list"), list) and data["item_list"]:
            return data["item_list"][0]
        if isinstance(data.get("videoInfoRes"), dict):
            item_list = data["videoInfoRes"].get("item_list")
            if isinstance(item_list, list) and item_list:
                return item_list[0]
        if isinstance(data.get("itemInfo"), dict):
            item_struct = data["itemInfo"].get("itemStruct")
            if isinstance(item_struct, dict):
                return item_struct
        for value in data.values():
            found = find_video_item(value)
            if found:
                return found
    elif isinstance(data, list):
        for value in data:
            found = find_video_item(value)
            if found:
                return found
    return None


def extract_video_url(item: dict[str, Any]) -> str:
    candidates: list[str] = []
    video = item.get("video") or {}
    for key in ("play_addr", "download_addr"):
        value = video.get(key) or {}
        candidates.extend(value.get("url_list") or [])
    for bit_rate in video.get("bit_rate") or []:
        play_addr = bit_rate.get("play_addr") or {}
        candidates.extend(play_addr.get("url_list") or [])

    for url in candidates:
        if url:
            return str(url).replace("playwm", "play")
    return ""


def extract_image_urls(item: dict[str, Any]) -> list[str]:
    image_urls: list[str] = []
    images = item.get("images") or item.get("image_infos") or []
    if isinstance(images, list):
        for image in images:
            if not isinstance(image, dict):
                continue
            for key in ("url_list", "download_url_list"):
                for url in image.get(key) or []:
                    if url and url not in image_urls:
                        image_urls.append(url)
            url = image.get("url")
            if url and url not in image_urls:
                image_urls.append(url)
    return image_urls


def extract_hashtags(description: str) -> list[str]:
    tags: list[str] = []
    for match in re.finditer(r"#([^\s#]+)", description or ""):
        tag = match.group(1).strip(" \t\r\n,，.。!！?？;；:：、")
        if tag and tag not in tags:
            tags.append(tag)
    return tags


def clean_description(description: str) -> str:
    description = re.sub(r"#\S+", "", description or "")
    description = re.sub(r"\s+", " ", description).strip()
    return description


def apply_term_corrections(text: str, config: dict[str, Any] | None = None) -> str:
    if not text:
        return text
    correction_config = (config or load_config()).get("term_corrections") or {}
    if not correction_config.get("enabled", True):
        return text

    corrected = text
    for item in correction_config.get("items") or []:
        if isinstance(item, dict):
            source = str(item.get("from") or "")
            target = str(item.get("to") or "")
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            source = str(item[0] or "")
            target = str(item[1] or "")
        else:
            continue
        if source:
            corrected = corrected.replace(source, target)
    return corrected


def parse_with_browser(url: str, content_id: str, timeout_seconds: int) -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise UserFacingError(f"Playwright 不可用：{exc}") from exc

    if not CHROME_EXE.exists():
        raise UserFacingError(f"未找到本地 Chrome：{CHROME_EXE}")

    BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    stages: list[dict[str, Any]] = []
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_PROFILE_DIR),
            executable_path=str(CHROME_EXE),
            headless=True,
            viewport={"width": 390, "height": 844},
            user_agent=USER_AGENT,
            args=["--disable-blink-features=AutomationControlled", "--no-first-run"],
        )
        page = context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
            page.wait_for_timeout(2500)
            content = page.content()
            stages.append({"stage": "browser_fetch", "url": url, "length": len(content)})
            try:
                router_json = page.evaluate(
                    "() => JSON.stringify(window._ROUTER_DATA || window.__INITIAL_STATE__ || null)"
                )
                if router_json and router_json != "null":
                    item = find_video_item(json.loads(router_json))
                    if item:
                        raw_description = str(item.get("desc") or item.get("item_title") or "")
                        parsed = {
                            "description": clean_description(raw_description),
                            "source_description_raw": raw_description,
                            "source_hashtags": extract_hashtags(raw_description),
                            "video_url": extract_video_url(item),
                            "image_urls": extract_image_urls(item),
                            "has_video": bool(extract_video_url(item)),
                            "raw_type": item.get("aweme_type"),
                            "stages": stages,
                        }
                        if parsed["video_url"] or parsed["image_urls"]:
                            return parsed
            except Exception as exc:
                stages.append({"stage": "browser_window_data_failed", "error": str(exc)})
            parsed = parse_douyin_html(content, content_id)
            parsed["stages"] = stages
            return parsed
        finally:
            context.close()


def transcribe_media_url(media_url: str, config: dict[str, Any]) -> str:
    asr_config = config["asr"]
    provider = asr_config.get("provider", "dashscope")
    api_key = asr_config.get("api_key", "")
    if provider == "dashscope":
        if not api_key:
            raise UserFacingError("已启用语音识别，但没有配置 DashScope API_KEY。")
        return transcribe_dashscope(media_url, asr_config)
    if provider == "openai_compatible":
        if not api_key:
            raise UserFacingError("已启用语音识别，但没有配置 OpenAI 兼容 API_KEY。")
        return transcribe_openai_compatible(media_url, asr_config)
    if provider == "local_whisper":
        return transcribe_local_whisper(media_url, asr_config)
    raise UserFacingError(f"不支持的语音识别服务：{provider}")


def transcribe_dashscope(media_url: str, asr_config: dict[str, Any]) -> str:
    from dashscope.audio.asr import Transcription

    model = asr_config.get("model") or "paraformer-v2"
    api_key = asr_config.get("api_key") or ""
    workspace = asr_config.get("workspace") or None

    kwargs: dict[str, Any] = {"model": model, "file_urls": [media_url], "api_key": api_key}
    if workspace:
        kwargs["workspace"] = workspace

    task_response = Transcription.async_call(**kwargs)
    if getattr(task_response, "status_code", None) != HTTPStatus.OK:
        raise UserFacingError(
            "DashScope ASR 任务创建失败：" + str(getattr(task_response, "message", task_response))
        )

    wait_kwargs = {"task": task_response, "api_key": api_key}
    if workspace:
        wait_kwargs["workspace"] = workspace
    transcription_response = Transcription.wait(**wait_kwargs)
    if getattr(transcription_response, "status_code", None) != HTTPStatus.OK:
        raise UserFacingError(
            "DashScope ASR 任务失败："
            + str(getattr(transcription_response, "message", transcription_response))
        )

    output = getattr(transcription_response, "output", None)
    results = get_mapping_value(output, "results") or []
    if not results:
        raise UserFacingError("DashScope ASR 没有返回转写结果。")

    texts: list[str] = []
    for item in results:
        transcription_url = get_mapping_value(item, "transcription_url")
        if not transcription_url:
            continue
        result = requests.get(transcription_url, timeout=60).json()
        transcripts = result.get("transcripts") or []
        for transcript in transcripts:
            text = str(transcript.get("text") or "").strip()
            if text:
                texts.append(text)

    if not texts:
        raise UserFacingError("DashScope ASR 转写结果为空。")
    return "\n".join(texts)


def transcribe_openai_compatible(media_url: str, asr_config: dict[str, Any]) -> str:
    base_url = (asr_config.get("base_url") or "https://api.openai.com/v1").rstrip("/")
    api_key = asr_config.get("api_key") or ""
    model = asr_config.get("model") or "whisper-1"
    suffix = ".mp4"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp:
        temp_path = Path(temp.name)
        with requests.get(media_url, stream=True, timeout=120) as response:
            response.raise_for_status()
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    temp.write(chunk)
    try:
        with temp_path.open("rb") as file_handle:
            response = requests.post(
                f"{base_url}/audio/transcriptions",
                headers={"Authorization": f"Bearer {api_key}"},
                data={"model": model},
                files={"file": (temp_path.name, file_handle, "video/mp4")},
                timeout=300,
            )
        if response.status_code >= 400:
            raise UserFacingError(f"OpenAI 兼容 ASR 失败：{response.text[:500]}")
        data = response.json()
        text = str(data.get("text") or "").strip()
        if not text:
            raise UserFacingError("OpenAI 兼容 ASR 返回为空。")
        return text
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            pass


def transcribe_local_whisper(media_url: str, asr_config: dict[str, Any]) -> str:
    python_exe = Path(asr_config.get("local_python") or LOCAL_WHISPER_PYTHON)
    script_path = LOCAL_WHISPER_SCRIPT
    model_path = Path(asr_config.get("local_model_path") or LOCAL_WHISPER_MODEL)
    device = str(asr_config.get("local_device") or "auto")
    language = str(asr_config.get("language") or "zh").strip()
    timeout = int(asr_config.get("timeout") or 900)

    if not python_exe.exists():
        raise UserFacingError(f"本地 Whisper Python 不存在：{python_exe}")
    if not script_path.exists():
        raise UserFacingError(f"本地 Whisper 脚本不存在：{script_path}")
    if not model_path.exists():
        raise UserFacingError(f"本地 Whisper 模型不存在：{model_path}")

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as temp:
            temp_path = Path(temp.name)
            with requests.get(
                media_url,
                headers={"User-Agent": USER_AGENT, "Referer": "https://www.douyin.com/"},
                stream=True,
                timeout=120,
            ) as response:
                response.raise_for_status()
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        temp.write(chunk)

        command = [
            str(python_exe),
            str(script_path),
            "--input",
            str(temp_path),
            "--model",
            str(model_path),
            "--device",
            device,
        ]
        if language:
            command.extend(["--language", language])

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        completed = subprocess.run(
            command,
            cwd=str(PROJECT_ROOT),
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise UserFacingError(f"本地 Whisper 识别失败：{detail[:1000]}")
        try:
            data = json.loads(completed.stdout)
        except Exception as exc:
            raise UserFacingError(
                f"本地 Whisper 返回格式无法识别：{completed.stdout[:1000]}"
            ) from exc
        text = str(data.get("text") or "").strip()
        if not text:
            raise UserFacingError("本地 Whisper 转写结果为空。")
        return text
    finally:
        if temp_path:
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass


def get_mapping_value(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def normalize_messages(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for message in messages:
        role = str(message.get("role") or message.get("type") or "user")
        if role == "ai":
            role = "assistant"
        if role not in {"system", "user", "assistant"}:
            role = "user"
        content = str(message.get("content") or message.get("text") or "")
        if content:
            normalized.append({"role": role, "content": content})
    return normalized or [{"role": "user", "content": ""}]


def call_llm(
    messages: list[dict[str, str]],
    temperature: float | None = None,
    max_tokens: int | None = None,
    allow_deepseek_retry: bool = True,
) -> str:
    config = load_config()["llm"]
    if not config.get("enabled"):
        raise UserFacingError("未启用大模型接口，请先打开增强配置并保存 LLM API。")

    provider = config.get("provider") or "openai_compatible"
    if provider == "dashscope_application":
        return call_dashscope_application(messages, config)
    if provider != "openai_compatible":
        raise UserFacingError(f"不支持的大模型接口类型：{provider}")

    base_url = (config.get("base_url") or "").rstrip("/")
    api_key = config.get("api_key") or ""
    model = config.get("model") or ""
    if not base_url or not model:
        raise UserFacingError("OpenAI 兼容接口需要填写 Base URL 和模型名。")
    if not api_key and "127.0.0.1" not in base_url and "localhost" not in base_url:
        raise UserFacingError("OpenAI 兼容接口需要填写 API_KEY。")

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature
        if temperature is not None
        else float(config.get("temperature", 0.7)),
    }
    if is_deepseek_config(config):
        thinking_type = str(config.get("deepseek_thinking") or "disabled").strip().lower()
        if thinking_type in {"enabled", "disabled"}:
            payload["thinking"] = {"type": thinking_type}
            reasoning_effort = (
                str(config.get("deepseek_reasoning_effort") or "high").strip().lower()
            )
            if thinking_type == "enabled" and reasoning_effort in {"high", "max"}:
                payload["reasoning_effort"] = reasoning_effort
    if max_tokens:
        payload["max_tokens"] = max_tokens

    response = requests.post(
        f"{base_url}/chat/completions",
        headers=headers,
        json=payload,
        timeout=int(config.get("timeout") or 120),
    )
    if response.status_code >= 400:
        raise UserFacingError(f"大模型接口请求失败：{response.text[:800]}")
    data = response.json()
    try:
        message = data["choices"][0]["message"]
        content = message.get("content")
    except Exception as exc:
        raise UserFacingError(f"大模型返回格式无法识别：{data}") from exc
    if (
        allow_deepseek_retry
        and not str(content or "").strip()
        and is_deepseek_config(config)
        and payload.get("thinking", {}).get("type") == "enabled"
    ):
        retry_payload = deepcopy(payload)
        retry_payload["thinking"] = {"type": "disabled"}
        retry_payload.pop("reasoning_effort", None)
        retry_response = requests.post(
            f"{base_url}/chat/completions",
            headers=headers,
            json=retry_payload,
            timeout=int(config.get("timeout") or 120),
        )
        if retry_response.status_code >= 400:
            raise UserFacingError(f"DeepSeek 非思考模式重试失败：{retry_response.text[:800]}")
        retry_data = retry_response.json()
        try:
            content = retry_data["choices"][0]["message"].get("content")
        except Exception as exc:
            raise UserFacingError(f"DeepSeek 重试返回格式无法识别：{retry_data}") from exc
    if not str(content or "").strip():
        raise UserFacingError(
            "大模型返回正文为空。DeepSeek 思考模式可能消耗了输出额度，请关闭思考模式后重试。"
        )
    return str(content or "").strip()


def is_deepseek_config(config: dict[str, Any]) -> bool:
    base_url = str(config.get("base_url") or "").lower()
    model = str(config.get("model") or "").lower()
    return "api.deepseek.com" in base_url or model.startswith("deepseek-")


def call_dashscope_application(messages: list[dict[str, str]], config: dict[str, Any]) -> str:
    from dashscope import Application

    api_key = config.get("api_key") or ""
    app_id = config.get("app_id") or ""
    if not api_key or not app_id:
        raise UserFacingError("百炼应用模式需要填写 API_KEY 和 APP_ID。")
    prompt = "\n\n".join(message["content"] for message in messages if message["role"] != "system")
    response = Application.call(api_key=api_key, app_id=app_id, prompt=prompt)
    if getattr(response, "status_code", None) != HTTPStatus.OK:
        raise UserFacingError("百炼应用请求失败：" + str(getattr(response, "message", response)))
    output = getattr(response, "output", None)
    return str(get_mapping_value(output, "text") or "").strip()


def rewrite_copywriting(text: str, prompt1: str, prompt2: str) -> str:
    system = (
        "你是短视频口播文案改写助手。请在不改变核心事实的前提下，"
        "把原文改写成自然、口语化、适合短视频表达的中文文案。"
        "不要输出解释、标题、项目符号或多余引号。"
    )
    custom = "\n".join(part for part in [prompt1, prompt2] if part)
    user = f"原文：\n{text}\n"
    if custom:
        user += f"\n额外要求：\n{custom}\n"
    user += "\n请直接输出改写后的文案。"
    return call_llm(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_tokens=2400,
    )


def generate_title_string(text: str) -> str:
    source_tags = "、".join("#" + tag for tag in extract_hashtags(text)[:8]) or "无"
    prompt = f"""请为下面短视频文案生成 5 个适合抖音/视频号的中文标题。
要求：
- 每行一个标题，只输出标题本身。
- 标题要贴近文案事实，12 到 28 个中文字符左右。
- 可以用口语化钩子、反差、痛点、结果导向，但不要编造数据、价格、身份、热榜或平台背书。
- 如果原文有可用话题，可以在标题表达里参考其方向，但不要把话题标签直接堆进标题。

原文可能包含的话题：{source_tags}

文案：
{text}
"""
    return call_llm(
        [
            {
                "role": "system",
                "content": "你是短视频标题策划，擅长把内容事实转成抖音信息流里自然、有点击欲但不过度夸张的标题。",
            },
            {"role": "user", "content": prompt},
        ],
        max_tokens=600,
    )


def generate_visual_title_lines(text: str) -> str:
    prompt = f"""请根据下面短视频文案生成适合封面或视频顶部标题的两行短标题。

输出要求：
- 只输出两行文本，不要编号、不要引号、不要解释。
- 第一行 4 到 8 个中文字符，负责抓注意力。
- 第二行 4 到 10 个中文字符，补充价值点或结果。
- 不要出现 #话题 标签。
- 不要编造数据、热榜、平台官方推荐、价格、身份或夸大承诺。
- 尽量口语化、短促、有画面感，适合放在封面上。

文案：
{text}
"""
    content = call_llm(
        [
            {
                "role": "system",
                "content": "你是短视频封面标题策划，擅长把长文案压缩成两行醒目但真实的封面字。",
            },
            {"role": "user", "content": prompt},
        ],
        max_tokens=240,
    )
    lines = normalize_title_lines(content)
    if len(lines) < 2:
        fallback = split_visual_title_fallback(text)
        lines = (lines + fallback)[:2]
    return "\n".join(lines[:2])


def generate_title_topics(text: str) -> dict[str, Any]:
    source_tags = extract_hashtags(text)
    source_tag_text = "、".join("#" + tag for tag in source_tags[:8]) or "无"
    prompt = f"""请基于短视频文案生成一个主标题和 5 到 8 个抖音风格话题标签。

必须只返回 JSON，格式：
{{"title":"...","topics":["#话题1","#话题2"]}}

生成策略：
1. 标题要来自文案内容本身，12 到 28 个中文字符左右，适合抖音信息流第一眼看到。
2. 话题不要乱追“热榜”。如果没有实时平台热度数据，只按内容相关性、垂直领域和目标人群来选。
3. 话题结构建议包含：1 到 2 个大类话题、1 到 3 个垂直细分话题、1 到 2 个场景/人群话题。
4. 如果原文带有相关话题，可保留或改写其中 1 到 3 个；无关或过泛的话题不要硬保留。
5. 不要编造品牌授权、夸大承诺、医疗金融收益、平台官方推荐、实时热榜名次。
6. topics 中每个元素必须以 # 开头，不要有空格。

原文可能包含的话题：{source_tag_text}

文案：
{text}
"""
    content = call_llm(
        [
            {
                "role": "system",
                "content": "你是短视频标题和话题策划，优先保证内容真实、抖音语感自然、话题与内容强相关。",
            },
            {"role": "user", "content": prompt},
        ],
        max_tokens=800,
    )
    data = parse_json_from_text(content)
    title = str(data.get("title") or "").strip()
    topics = data.get("topics") or []
    if isinstance(topics, str):
        topics = re.findall(r"#?[\w\u4e00-\u9fff]+", topics)
    topics = normalize_topics(topics)
    if not topics:
        topics = ["#短视频", "#内容创作", "#知识分享"]
    return {"title": title or content.strip().splitlines()[0], "topics": topics[:8]}


def normalize_title_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        line = re.sub(r"^\s*[\d一二三四五六七八九十]+[\.、:：\)]\s*", "", line)
        line = line.strip(" \t\r\n\"'“”‘’`，。,.!！?？;；:：、")
        if not line or line.startswith("#"):
            continue
        line = re.sub(r"\s+", "", line)
        if line and line not in lines:
            lines.append(line)
    return lines


def split_visual_title_fallback(text: str) -> list[str]:
    cleaned = re.sub(r"#\S+", "", text or "")
    cleaned = re.sub(r"\s+", "", cleaned)
    cleaned = re.sub(r"[，。,.!！?？;；:：、]+", "\n", cleaned)
    parts = [part for part in cleaned.splitlines() if part]
    if not parts:
        return ["重点来了", "马上看懂"]
    first = parts[0][:8] or "重点来了"
    second_source = parts[1] if len(parts) > 1 else parts[0][8:]
    second = second_source[:10] or "马上看懂"
    return [first, second]


def normalize_topics(topics: list[Any]) -> list[str]:
    normalized: list[str] = []
    for topic in topics:
        value = str(topic or "").strip()
        value = re.sub(r"^#+\s*", "", value)
        value = re.sub(r"\s+", "", value)
        value = value.strip(" \t\r\n,，.。!！?？;；:：、")
        if not value:
            continue
        normalized_topic = "#" + value
        if normalized_topic not in normalized:
            normalized.append(normalized_topic)
    return normalized


def parse_json_from_text(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if match:
            return json.loads(match.group(0))
    raise UserFacingError("大模型没有按 JSON 返回标题话题：" + text[:300])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="YanYing content worker")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    load_config()
    logger.info("Starting YanYing content worker on %s:%s", args.host, args.port)
    app.run(host=args.host, port=args.port, threaded=True)


if __name__ == "__main__":
    main()
