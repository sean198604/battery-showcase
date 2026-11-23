import html
import re

from . import config

_RTL_LANGS = {"ar", "he", "fa", "ur"}
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?!\w)")


def esc(text: str) -> str:
    return html.escape(text or "", quote=True)


def inline(text: str) -> str:
    """只认 **粗体** 和 *斜体*，其余全部转义，避免把用户内容当 HTML 执行。"""
    out = esc(text)
    out = _BOLD.sub(r"<strong>\1</strong>", out)
    out = _ITALIC.sub(r"<em>\1</em>", out)
    return out


def rich_text(text: str) -> str:
    """把后台里的纯文本按空行/列表/标题排成 HTML。"""
    parts = []
    para: list[str] = []
    list_items: list[str] = []
    list_kind = None  # 'ul' | 'ol'

    def flush_list():
        nonlocal list_items, list_kind
        if list_items:
            tag = list_kind or "ul"
            parts.append(f"<{tag}>" + "".join(f"<li>{i}</li>" for i in list_items) + f"</{tag}>")
        list_items, list_kind = [], None

    def flush_para():
        if para:
            parts.append("<p>" + "<br>".join(para) + "</p>")
            para.clear()

    for raw in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.strip()
        if not line:
            flush_para()
            flush_list()
            continue
        if line.startswith("### "):
            flush_para(); flush_list(); parts.append(f"<h4>{inline(line[4:])}</h4>"); continue
        if line.startswith("## "):
            flush_para(); flush_list(); parts.append(f"<h3>{inline(line[3:])}</h3>"); continue
        if line.startswith("- ") or line.startswith("* "):
            flush_para()
            list_kind = list_kind or "ul"
            list_items.append(inline(line[2:]))
            continue
        m = re.match(r"^(\d+)[.)]\s+(.*)$", line)
        if m:
            flush_para()
            list_kind = list_kind or "ol"
            list_items.append(inline(m.group(2)))
            continue
        flush_list()
        para.append(inline(line))
    flush_para()
    flush_list()
    return "".join(parts)


def specs_table(data_json: str, fallback_text: str = "") -> str:
    rows = _parse_pairs(data_json, fallback_text)
    if not rows:
        return ""
    body = "".join(f"<tr><th>{esc(k)}</th><td>{inline(v)}</td></tr>" for k, v in rows)
    return f'<table class="specs"><tbody>{body}</tbody></table>'


