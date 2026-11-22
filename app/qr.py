import io

import segno

_BORDER = 4


def _code(url: str):
    # error='m' 在数据量和容错之间平衡；手机扫码场景够用
    return segno.make(url, error="m", micro=False)


def png(url: str, scale: int = 10) -> bytes:
    """scale 是每个模块的像素数：10 约 330px，20 约 660px，30 约 1000px。"""
    buf = io.BytesIO()
    _code(url).save(buf, kind="png", scale=max(4, min(int(scale), 60)), border=_BORDER)
    return buf.getvalue()


def svg(url: str) -> bytes:
    buf = io.BytesIO()
    _code(url).save(buf, kind="svg", border=_BORDER)
    return buf.getvalue()


def side_length(url: str) -> int:
    """二维码边长（模块数，不含留白）。越大越难扫，后台用它提示链接过长。"""
    return 4 * _code(url).version + 17
