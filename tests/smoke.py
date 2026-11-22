"""端到端冒烟测试：对一个跑起来的实例走一遍真实业务流程。

用法（容器内需有本文件）：
    SHOWCASE_TEST_PASS=你的口令 python tests/smoke.py [http://127.0.0.1:7023]

只创建带 smoke- 前缀的测试页，结束后自动删除；跑完应该全部 PASS。
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:7023").rstrip("/")
USER = os.environ.get("SHOWCASE_TEST_USER", "admin")
PW = os.environ.get("SHOWCASE_TEST_PASS", "")
_cookie = ""
_heads = {}
_failed = []


def call(path, data=None, ctype=None, method=None):
    req = urllib.request.Request(BASE + path, data=data,
                                 method=method or ("POST" if data is not None else "GET"))
    # 手机浏览器 UA：套 Cloudflare 的实例会按指纹拦掉 Python-urllib 默认头
    req.add_header("User-Agent",
                   "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
                   "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1")
    if ctype:
        req.add_header("Content-Type", ctype)
    if _cookie:
        req.add_header("Cookie", _cookie)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read()
            sc = r.headers.get("Set-Cookie")
            if sc:
                globals()["_cookie"] = sc.split(";")[0]
            _heads[path] = r.headers
            return r.status, body
    except urllib.error.HTTPError as e:
        _heads[path] = e.headers
        return e.code, e.read()


def head(path, **kw):
    """返回该路径最后一次响应的响应头。"""
    call(path, **kw)
    return _heads.get(path, {})


def jget(path, **kw):
    status, body = call(path, **kw)
    try:
        parsed = json.loads(body)
    except ValueError:
        parsed = body[:200]
    return status, parsed


def multipart(filename, field="file"):
    boundary = "smokeboundary" + uuid.uuid4().hex
    head = (f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; '
            f'filename="{os.path.basename(filename)}"\r\nContent-Type: image/jpeg\r\n\r\n').encode()
    tail = f"\r\n--{boundary}--\r\n".encode()
    with open(filename, "rb") as fh:
        return head + fh.read() + tail, f"multipart/form-data; boundary={boundary}"


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  {detail}" if detail else ""))
    if not ok:
        _failed.append(name)


def form(fields):
    body = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in fields.items())
    return body.encode(), "application/x-www-form-urlencoded"


print(f"目标 {BASE}")
if not PW:
    sys.exit("缺少 SHOWCASE_TEST_PASS 环境变量（后台登录口令）")

# 1. 鉴权边界
st, _ = jget("/admin/api/pages")
check("未登录访问后台返回 401", st == 401, f"实际 {st}")
data, ct = form({"username": USER, "password": "绝不对的口令"})
st, _ = call("/admin/api/login", data=data, ctype=ct)
check("错误口令登录返回 401", st == 401, f"实际 {st}")
data, ct = form({"username": USER, "password": PW})
st, body = call("/admin/api/login", data=data, ctype=ct)
check("正确口令登录成功", st == 200, f"实际 {st} {body[:120]}")
if st != 200:
    sys.exit("无法登录，后续用例跳过")

# 2. 图片上传（自己造一张大图，顺带验证缩放链路）
big = os.environ.get("SHOWCASE_TEST_IMAGE", "/tmp/smoke-big.jpg")
try:
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (2000, 1200), (236, 240, 244))
    d = ImageDraw.Draw(im)
    d.rectangle([100, 100, 1900, 1100], fill=(30, 90, 150))
    im.save(big, quality=88)
except Exception as exc:  # 没有 Pillow 时退回用已存在的文件
    print(f"（生成测试图片失败：{exc}）")
if os.path.exists(big):
    body, ct = multipart(big)
    st, img = jget("/admin/api/images", data=body, ctype=ct)
    check("上传真实图片", st == 200 and img.get("token"), f"实际 {st} {str(img)[:160]}")
    check("上传后记下真实尺寸", isinstance(img, dict) and img.get("width") == 2000
          and img.get("height") == 1200, f"实际 {str(img)[:120]}")
    image_id = img.get("id") if isinstance(img, dict) else None
else:
    check("上传真实图片", False, f"测试图片 {big} 不存在")
    image_id = None

bad = b"this is definitely not an image, just text" * 3
boundary = "smokebad"
body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="bad.jpg"\r\n'
        f'Content-Type: image/jpeg\r\n\r\n').encode() + bad + f"\r\n--{boundary}--\r\n".encode()
st, out = jget("/admin/api/images", data=body, ctype=f"multipart/form-data; boundary={boundary}")
check("伪装的图片被拒收", st == 400, f"实际 {st} {str(out)[:120]}")

# 3. 建页 + 存正文
tag = uuid.uuid4().hex[:6]
st, page = jget("/admin/api/pages", data=json.dumps({
    "title": f"SMOKE R6P {tag}", "lang": "en", "subtitle": "Zinc Carbon Dry Cell",
    "group_key": f"smoke-{tag}", "header_text": "Carbon Zn/MnO2 Battery", "sort_order": 1,
}).encode(), ctype="application/json")
check("新建展示页（草稿）", st == 200 and page.get("id"), f"实际 {st} {str(page)[:160]}")
pid, slug = page["id"], page["slug"]

blocks = [
    {"kind": "text", "text": "## Product Features\n- Long shelf life **4 years**\n- Leak-proof seal\n"
                             "\n1. First step\n2. Second step\n\n<img src=x onerror=alert(1)>"},
    {"kind": "specs", "pairs": [{"k": "IEC name", "v": "R6P"}, {"k": "Size", "v": "AA / LR6"},
                               {"k": "Nominal voltage", "v": "1.5V"}]},
    {"kind": "note", "text": "Values are typical, not guaranteed."},
    {"kind": "divider", "text": ""},
]
if image_id:
    blocks.insert(1, {"kind": "image", "image_id": image_id, "caption": "Real photo <script>x</script>"})
st, out = jget(f"/admin/api/pages/{pid}/blocks", method="PUT",
               data=json.dumps({"blocks": blocks}).encode(), ctype="application/json")
check("保存正文内容块", st == 200 and out.get("count") == len(blocks), f"实际 {st} {str(out)[:120]}")

st, out = jget(f"/admin/api/pages/{pid}/blocks", method="PUT",
               data=json.dumps({"blocks": [{"kind": "image", "image_id": 999999}]}).encode(),
               ctype="application/json")
check("引用不存在的图片被拒", st == 400, f"实际 {st}")
st, out = jget(f"/admin/api/pages/{pid}/blocks", method="PUT",
               data=json.dumps({"blocks": [{"kind": "image", "image_id": "abc"}]}).encode(),
               ctype="application/json")
check("图片编号是乱码时返回 400 而不是 500", st == 400, f"实际 {st} {str(out)[:100]}")
st, out = jget(f"/admin/api/pages/{pid}/blocks", method="PUT",
               data=json.dumps({"blocks": [{"kind": "evil_html"}]}).encode(), ctype="application/json")
check("未知内容类型被拒", st == 400, f"实际 {st}")

# 4. 草稿阶段：前台访问不到，后台预览可以
st, body = call(f"/p/{slug}")
check("草稿页对客人不可见（404）", st == 404, f"实际 {st}")
st, body = call(f"/preview/{slug}")
check("后台预览草稿可用", st == 200 and b"Product Features" in body, f"实际 {st}")
check("正文里的 HTML 标签被转义", b"<img src=x" not in body and b"&lt;img" in body)
if image_id:
    check("图注里的 HTML 被转义", b"<script>x</script>" not in body and b"&lt;script&gt;" in body)
st, _ = call(f"/qr/{slug}.png")
check("草稿没有二维码", st == 404, f"实际 {st}")
# Cloudflare 会把 .png 按源站头缓存，草稿期的 404 一旦被缓存，发布后还要挡几分钟
check("二维码 404 带 no-store", "no-store" in head(f"/qr/{slug}.png").get("Cache-Control", ""))
check("页面 404 带 no-store", "no-store" in head("/p/smoke-does-not-exist").get("Cache-Control", ""))
check("SVG 404 带 no-store", "no-store" in head(f"/qr/{slug}.svg").get("Cache-Control", ""))

# 5. 发布后一切对外可见
st, out = jget(f"/admin/api/pages/{pid}/status", data=json.dumps({"published": True}).encode(),
               ctype="application/json")
check("发布页面", st == 200 and out.get("status") == "published", f"实际 {st}")
st, body = call(f"/p/{slug}")
check("发布后前台 200", st == 200, f"实际 {st}")
check("正文排版成标题+列表", b"<h3>" in body and b"<li>Long shelf life" in body and b"<strong>" in body)
check("参数表渲染", b"<table" in body and b"Nominal voltage" in body)
if image_id:
    check("图片以压缩变体输出", b"/img/" in body and b"/page" in body)
st, body = call(f"/p/{slug}", method="GET")
check("页面声明手机 viewport", b'name="viewport"' in body)

st, body = call(f"/qr/{slug}.png?scale=12")
check("二维码 PNG 生成", st == 200 and body[:8] == b"\x89PNG\r\n\x1a\n", f"实际 {st} {body[:8]!r}")
st, body = call(f"/qr/{slug}.svg")
check("二维码 SVG 生成", st == 200 and b"<svg" in body, f"实际 {st}")
st, body = call(f"/qr/{slug}/print")
check("打印卡片页生成", st == 200 and b"qrcode" not in body and body.count(b"class=\"card\"") == 4,
      f"实际 {st}")
st, imgs = jget("/admin/api/images")
token = next((i["token"] for i in imgs["images"] if i["id"] == image_id), None) if image_id else None
if token:
    st, body = call(f"/img/{token}/page")
    check("手机压缩图可访问", st == 200 and body[:4] == b"RIFF", f"实际 {st} {body[:4]!r}")
    st, body = call(f"/img/{'0' * 24}/page")
    check("非法图片 token 返回 404", st == 404, f"实际 {st}")

# 参数表也可以直接写成 "项目: 数值" 的纯文本，服务端要能认
st, out = jget(f"/admin/api/pages/{pid}/blocks", method="PUT",
               data=json.dumps({"blocks": [{"kind": "specs",
                                            "text": "Voltage: 1.5V\n容量=650mAh\nSize | AA"}]}).encode(),
               ctype="application/json")
st, body = call(f"/p/{slug}")
check("纯文本参数表也能排版成表格", st == 200 and b"Voltage" in body and "650mAh".encode() in body
      and b"<td>AA</td>" in body, f"实际 {st}")
st, out = jget(f"/admin/api/pages/{pid}/blocks", method="PUT",
               data=json.dumps({"blocks": blocks}).encode(), ctype="application/json")
check("恢复原来的内容块", st == 200 and out.get("count") == len(blocks), f"实际 {st}")

# 6. 多语言复制
st, copy = jget(f"/admin/api/pages/{pid}/duplicate",
                data=json.dumps({"lang": "es", "title": f"SMOKE Pila R6P {tag}"}).encode(),
                ctype="application/json")
check("复制成另一语言版本", st == 200 and copy.get("lang") == "es" and copy.get("status") == "draft",
      f"实际 {st} {str(copy)[:160]}")
cid = copy["id"]
st, out = jget(f"/admin/api/pages/{cid}")
check("复制带来同样多的内容块", st == 200 and len(out.get("blocks", [])) == len(blocks),
      f"实际 {st} 块数 {len(out.get('blocks', []))}")
check("复制的内容块文字一致",
      any(b["kind"] == "specs" for b in out.get("blocks", []))
      and any("Product Features" in b["text"] for b in out.get("blocks", [])))

jget(f"/admin/api/pages/{cid}/status", data=json.dumps({"published": True}).encode(), ctype="application/json")
st, body = call(f"/p/{slug}")
check("同组页面出多语言切换", st == 200 and b'class="langs"' in body, f"实际 {st}")

# 6b. 不填分组标识：应自成一组，复制后仍能互相切换，保存也不该把分组清空
st, auto = jget("/admin/api/pages", data=json.dumps({"title": f"SMOKE Auto {tag}"}).encode(),
                ctype="application/json")
check("未填分组时以网址标识自成一组",
      st == 200 and auto.get("group_key") == auto.get("slug"), f"实际 {str(auto)[:120]}")
st, auto2 = jget(f"/admin/api/pages/{auto['id']}/duplicate",
                 data=json.dumps({"lang": "de", "title": f"SMOKE Auto DE {tag}"}).encode(),
                 ctype="application/json")
jget(f"/admin/api/pages/{auto['id']}/status", data=json.dumps({"published": True}).encode(),
     ctype="application/json")
jget(f"/admin/api/pages/{auto2['id']}/status", data=json.dumps({"published": True}).encode(),
     ctype="application/json")
jget(f"/admin/api/pages/{auto['id']}", data=json.dumps({"subtitle": "touched"}).encode(),
     ctype="application/json", method="PUT")
st, again = jget(f"/admin/api/pages/{auto['id']}")
check("保存时不带分组字段不会清空分组",
      st == 200 and again["page"].get("group_key") == auto["slug"],
      f"实际 {again['page'].get('group_key')!r}")
st, body = call(f"/p/{auto2['slug']}")
check("自动分组的复制页也出语言切换", st == 200 and b'class="langs"' in body, f"实际 {st}")
jget(f"/admin/api/pages/{auto2['id']}", method="DELETE")
jget(f"/admin/api/pages/{auto['id']}", method="DELETE")

# 同语言的第二个页面发布后，两页之间应有上下条
st, third = jget("/admin/api/pages", data=json.dumps({
    "title": f"SMOKE R03 {tag}", "lang": "en", "group_key": f"smoke-{tag}", "sort_order": 2,
}).encode(), ctype="application/json")
jget(f"/admin/api/pages/{third['id']}/status", data=json.dumps({"published": True}).encode(),
     ctype="application/json")
st, body = call(f"/p/{slug}")
check("同组同语言出上下条导航", st == 200 and b'class="pager"' in body and "SMOKE R03".encode() in body,
      f"实际 {st}")
st, body = call(f"/p/{third['slug']}")
check("第二条页面上条指回第一页", slug.encode() in body, f"实际 {st}")

# 7. 标识改动的保护
st, out = jget(f"/admin/api/pages/{pid}", method="PUT",
               data=json.dumps({"title": "改名", "slug": "smoke-dup"}).encode(), ctype="application/json")
check("改网址标识生效", st == 200 and out.get("slug") == "smoke-dup", f"实际 {st} {str(out)[:120]}")
old = out["slug"]
st, out = jget(f"/admin/api/pages/{cid}", method="PUT",
               data=json.dumps({"title": "撞名", "slug": old}).encode(), ctype="application/json")
check("标识重复被拒", st in (400, 409), f"实际 {st}")
st, out = jget(f"/admin/api/pages/{pid}", method="PUT",
               data=json.dumps({"title": "", "slug": old}).encode(), ctype="application/json")
check("空标题被拒", st == 400, f"实际 {st}")

# 8. 越权与清理
st, body = call(f"/preview/{slug}")
_call_cookie = _cookie
globals()["_cookie"] = ""
st2, body2 = call(f"/preview/{old}")
globals()["_cookie"] = _call_cookie
check("未登录打不开草稿预览", st2 in (401, 404), f"实际 {st2}")

st, out = jget(f"/admin/api/pages/{pid}", method="DELETE")
check("删除页面", st == 200, f"实际 {st}")
st, _ = call(f"/p/{old}")
check("删除后二维码失效", st == 404, f"实际 {st}")
jget(f"/admin/api/pages/{cid}", method="DELETE")
jget(f"/admin/api/pages/{third['id']}", method="DELETE")
if image_id:
    st, out = jget(f"/admin/api/images/{image_id}", method="DELETE")
    check("被引用过的图片删除受限或成功", st in (200, 400), f"实际 {st} {str(out)[:100]}")
st, _ = call("/admin/api/logout", data=b"", method="POST")
check("退出登录", st == 200, f"实际 {st}")
st, _ = call("/admin/api/pages")
check("退出后后台 API 不再可用", st == 401, f"实际 {st}")

print()
if _failed:
    print(f"共 {len(_failed)} 个用例失败: " + ", ".join(_failed))
    sys.exit(1)
print("全部用例通过")
