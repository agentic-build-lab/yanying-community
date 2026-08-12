import base64
import binascii
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock

from pydantic import BaseModel, Field

PROFILE_KIND_PATTERN = re.compile(r"^[a-z_]{2,32}$")
PROFILE_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_.:@-]{1,160}$")
DATA_URL_PATTERN = re.compile(r"^data:(image/(?:png|jpeg|webp));base64,([A-Za-z0-9+/=\r\n]+)$")
IMAGE_EXTENSIONS = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}


class UiProfileUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=80)
    image_url: str | None = Field(default=None, max_length=2000)


class UiImageUpload(BaseModel):
    kind: str
    key: str
    data_url: str


class UiProfileStore:
    def __init__(self, storage_path: Path, media_root: Path) -> None:
        self._storage_path = storage_path
        self._media_root = media_root
        self._lock = RLock()
        self._profiles = self._load_profiles()

    def list_profiles(self) -> dict[str, dict[str, dict[str, str]]]:
        with self._lock:
            return json.loads(json.dumps(self._profiles, ensure_ascii=False))

    def update_profile(self, kind: str, key: str, update: UiProfileUpdate) -> dict[str, str]:
        self._validate_identity(kind, key)
        with self._lock:
            profile = self._profiles.setdefault(kind, {}).setdefault(key, {})
            if update.display_name is not None:
                display_name = update.display_name.strip()
                if display_name:
                    profile["display_name"] = display_name
                else:
                    profile.pop("display_name", None)
            if update.image_url is not None:
                image_url = update.image_url.strip()
                if image_url:
                    profile["image_url"] = image_url
                else:
                    profile.pop("image_url", None)
            profile["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._persist()
            return dict(profile)

    def save_image(self, payload: UiImageUpload) -> str:
        self._validate_identity(payload.kind, payload.key)
        match = DATA_URL_PATTERN.fullmatch(payload.data_url.strip())
        if not match:
            raise ValueError("仅支持 PNG、JPEG 或 WebP 图片。")
        try:
            image_bytes = base64.b64decode(match.group(2), validate=True)
        except binascii.Error as exc:
            raise ValueError("图片数据无效。") from exc
        if not image_bytes or len(image_bytes) > 5 * 1024 * 1024:
            raise ValueError("图片大小必须在 5 MB 以内。")
        extension = IMAGE_EXTENSIONS[match.group(1)]
        safe_key = re.sub(r"[^A-Za-z0-9_.-]", "_", payload.key)[:80]
        relative_path = Path("ui_assets") / payload.kind / f"{safe_key}{extension}"
        output_path = self._media_root / relative_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = output_path.with_suffix(f"{output_path.suffix}.tmp")
        temporary_path.write_bytes(image_bytes)
        temporary_path.replace(output_path)
        return f"/media/{relative_path.as_posix()}"

    def _load_profiles(self) -> dict[str, dict[str, dict[str, str]]]:
        if not self._storage_path.is_file():
            return {}
        try:
            payload = json.loads(self._storage_path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _persist(self) -> None:
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self._storage_path.with_suffix(f"{self._storage_path.suffix}.tmp")
        temporary_path.write_text(
            json.dumps(self._profiles, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary_path.replace(self._storage_path)

    @staticmethod
    def _validate_identity(kind: str, key: str) -> None:
        if not PROFILE_KIND_PATTERN.fullmatch(kind) or not PROFILE_KEY_PATTERN.fullmatch(key):
            raise ValueError("资料类型或标识不合法。")
