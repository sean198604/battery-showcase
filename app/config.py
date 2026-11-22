import os
import secrets
from pathlib import Path

BASE_DIR = Path(os.environ.get("SHOWCASE_DATA_ROOT", "/app")).resolve()

DATA_DIR = Path(os.environ.get("SHOWCASE_DATA_DIR", BASE_DIR / "data"))
STORAGE_DIR = Path(os.environ.get("SHOWCASE_STORAGE_DIR", BASE_DIR / "storage"))
DB_PATH = DATA_DIR / "showcase.db"
UPLOAD_DIR = STORAGE_DIR / "uploads"
THUMB_DIR = STORAGE_DIR / "thumbs"

ADMIN_USER = os.environ.get("SHOWCASE_ADMIN_USER", "")
ADMIN_PASS = os.environ.get("SHOWCASE_ADMIN_PASS", "")

# 会话有效期（秒），默认 30 天，后台登录一次能撑很久
SESSION_TTL = int(os.environ.get("SHOWCASE_SESSION_TTL", 60 * 60 * 24 * 30))

# 前台页面 URL 的基准域名，用于生成二维码。留空则按请求头自动推断
PUBLIC_BASE_URL = os.environ.get("SHOWCASE_PUBLIC_BASE_URL", "").rstrip("/")

MAX_IMAGE_BYTES = int(os.environ.get("SHOWCASE_MAX_IMAGE_BYTES", 15 * 1024 * 1024))
THUMB_MAX_WIDTH = 1280
PREVIEW_MAX_WIDTH = 420

ALLOWED_EXTENSIONS = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

LANGS = [
    ("zh", "中文"),
    ("en", "English"),
    ("es", "Español"),
    ("pt", "Português"),
    ("ru", "Русский"),
    ("ar", "العربية"),
    ("fr", "Français"),
    ("de", "Deutsch"),
    ("ja", "日本語"),
    ("id", "Bahasa Indonesia"),
    ("vi", "Tiếng Việt"),
    ("th", "ไทย"),
]
LANG_NAMES = dict(LANGS)


def ensure_dirs() -> None:
    for d in (DATA_DIR, STORAGE_DIR, UPLOAD_DIR, THUMB_DIR):
        d.mkdir(parents=True, exist_ok=True)


def secret_salt() -> str:
    """会话签名种子。首次启动随机生成并落盘，改数据库不需要重启就能失效旧会话。"""
    marker = DATA_DIR / ".session_seed"
    if marker.exists():
        value = marker.read_text().strip()
        if len(value) >= 32:
            return value
    value = secrets.token_hex(32)
    marker.write_text(value)
    marker.chmod(0o600)
    return value
