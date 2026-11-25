import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from . import config

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS pages (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    slug          TEXT    NOT NULL UNIQUE,
    title         TEXT    NOT NULL DEFAULT '',
    subtitle      TEXT    NOT NULL DEFAULT '',
    lang          TEXT    NOT NULL DEFAULT 'en',
    group_key     TEXT    NOT NULL DEFAULT '',
    sort_order    INTEGER NOT NULL DEFAULT 0,
    status        TEXT    NOT NULL DEFAULT 'draft',
    header_text   TEXT    NOT NULL DEFAULT '',
    footer_text   TEXT    NOT NULL DEFAULT '',
    cover_image   INTEGER REFERENCES images(id) ON DELETE SET NULL,
    images_only   INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT    NOT NULL,
    updated_at    TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pages_group ON pages(group_key, lang, sort_order);
CREATE INDEX IF NOT EXISTS idx_pages_status ON pages(status);

CREATE TABLE IF NOT EXISTS blocks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    page_id    INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    kind       TEXT    NOT NULL,
    position   INTEGER NOT NULL,
    text       TEXT    NOT NULL DEFAULT '',
    image_id   INTEGER REFERENCES images(id) ON DELETE SET NULL,
    caption    TEXT    NOT NULL DEFAULT '',
    data_json  TEXT    NOT NULL DEFAULT '',
    hidden     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_blocks_page ON blocks(page_id, position);

CREATE TABLE IF NOT EXISTS images (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    token      TEXT    NOT NULL UNIQUE,
    orig_name  TEXT    NOT NULL DEFAULT '',
    mime       TEXT    NOT NULL DEFAULT '',
    width      INTEGER NOT NULL DEFAULT 0,
    height     INTEGER NOT NULL DEFAULT 0,
    bytes      INTEGER NOT NULL DEFAULT 0,
    sha256     TEXT    NOT NULL DEFAULT '',
    created_at TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS admins (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    username    TEXT NOT NULL UNIQUE,
    pass_hash   TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    admin_id   INTEGER NOT NULL REFERENCES admins(id) ON DELETE CASCADE,
    created_ip TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS login_failures (
    ip         TEXT PRIMARY KEY,
    count      INTEGER NOT NULL DEFAULT 0,
    last_at    TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(config.DB_PATH), timeout=15, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=15000")
    return conn


@contextmanager
def db():
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def query(sql: str, args: tuple = ()) -> list[dict]:
    with db() as conn:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]


def one(sql: str, args: tuple = ()):
    with db() as conn:
        row = conn.execute(sql, args).fetchone()
        return dict(row) if row else None


def execute(sql: str, args: tuple = ()) -> int:
    with db() as conn:
        cur = conn.execute(sql, args)
        return cur.lastrowid if cur.lastrowid else cur.rowcount


def init() -> None:
    config.ensure_dirs()
    with db() as conn:
        conn.executescript(SCHEMA)
        # 旧库里的 contact_text（页面底部联系方式）已经不再展示，直接删列
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(pages)")}
        if "contact_text" in cols:
            conn.execute("ALTER TABLE pages DROP COLUMN contact_text")
        # 内容块支持"暂时不显示"：保留内容，只是不在页面上渲染
        bcols = {r["name"] for r in conn.execute("PRAGMA table_info(blocks)")}
        if "hidden" not in bcols:
            conn.execute("ALTER TABLE blocks ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0")
        # 整页只看图片：正文里的文字类内容块不渲染，只留图片
        if "images_only" not in cols:
            conn.execute("ALTER TABLE pages ADD COLUMN images_only INTEGER NOT NULL DEFAULT 0")
