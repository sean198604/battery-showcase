import json
import re
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from . import auth, config, db, images, qr, render


@asynccontextmanager
async def lifespan(_app: FastAPI):
    config.ensure_dirs()
    db.init()
    created = auth.ensure_admin()
    if created:
        username, generated = created
        if generated:
            print(f"[showcase] 已创建管理员 {username}，随机初始口令：{generated}")
            print("[showcase] 该口令只打印这一次，请立刻登录后台在“账号”里改掉")
        else:
            print(f"[showcase] 已按环境变量创建管理员 {username}")
    yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)

BLOCK_KINDS = {"text", "heading", "image", "specs", "note", "divider"}
MAX_TEXT = 20000
MAX_CAPTION = 400
MAX_PAGES = 3000
COOKIE = "showcase_session"


# --------------------------------------------------------------------------
# 基础设施
# --------------------------------------------------------------------------

def base_url(request: Request) -> str:
    if config.PUBLIC_BASE_URL:
        return config.PUBLIC_BASE_URL
    scheme = request.headers.get("x-forwarded-proto", "http").split(",")[0].strip() or "http"
    host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    if not host:
        host = request.url.netloc
    return f"{scheme}://{host}"


def page_url(request: Request, slug: str) -> str:
    return f"{base_url(request)}/p/{slug}"


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "")


def current_admin(request: Request):
    return auth.admin_from_token(request.cookies.get(COOKIE, ""))


def require_admin(request: Request) -> dict:
    admin = current_admin(request)
    if not admin:
        raise HTTPException(401, "需要登录")
    return admin


# --------------------------------------------------------------------------
# 数据读写
# --------------------------------------------------------------------------

_PAGE_SQL = (
    "SELECT p.*, i.token AS cover_token FROM pages p "
    "LEFT JOIN images i ON i.id = p.cover_image "
)
_BLOCK_SQL = (
    "SELECT b.*, im.token AS image_token, im.width AS image_w, im.height AS image_h "
    "FROM blocks b LEFT JOIN images im ON im.id = b.image_id "
)


def get_page(where: str, value) -> dict | None:
    return db.one(_PAGE_SQL + f"WHERE {where}", (value,))


def get_blocks(page_id: int) -> list[dict]:
    return db.query(_BLOCK_SQL + "WHERE b.page_id = ? ORDER BY b.position, b.id", (page_id,))


def siblings(page: dict) -> list[dict]:
    if not page.get("group_key"):
        return []
    return db.query(
        "SELECT slug, lang, title FROM pages WHERE group_key = ? AND status = 'published' "
        "ORDER BY lang, sort_order, id",
        (page["group_key"],),
    )


def neighbours(page: dict):
    if not page.get("group_key"):
        return None, None
    rows = db.query(
        "SELECT id, slug, title FROM pages WHERE group_key = ? AND lang = ? AND status = 'published' "
        "ORDER BY sort_order, id",
        (page["group_key"], page["lang"]),
    )
    idx = next((i for i, r in enumerate(rows) if r["id"] == page["id"]), None)
    if idx is None:
        return None, None
    prev_row = rows[idx - 1] if idx > 0 else None
    next_row = rows[idx + 1] if idx + 1 < len(rows) else None
    return prev_row, next_row


def make_slug(title: str, lang: str) -> str:
    stem = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")[:40].strip("-")
    if not stem:
        stem = "p" + secrets.token_hex(3)
    if lang and lang != "en":
        stem = f"{stem}-{lang}" if len(stem) < 34 else f"{stem[:24]}-{lang}"
    candidate, taken = stem, {
        r["slug"] for r in db.query("SELECT slug FROM pages WHERE slug LIKE ?", (f"{stem}%",))
    }
    if candidate not in taken:
        return candidate
    while True:
        candidate = f"{stem}-{secrets.token_hex(2)}"
        if candidate not in taken:
            return candidate