def _parse_pairs(data_json: str, fallback_text: str) -> list[tuple[str, str]]:
    import json

    rows: list[tuple[str, str]] = []
    if data_json:
        try:
            loaded = json.loads(data_json)
        except ValueError:
            loaded = None
        if isinstance(loaded, list):
            for item in loaded:
                if isinstance(item, dict) and item.get("k"):
                    rows.append((str(item["k"]), str(item.get("v") or "")))
            if rows:
                return rows
    for line in (fallback_text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        for sep in ("：", ":", "=", "|", "\t"):
            if sep in line:
                k, v = line.split(sep, 1)
                rows.append((k.strip(), v.strip()))
                break
        else:
            rows.append((line, ""))
    return rows


CSS = """
*{box-sizing:border-box;-webkit-text-size-adjust:100%}
body{margin:0;background:#f4f6f8;color:#1c2530;
 font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",
 "PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;
 font-size:16px;line-height:1.75;-webkit-font-smoothing:antialiased}
.wrap{max-width:720px;margin:0 auto;background:#fff;min-height:100vh;
 box-shadow:0 0 24px rgba(20,30,40,.07)}
.hero{padding:0 0 18px}
.hero .cover{display:block;width:100%;height:clamp(170px,26vw,290px);object-fit:cover;
 background:#dde3ea}
.head{padding:18px 18px 4px}
.cat{color:#2b7fd4;font-size:13px;letter-spacing:.06em;text-transform:uppercase;font-weight:600}
h1{margin:.25em 0 .15em;font-size:25px;line-height:1.3}
.sub{margin:0;color:#5b6875;font-size:15px}
.main{padding:6px 18px 8px}
.main p{margin:.75em 0}
.main h3{font-size:19px;margin:1.3em 0 .5em;padding-left:10px;border-left:4px solid #2b7fd4}
.main h4{font-size:17px;margin:1.2em 0 .4em;color:#2f3a45}
.main ul,.main ol{margin:.6em 0;padding-left:1.4em}
.main li{margin:.3em 0}
figure{margin:14px 0}
figure img{display:block;width:100%;height:auto;border-radius:8px;background:#eef1f4}
figcaption{margin-top:6px;font-size:13px;color:#6b7783;text-align:center}
table.specs{width:100%;margin:14px 0;border-collapse:collapse;font-size:15px}
table.specs th,table.specs td{border:1px solid #e2e7ec;padding:9px 11px;vertical-align:top;text-align:left}
table.specs th{width:39%;background:#f6f8fa;color:#42505e;font-weight:600}
.note{margin:14px 0;padding:12px 14px;background:#f2f7fd;border-radius:8px;font-size:14px;color:#33506b}
.foot{padding:16px 18px 26px;border-top:1px solid #eef1f4;color:#6b7783;font-size:14px}
.foot p{margin:.3em 0}
.pager{display:flex;gap:10px;padding:14px 18px 4px}
.pager a{flex:1;text-decoration:none;color:#2b7fd4;background:#f2f7fd;border-radius:8px;
 padding:11px 12px;font-size:14px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pager a.next{text-align:right}
.pager span{color:#8a97a3}
.topbar{display:flex;flex-wrap:wrap;justify-content:flex-end;align-items:center;
 gap:4px 8px;padding:10px 14px 0}
.langlab{font-size:12px;color:#8a97a3}
.langs{display:flex;flex-wrap:wrap;gap:6px;justify-content:flex-end}
.langs a{display:inline-block;padding:5px 11px;border:1px solid #cfd8e2;
 border-radius:16px;font-size:13px;text-decoration:none;color:#42505e;background:#fff}
.langs a.on{background:#2b7fd4;border-color:#2b7fd4;color:#fff}
.draft{margin:0;padding:10px 18px;background:#fff3cd;color:#7a5b00;font-size:13px;text-align:center}
html[dir=rtl] .main h3{border-left:0;border-right:4px solid #2b7fd4;padding-left:0;padding-right:10px}
html[dir=rtl] table.specs th{text-align:right}
html[dir=rtl] .pager a.next{text-align:left}
"""


def page_html(page: dict, blocks: list[dict], siblings: list[dict],
              prev_page: dict | None, next_page: dict | None,
              draft_badge: bool = False, accept_language: str = "") -> str:
    lang = page.get("lang") or "en"
    # 正文语言由页面自己决定，界面小词（上一条/语言）跟着访客浏览器的区域语言走
    ui = _ui_lang(accept_language, lang)
    direction = "rtl" if lang in _RTL_LANGS else "ltr"
    site = config.LANG_NAMES.get(lang, lang)

    body: list[str] = []
    for b in blocks:
        body.append(_block_html(b))
    if not blocks:
        body.append(f'<div class="note">{esc(_l("empty", ui))}</div>')

    topbar = ""
    if len(siblings) > 1:
        items = "".join(
            f'<a class="{"on" if s["slug"] == page["slug"] else ""}" href="/p/{esc(s["slug"])}">'
            f'{esc(config.LANG_NAMES.get(s.get("lang") or "en", s.get("lang") or ""))}</a>'
            for s in siblings
        )
        topbar = (f'<div class="topbar"><span class="langlab">{esc(_l("language", ui))}</span>'
                  f'<div class="langs">{items}</div></div>')

    pager_html = ""
    if prev_page or next_page:
        left = right = ""
        if prev_page:
            left = (f'<a class="prev" href="/p/{esc(prev_page["slug"])}">'
                    f'<span>{esc(_l("prev", ui))} · </span>{esc(prev_page["title"])}</a>')
        if next_page:
            right = (f'<a class="next" href="/p/{esc(next_page["slug"])}">'
                     f'<span>{esc(_l("next", ui))} · </span>{esc(next_page["title"])}</a>')
        pager_html = f'<div class="pager">{left}{right}</div>'

    hero = ""
    if page.get("cover_token"):
        hero = (f'<img class="cover" src="/img/{esc(page["cover_token"])}/page" '
                f'alt="{esc(page["title"])}">')

    head_bits = []
    if page.get("header_text"):
        head_bits.append(f'<p class="cat">{esc(page["header_text"])}</p>')
    head_bits.append(f"<h1>{esc(page['title'])}</h1>")
    if page.get("subtitle"):
        head_bits.append(f'<p class="sub">{esc(page["subtitle"])}</p>')

    foot = ""
    if (page.get("footer_text") or "").strip():
        foot = f'<div class="foot">{rich_text(page["footer_text"])}</div>'

    badge = '<div class="draft">草稿预览 · 客人扫正式二维码看不到这页</div>' if draft_badge else ""
    title_tag = esc(page["title"]) or "Showcase"

    return f"""<!doctype html>
<html lang="{esc(lang)}" dir="{direction}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=5">
<meta name="description" content="{esc((page.get('subtitle') or page['title'])[:150])}">
<meta name="theme-color" content="#ffffff">
<meta property="og:title" content="{title_tag}">
<meta property="og:description" content="{esc((page.get('subtitle') or '')[:150])}">
<meta property="og:image" content="/img/{esc(page.get('cover_token') or '')}/page">
<meta property="og:type" content="article">
<title>{title_tag} · {esc(site)}</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
{badge}
{topbar}
<div class="hero">{hero}<div class="head">{''.join(head_bits)}</div></div>
<div class="main">{''.join(body)}</div>
{pager_html}
{foot}
</div>
</body>
</html>"""


def _block_html(b: dict) -> str:
    kind = b.get("kind") or "text"
    if kind == "image":
        if not b.get("image_token"):
            return ""
        cap = f'<figcaption>{inline(b["caption"])}</figcaption>' if b.get("caption") else ""
        # 带上真实宽高，图片加载完成前页面就不会往下跳
        size = ""
        if b.get("image_w") and b.get("image_h"):
            size = f' width="{int(b["image_w"])}" height="{int(b["image_h"])}"'
        return (f'<figure><img src="/img/{esc(b["image_token"])}/page" alt="{esc(b.get("caption") or "")}"'
                f'{size} loading="lazy">{cap}</figure>')
    if kind == "specs":
        return specs_table(b.get("data_json") or "", b.get("text") or "")
    if kind == "heading":
        return f"<h3>{inline(b.get('text') or '')}</h3>"
    if kind == "divider":
        return '<hr style="border:0;border-top:1px solid #eef1f4;margin:18px 0">'
    if kind == "note":
        return f'<div class="note">{rich_text(b.get("text") or "")}</div>'
    return rich_text(b.get("text") or "")


_LABELS = {
    "prev": {"zh": "上一条", "en": "Previous", "es": "Anterior", "pt": "Anterior", "ru": "Назад",
             "ar": "السابق", "fr": "Précédent", "de": "Zurück", "ja": "前へ",
             "id": "Sebelumnya", "vi": "Trước", "th": "ก่อนหน้า"},
    "next": {"zh": "下一条", "en": "Next", "es": "Siguiente", "pt": "Próximo", "ru": "Далее",
             "ar": "التالي", "fr": "Suivant", "de": "Weiter", "ja": "次へ",
             "id": "Berikutnya", "vi": "Tiếp", "th": "ถัดไป"},
    "language": {"zh": "语言", "en": "Language", "es": "Idioma", "pt": "Idioma", "ru": "Язык",
                 "ar": "اللغة", "fr": "Langue", "de": "Sprache", "ja": "言語",
                 "id": "Bahasa", "vi": "Ngôn ngữ", "th": "ภาษา"},
    "empty": {"zh": "这个页面还没有内容。", "en": "This page has no content yet.",
              "es": "Esta página aún no tiene contenido.", "pt": "Esta página ainda não tem conteúdo.",
              "ru": "На этой странице пока нет содержимого.", "ar": "لا يوجد محتوى في هذه الصفحة بعد.",
              "fr": "Cette page n'a pas encore de contenu.", "de": "Diese Seite hat noch keinen Inhalt.",
              "ja": "このページにはまだ内容がありません。", "id": "Halaman ini belum memiliki konten.",
              "vi": "Trang này chưa có nội dung.", "th": "หน้านี้ยังไม่มีเนื้อหา"},
}


def _l(key: str, lang: str) -> str:
    table = _LABELS.get(key, {})
    return table.get(lang) or table.get("en", key)


def _ui_lang(accept_language: str, page_lang: str) -> str:
    """按浏览器 Accept-Language 选界面小词的语言，认不出来就退回页面自己的语言。"""
    for tag in _accept_tags(accept_language):
        if tag in _LABELS["prev"]:
            return tag
    return page_lang if page_lang in _LABELS["prev"] else "en"


def _accept_tags(header: str) -> list[str]:
    """解析 Accept-Language，按 q 权重从高到低返回主语言子标签（zh-CN → zh）。"""
    scored: list[tuple[float, int, str]] = []
    for order, part in enumerate(header.split(",")):
        tag, _, params = part.strip().partition(";")
        primary = tag.lower().split("-")[0]
        quality = 1.0
        for param in params.split(";"):
            name, _, value = param.strip().partition("=")
            if name.lower() == "q":
                try:
                    quality = float(value)
                except ValueError:
                    quality = 0.0
        if primary and primary != "*":
            # 同权重时保留浏览器列出的先后顺序
            scored.append((-quality, order, primary))
    return [tag for _, _, tag in sorted(scored)]
