import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from . import config, db

# scrypt 参数与客户信息卡项目保持一致，便于同一套口令校验逻辑
_N, _R, _P, _DKLEN = 2 ** 14, 8, 1, 32


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.scrypt(password.encode(), salt=salt.encode(), n=_N, r=_R, p=_P, dklen=_DKLEN)
    return f"scrypt${salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt, hexdigest = stored.split("$", 2)
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    dk = hashlib.scrypt(password.encode(), salt=salt.encode(), n=_N, r=_R, p=_P, dklen=_DKLEN)
    return hmac.compare_digest(dk.hex(), hexdigest)


def ensure_admin() -> tuple[str, str | None] | None:
    """没有管理员就按环境变量建一个。
    返回 (用户名, 随机口令或 None)；None 表示已存在、无需处理。
    随机口令只在创建当场返回一次，用于打印到容器日志。"""
    if db.one("SELECT id FROM admins LIMIT 1"):
        return None
    username = (config.ADMIN_USER or "").strip()
    password = config.ADMIN_PASS or ""
    generated = None
    if not username or not password:
        username = username or "admin"
        generated = password = secrets.token_urlsafe(9)
    db.execute(
        "INSERT INTO admins (username, pass_hash, updated_at) VALUES (?,?,?)",
        (username, hash_password(password), db.now()),
    )
    return username, generated


def create_session(admin_id: int, ip: str) -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(seconds=config.SESSION_TTL)
    expires_at = expires.isoformat(timespec="seconds")
    db.execute("DELETE FROM sessions WHERE expires_at <= ?", (db.now(),))
    db.execute(
        "INSERT INTO sessions (token, admin_id, created_ip, created_at, expires_at) VALUES (?,?,?,?,?)",
        (token, admin_id, ip, db.now(), expires_at),
    )
    return sign(token), expires_at


def sign(token: str) -> str:
    mac = hmac.new(config.secret_salt().encode(), token.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{token}.{mac}"


def admin_from_token(signed: str):
    if not signed or "." not in signed:
        return None
    token, mac = signed.rsplit(".", 1)
    expected = hmac.new(config.secret_salt().encode(), token.encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(mac, expected):
        return None
    row = db.one(
        "SELECT a.id, a.username FROM sessions s JOIN admins a ON a.id = s.admin_id "
        "WHERE s.token = ? AND s.expires_at > ?",
        (token, datetime.now(timezone.utc).isoformat(timespec="seconds")),
    )
    return row


def destroy_session(signed: str) -> None:
    if signed and "." in signed:
        token = signed.rsplit(".", 1)[0]
        db.execute("DELETE FROM sessions WHERE token = ?", (token,))
    db.execute("DELETE FROM sessions WHERE expires_at <= ?",
               (datetime.now(timezone.utc).isoformat(timespec="seconds"),))


def login_allowed(ip: str) -> bool:
    """同一 IP 15 分钟内最多 10 次失败登录，够正常用、不够爆破。"""
    row = db.one("SELECT count AS c, last_at FROM login_failures WHERE ip = ?", (ip,))
    if not row:
        return True
    since = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat(timespec="seconds")
    return row["last_at"] < since or row["c"] < 10


def note_login_failure(ip: str) -> None:
    now = db.now()
    db.execute(
        "INSERT INTO login_failures (ip, count, last_at) VALUES (?,1,?) "
        "ON CONFLICT(ip) DO UPDATE SET count = count + 1, last_at = excluded.last_at",
        (ip, now),
    )


def clear_login_failures(ip: str) -> None:
    db.execute("DELETE FROM login_failures WHERE ip = ?", (ip,))