def clean_blocks(raw) -> list[dict]:
    if not isinstance(raw, list):
        raise HTTPException(400, "blocks 必须是列表")
    if len(raw) > 200:
        raise HTTPException(400, "单页最多 200 个内容块")
    out = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        if kind not in BLOCK_KINDS:
            raise HTTPException(400, f"未知的内容类型 {kind}")
        text = str(item.get("text") or "")[:MAX_TEXT]
        caption = str(item.get("caption") or "")[:MAX_CAPTION]
        data_json = ""
        if kind == "specs":
            pairs = item.get("pairs")
            if isinstance(pairs, list):
                pairs = [{"k": str(p.get("k", ""))[:80], "v": str(p.get("v", ""))[:400]}
                         for p in pairs if isinstance(p, dict) and str(p.get("k") or "").strip()][:120]
                data_json = json.dumps(pairs, ensure_ascii=False)
            elif item.get("data_json"):
                data_json = str(item["data_json"])[:20000]
        image_id = item.get("image_id")
        if kind == "image":
            if not image_id:
                raise HTTPException(400, "图片块必须带 image_id")
            try:
                image_id = int(image_id)
            except (TypeError, ValueError):
                raise HTTPException(400, "图片编号无效") from None
            if not db.one("SELECT id FROM images WHERE id = ?", (image_id,)):
                raise HTTPException(400, "图片不存在，请重新上传")
        out.append({"kind": kind, "position": index, "text": text,
                    "caption": caption, "image_id": _as_int(image_id),
                    "data_json": data_json})
    return out


def _as_int(value):
    try:
        return int(value) if value else None
    except (TypeError, ValueError):
        return None


def page_meta(body: dict, existing: dict | None = None) -> dict:
    def field(name, default="", limit=300):
        value = body.get(name, existing.get(name, default) if existing else default)
        return str(value or "")[:limit]

    title = field("title", "", 200).strip()
    if not title:
        raise HTTPException(400, "标题不能为空")
    lang = field("lang", "en", 8).strip().lower() or "en"
    cover = body.get("cover_image", existing.get("cover_image") if existing else None)
    sort = body.get("sort_order", existing.get("sort_order", 0) if existing else 0)
    try:
        sort = int(sort)
    except (TypeError, ValueError):
        sort = 0
    return {
        "title": title,
        "subtitle": field("subtitle", "", 300).strip(),
        "lang": lang,
        "group_key": field("group_key", "", 60).strip(),
        "sort_order": sort,
        "header_text": field("header_text", "", 120).strip(),
        "footer_text": field("footer_text", "", 1000),
        "cover_image": _as_int(cover),
    }


# --------------------------------------------------------------------------
# 前台
# --------------------------------------------------------------------------

@app.get("/api/health")
def health():
    row = db.one("SELECT COUNT(*) AS pages FROM pages WHERE status='published'")
    return {"ok": True, "published": row["pages"] if row else 0}


@app.get("/p/{slug}", response_class=HTMLResponse)
def show_page(slug: str, request: Request):
    page = get_page("p.slug = ? AND p.status = 'published'", slug)
    if not page:
        raise HTTPException(404, "页面不存在或未发布")
    return _render_page(page, request)


@app.get("/preview/{slug}", response_class=HTMLResponse)
def preview_page(slug: str, request: Request):
    """草稿预览：只有登录后台的浏览器能打开，用于发布前确认排版。"""
    require_admin(request)
    page = get_page("p.slug = ?", slug)
    if not page:
        raise HTTPException(404, "页面不存在")
    return _render_page(page, request, draft=page["status"] != "published")


def _render_page(page: dict, request: Request, draft: bool = False) -> str:
    blocks = get_blocks(page["id"])
    return render.page_html(page, blocks, siblings(page), *neighbours(page),
                            draft_badge=draft,
                            accept_language=request.headers.get("accept-language", ""))


