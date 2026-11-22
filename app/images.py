import hashlib
import io
import secrets
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from . import config, db

_FORMATS = {
    "jpeg": (".jpg", "image/jpeg"),
    "png": (".png", "image/png"),
    "webp": (".webp", "image/webp"),
    "gif": (".gif", "image/gif"),
}


class ImageRejected(Exception):
    pass


def save_upload(data: bytes, orig_name: str) -> dict:
    if len(data) > config.MAX_IMAGE_BYTES:
        raise ImageRejected(f"图片超过 {config.MAX_IMAGE_BYTES // 1024 // 1024} MB")
    if len(data) < 24:
        raise ImageRejected("文件太小，不像是图片")

    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise ImageRejected("无法识别的图片格式，请用 JPG / PNG / WebP / GIF") from exc

    key = (img.format or "").lower()
    if key not in _FORMATS:
        raise ImageRejected(f"不支持的格式 {img.format or '未知'}，请用 JPG / PNG / WebP / GIF")
    ext, mime = _FORMATS[key]

    token = secrets.token_hex(12)
    (config.UPLOAD_DIR / f"{token}{ext}").write_bytes(data)

    if key != "gif":
        _write_thumbs(ImageOps.exif_transpose(img), token)

    db.execute(
        "INSERT INTO images (token, orig_name, mime, width, height, bytes, sha256, created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (token, _safe_orig_name(orig_name), mime, img.width, img.height, len(data),
         hashlib.sha256(data).hexdigest(), db.now()),
    )
    return db.one("SELECT * FROM images WHERE token = ?", (token,))


def _write_thumbs(img: Image.Image, token: str) -> None:
    """手机页面用压缩后的 WebP，原图只保留用于下载和重新生成。"""
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    for max_w, folder in ((config.THUMB_MAX_WIDTH, "page"), (config.PREVIEW_MAX_WIDTH, "prev")):
        out = img
        if out.width > max_w:
            out = out.resize((max_w, round(out.height * max_w / out.width)), Image.LANCZOS)
        out_dir = config.THUMB_DIR / folder
        out_dir.mkdir(parents=True, exist_ok=True)
        out.save(out_dir / f"{token}.webp", "WEBP", quality=82, method=4)


def _safe_orig_name(name: str) -> str:
    name = Path(name or "").name
    name = "".join(ch for ch in name if ch.isprintable() and ch not in '\\/"|<>:*?')
    return name[:120]


def token_of(image_id: int) -> str | None:
    row = db.one("SELECT token FROM images WHERE id = ?", (image_id,))
    return row["token"] if row else None


def resolve_path(token: str, variant: str):
    """按变体找实际存在的文件；GIF 没有缩略图，回落到原图。"""
    if not _token_ok(token):
        return None, None
    if variant in ("page", "prev"):
        webp = config.THUMB_DIR / variant / f"{token}.webp"
        if webp.exists():
            return webp, "image/webp"
    return _orig_path(token), _orig_mime(token)


def _token_ok(token: str) -> bool:
    return bool(token) and len(token) <= 64 and all(c in "0123456789abcdef" for c in token)


def _orig_path(token: str):
    for candidate in (".jpg", ".png", ".webp", ".gif"):
        p = config.UPLOAD_DIR / f"{token}{candidate}"
        if p.exists():
            return p
    return None


def _orig_mime(token: str) -> str:
    p = _orig_path(token)
    if not p:
        return ""
    return {".jpg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"}[p.suffix]


def in_use(image_id: int) -> bool:
    return bool(
        db.one("SELECT 1 AS x FROM blocks WHERE image_id = ? LIMIT 1", (image_id,))
        or db.one("SELECT 1 AS x FROM pages WHERE cover_image = ? LIMIT 1", (image_id,))
    )


def referenced_ids() -> set[int]:
    rows = db.query("SELECT DISTINCT image_id AS i FROM blocks WHERE image_id IS NOT NULL "
                    "UNION SELECT cover_image AS i FROM pages WHERE cover_image IS NOT NULL")
    return {r["i"] for r in rows if r["i"]}


def orphan_files() -> list[Path]:
    """返回不属于任何记录的文件，供后台清理磁盘。"""
    known = {r["token"] for r in db.query("SELECT token FROM images")}
    stale = []
    for base in (config.UPLOAD_DIR, config.THUMB_DIR / "page", config.THUMB_DIR / "prev"):
        if not base.exists():
            continue
        for f in base.iterdir():
            stem = f.name.split(".")[0]
            if stem not in known:
                stale.append(f)
    return stale


def delete(image_id: int) -> None:
    token = token_of(image_id)
    if not token:
        return
    db.execute("DELETE FROM images WHERE id = ?", (image_id,))
    if in_use(image_id):
        return
    for path in (_orig_path(token),
                 config.THUMB_DIR / "page" / f"{token}.webp",
                 config.THUMB_DIR / "prev" / f"{token}.webp"):
        if path and path.exists():
            path.unlink()


def storage_bytes() -> int:
    total = 0
    for base in (config.UPLOAD_DIR, config.THUMB_DIR):
        if base.exists():
            total += sum(f.stat().st_size for f in base.rglob("*") if f.is_file())
    return total