@app.get("/qr/{slug}.png")
def page_qr(slug: str, request: Request, scale: int = 10):
    if not get_page("p.slug = ? AND p.status = 'published'", slug):
        raise HTTPException(404)
    data = qr.png(page_url(request, slug), scale)
    return Response(data, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=300"})


@app.get("/qr/{slug}.svg")
def page_qr_svg(slug: str, request: Request):
    if not get_page("p.slug = ? AND p.status = 'published'", slug):
        raise HTTPException(404)
    return Response(qr.svg(page_url(request, slug)), media_type="image/svg+xml")


@app.get("/qr/{slug}/print", response_class=HTMLResponse)
def page_qr_print(slug: str, request: Request):
    """A4 打印卡：标题 + 二维码，可直接打印给客人贴在样品上。"""
    page = get_page("p.slug = ? AND p.status = 'published'", slug)
    if not page:
        raise HTTPException(404)
    url = page_url(request, slug)
    data_uri = "data:image/png;base64," + _b64(qr.png(url, 24))
    title = render.esc(page["title"])
    sub = render.esc(page.get("subtitle") or "")
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{title}</title>
<style>
@page{{size:A4;margin:14mm}}
body{{margin:0;font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
 display:flex;flex-wrap:wrap;gap:12mm}}
.card{{width:84mm;padding:6mm;border:1px dashed #bbb;text-align:center;page-break-inside:avoid}}
img{{width:72mm;height:72mm}}
h2{{font-size:15px;margin:3mm 0 1mm;line-height:1.3}}
p{{font-size:10px;color:#555;margin:1mm 0 3mm;word-break:break-all}}
@media print{{.card{{border:0}}.noprint{{display:none}}}}
button{{padding:8px 16px;font-size:14px;cursor:pointer}}
.wrap{{width:100%;padding:10px}}
</style></head><body>
<div class="wrap noprint"><button onclick="print()">打印</button>
&nbsp;共 4 张相同卡片，裁开即可分别贴在样品、彩盒、包装箱和资料册上。</div>
<div class="wrap">
{''.join(f'<div class="card"><img src="{data_uri}" alt="QR"><h2>{title}</h2>'
         f'<p>{sub}</p><p>{render.esc(url)}</p></div>' for _ in range(4))}
</div></body></html>"""


def _b64(data: bytes) -> str:
    import base64
    return base64.b64encode(data).decode()


@app.get("/img/{token}/{variant}")
def serve_image(token: str, variant: str = "page"):
    path, mime = images.resolve_path(token, variant if variant in ("page", "prev", "orig") else "page")
    if not path or not path.exists():
        raise HTTPException(404)
    from fastapi.responses import FileResponse
    return FileResponse(path, media_type=mime or "application/octet-stream",
                        headers={"Cache-Control": "public, max-age=2592000, immutable"})


# --------------------------------------------------------------------------
# 后台：登录
# --------------------------------------------------------------------------

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@app.get("/admin", response_class=HTMLResponse)
@app.get("/admin/", response_class=HTMLResponse)
def admin_index():
    return (STATIC_DIR / "admin.html").read_text(encoding="utf-8")


@app.post("/admin/api/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    ip = client_ip(request)
    if not auth.login_allowed(ip):
        raise HTTPException(429, "失败次数过多，请 15 分钟后再试")
    admin = db.one("SELECT * FROM admins WHERE username = ?", (username.strip(),))
    if not admin or not auth.verify_password(password, admin["pass_hash"]):
        auth.note_login_failure(ip)
        raise HTTPException(401, "用户名或密码不正确")
    auth.clear_login_failures(ip)
    signed, expires_at = auth.create_session(admin["id"], ip)
    resp = JSONResponse({"ok": True, "username": admin["username"]})
    resp.set_cookie(COOKIE, signed, max_age=config.SESSION_TTL, expires=_epoch(expires_at),
                    httponly=True, samesite="lax", secure=request.url.scheme == "https"
                    or request.headers.get("x-forwarded-proto") == "https")
    return resp


def _epoch(iso: str) -> int:
    from datetime import datetime
    try:
        return int(datetime.fromisoformat(iso).timestamp())
    except ValueError:
        return 0


@app.post("/admin/api/logout")
def logout(request: Request):
    auth.destroy_session(request.cookies.get(COOKIE, ""))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE)
    return resp


@app.get("/admin/api/session")
def session(request: Request):
    admin = current_admin(request)
    if not admin:
        raise HTTPException(401)
    return {"username": admin["username"]}


@app.post("/admin/api/password")
def change_password(request: Request, body: dict):
    admin = require_admin(request)
    old, new = str(body.get("old") or ""), str(body.get("new") or "")
    row = db.one("SELECT * FROM admins WHERE id = ?", (admin["id"],))
    if not row or not auth.verify_password(old, row["pass_hash"]):
        raise HTTPException(400, "原密码不正确")
    if len(new) < 8:
        raise HTTPException(400, "新密码至少 8 位")
    db.execute("UPDATE admins SET pass_hash = ?, updated_at = ? WHERE id = ?",
               (auth.hash_password(new), db.now(), admin["id"]))
    db.execute("DELETE FROM sessions WHERE admin_id = ?", (admin["id"],))
    resp = JSONResponse({"ok": True, "note": "已生效，其他设备的登录状态全部失效"})
    signed, expires_at = auth.create_session(admin["id"], client_ip(request))
    resp.set_cookie(COOKIE, signed, max_age=config.SESSION_TTL, expires=_epoch(expires_at),
                    httponly=True, samesite="lax")
    return resp


# --------------------------------------------------------------------------
# 后台：页面
# --------------------------------------------------------------------------

@app.get("/admin/api/pages")
def list_pages(request: Request, q: str = ""):
    require_admin(request)
    sql = ("SELECT p.id, p.slug, p.title, p.subtitle, p.lang, p.group_key, p.sort_order, p.status, "
           "p.updated_at, (SELECT COUNT(*) FROM blocks b WHERE b.page_id = p.id) AS block_count, "
           "i.token AS cover_token "
           "FROM pages p LEFT JOIN images i ON i.id = p.cover_image ")
    args: tuple = ()
    if q.strip():
        sql += "WHERE p.title LIKE ? OR p.slug LIKE ? OR p.group_key LIKE ? "
        like = f"%{q.strip()}%"
        args = (like, like, like)
    sql += "ORDER BY p.updated_at DESC LIMIT 500"
    return {"pages": db.query(sql, args)}


@app.post("/admin/api/pages")
def create_page(request: Request, body: dict):
    require_admin(request)
    if db.one("SELECT COUNT(*) AS c FROM pages")["c"] >= MAX_PAGES:
        raise HTTPException(400, f"页面数已达上限 {MAX_PAGES}")
    meta = page_meta(body)
    slug = body.get("slug") or make_slug(meta["title"], meta["lang"])
    slug = _unique_slug(str(slug))
    # 分组决定页间是否互相出现语言切换：不填就自成一组，
    # 这样"复制为新语言"天然落在同一组里，不必让操作员理解分组概念
    group = meta["group_key"] or slug
    now = db.now()
    page_id = db.execute(
        "INSERT INTO pages (slug, status, created_at, updated_at, title, subtitle, lang, group_key,"
        " sort_order, header_text, footer_text, cover_image) "
        "VALUES (?, 'draft', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (slug, now, now, meta["title"], meta["subtitle"], meta["lang"], group,
         meta["sort_order"], meta["header_text"], meta["footer_text"],
         meta["cover_image"]),
    )
    return get_page("p.id = ?", page_id)


def _unique_slug(raw: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", str(raw).lower()).strip("-")[:48]
    if not slug:
        raise HTTPException(400, "网址标识只能用英文字母、数字和连字符")
    if db.one("SELECT id FROM pages WHERE slug = ?", (slug,)):
        raise HTTPException(409, f"标识 {slug} 已被占用")
    return slug


@app.get("/admin/api/pages/{page_id}")
def read_page(request: Request, page_id: int):
    require_admin(request)
    page = get_page("p.id = ?", page_id)
    if not page:
        raise HTTPException(404)
    return {"page": page, "blocks": get_blocks(page_id)}


@app.put("/admin/api/pages/{page_id}")
def update_page(request: Request, page_id: int, body: dict):
    require_admin(request)
    page = get_page("p.id = ?", page_id)
    if not page:
        raise HTTPException(404)
    meta = page_meta(body, page)
    slug = body.get("slug")
    if slug and slug != page["slug"]:
        slug = _unique_slug(slug)
    else:
        slug = page["slug"]
    db.execute(
        "UPDATE pages SET slug=?, title=?, subtitle=?, lang=?, group_key=?, sort_order=?,"
        " header_text=?, footer_text=?, cover_image=?, updated_at=? WHERE id=?",
        (slug, meta["title"], meta["subtitle"], meta["lang"],
         meta["group_key"] or page["group_key"] or slug, meta["sort_order"],
         meta["header_text"], meta["footer_text"], meta["cover_image"],
         db.now(), page_id),
    )
    return get_page("p.id = ?", page_id)


@app.put("/admin/api/pages/{page_id}/blocks")
def update_blocks(request: Request, page_id: int, body: dict):
    require_admin(request)
    if not get_page("p.id = ?", page_id):
        raise HTTPException(404)
    blocks = clean_blocks(body.get("blocks"))
    with db.db() as conn:
        conn.execute("DELETE FROM blocks WHERE page_id = ?", (page_id,))
        conn.executemany(
            "INSERT INTO blocks (page_id, kind, position, text, image_id, caption, data_json)"
            " VALUES (?,?,?,?,?,?,?)",
            [(page_id, b["kind"], b["position"], b["text"], b["image_id"], b["caption"], b["data_json"])
             for b in blocks],
        )
        conn.execute("UPDATE pages SET updated_at = ? WHERE id = ?", (db.now(), page_id))
    return {"ok": True, "count": len(blocks)}


@app.post("/admin/api/pages/{page_id}/status")
def set_status(request: Request, page_id: int, body: dict):
    require_admin(request)
    page = get_page("p.id = ?", page_id)
    if not page:
        raise HTTPException(404)
    status = "published" if body.get("published") else "draft"
    db.execute("UPDATE pages SET status = ?, updated_at = ? WHERE id = ?", (status, db.now(), page_id))
    return get_page("p.id = ?", page_id)


@app.post("/admin/api/pages/{page_id}/duplicate")
def duplicate_page(request: Request, page_id: int, body: dict):
    """复制整页，用于快速做多语言版本或同类产品。图片记录共享，不重复占空间。"""
    require_admin(request)
    source = get_page("p.id = ?", page_id)
    if not source:
        raise HTTPException(404)
    lang = str(body.get("lang") or source["lang"])[:8].lower()
    slug = _unique_slug(str(body.get("slug") or f"{source['slug']}-{lang}"))
    now = db.now()
    new_id = db.execute(
        "INSERT INTO pages (slug, status, created_at, updated_at, title, subtitle, lang, group_key,"
        " sort_order, header_text, footer_text, cover_image) "
        "VALUES (?, 'draft', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (slug, now, now, body.get("title") or source["title"], source["subtitle"], lang,
         body.get("group_key") or source["group_key"], source["sort_order"], source["header_text"],
         source["footer_text"], source["cover_image"]),
    )
    with db.db() as conn:
        conn.executemany(
            "INSERT INTO blocks (page_id, kind, position, text, image_id, caption, data_json)"
            " SELECT ?, kind, position, text, image_id, caption, data_json FROM blocks WHERE page_id = ?",
            [(new_id, page_id)],
        )
    return get_page("p.id = ?", new_id)


@app.delete("/admin/api/pages/{page_id}")
def delete_page(request: Request, page_id: int):
    require_admin(request)
    db.execute("DELETE FROM pages WHERE id = ?", (page_id,))
    return {"ok": True}


# --------------------------------------------------------------------------
# 后台：图片
# --------------------------------------------------------------------------

@app.get("/admin/api/images")
def list_images(request: Request):
    require_admin(request)
    rows = db.query(
        "SELECT id, token, orig_name, width, height, bytes, created_at,"
        " (SELECT COUNT(*) FROM blocks b WHERE b.image_id = images.id) AS uses,"
        " (SELECT COUNT(*) FROM pages p WHERE p.cover_image = images.id) AS cover_uses"
        " FROM images ORDER BY id DESC LIMIT 2000"
    )
    return {"images": rows, "storage_bytes": images.storage_bytes()}


@app.post("/admin/api/images")
async def upload_image(request: Request, file: UploadFile = File(...)):
    require_admin(request)
    data = await file.read(config.MAX_IMAGE_BYTES + 1)
    try:
        row = images.save_upload(data, file.filename or "")
    except images.ImageRejected as exc:
        raise HTTPException(400, str(exc)) from exc
    return row


@app.delete("/admin/api/images/{image_id}")
def remove_image(request: Request, image_id: int):
    require_admin(request)
    if images.in_use(image_id):
        raise HTTPException(400, "这张图还在页面里使用，先从页面移除再删除")
    images.delete(image_id)
    return {"ok": True}


@app.get("/admin/api/storage")
def storage_report(request: Request):
    require_admin(request)
    stale = images.orphan_files()
    return {"bytes": images.storage_bytes(),
            "orphan_count": len(stale),
            "orphan_bytes": sum(f.stat().st_size for f in stale)}


# --------------------------------------------------------------------------
# 兜底
# --------------------------------------------------------------------------

@app.get("/")
def index():
    return RedirectResponse("/admin/")


_NOT_FOUND_HTML = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>页面不存在</title><style>body{margin:0;font-family:-apple-system,"PingFang SC",
"Microsoft YaHei",sans-serif;background:#f4f6f8;color:#33404d;display:flex;
min-height:100vh;align-items:center;justify-content:center;text-align:center}
div{padding:24px}h1{font-size:20px;margin:0 0 8px}p{margin:0;font-size:15px;color:#6b7783}
a{color:#2b7fd4}</style></head><body><div>
<h1>这个展示页打不开了</h1>
<p>链接可能已过期，或页面被撤下。请联系业务员获取新的二维码。</p>
</div></body></html>"""


_NO_STORE = {"Cache-Control": "no-store"}


@app.exception_handler(404)
def not_found(request: Request, exc):
    # 错误页必须禁止缓存：Cloudflare 会照源站头缓存 5 分钟，
    # 否则页面刚发布时，草稿期产生的 404 还会继续挡住客人
    if request.url.path.startswith(("/admin", "/api")):
        return JSONResponse({"detail": "不存在"}, status_code=404, headers=_NO_STORE)
    return HTMLResponse(_NOT_FOUND_HTML, status_code=404, headers=_NO_STORE)


@app.exception_handler(403)
def forbidden(request: Request, exc):
    return JSONResponse({"detail": "没有权限"}, status_code=403, headers=_NO_STORE)


@app.exception_handler(Exception)
def unhandled(request: Request, exc):
    # 只回 500，不把异常细节透给客人
    print(f"[showcase] 未处理异常 {request.method} {request.url.path}: {exc!r}")
    return JSONResponse({"detail": "服务暂时有问题，请稍后再试"}, status_code=500, headers=_NO_STORE)
