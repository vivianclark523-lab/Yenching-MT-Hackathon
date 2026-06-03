#!/usr/bin/env python3
"""scripts/imagegen.py — 出行小结卡片生成（即梦AI 文生图 + 代码叠字，全项目唯一入口）。

链路：足迹 spec → 拼手帐风「无文字」插画 prompt → 即梦4.6 出底图 → PIL 叠干净中文文字层
（标题 / 时间轴 / 总结）→ 输出竖版卡片 PNG。文生图渲染不可靠中文，故文字一律由代码叠加。

子命令：
  card --spec '<JSON>' --out <path>

足迹 spec JSON：
  {
    "date": "6/7",
    "stops": [
      {"time": "18:21", "name": "海底捞·望京店", "kind": "火锅"},
      {"time": "20:00", "name": "嘉禾望京影院", "kind": "电影"}
    ],
    "summary": "火锅配电影，望京的快乐周末"
  }

双模式 / fallback 链（demo 不翻车）：
  1. 有 JIMENG key + 出图成功 → 即梦底图 + 叠字（mode=jimeng）
  2. 出图失败 / 无 key → 纯手帐底色卡 + 叠字（mode=fallback_card）
  3. 连 PIL/中文字体都没有 → 文字版小结（mode=fallback_text，写 <out>.txt）

凭证从仓库根 .env 读：JIMENG_ACCESS_KEY_ID / JIMENG_SECRET_ACCESS_KEY（火山引擎 AK/SK）。
依赖：Pillow（见 requirements.txt）。
"""

import argparse
import hashlib
import hmac
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------- 即梦4.6（火山引擎视觉服务）----------

_JIMENG = {
    "host": "visual.volcengineapi.com",
    "region": "cn-north-1",
    "service": "cv",
    "version": "2022-08-31",
    "req_key": "jimeng_seedream46_cvtob",  # 即梦AI-图片生成 4.6
}
_SAFE_SIZE = (1024, 1024)  # seedream46 已验证可用；非法尺寸（如 720x1280）会内部失败


def _load_env():
    """读仓库根 .env 注入 os.environ（不覆盖已存在的）。"""
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _ssl_ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _creds():
    _load_env()
    ak = os.environ.get("JIMENG_ACCESS_KEY_ID", "").strip()
    sk = os.environ.get("JIMENG_SECRET_ACCESS_KEY", "").strip()
    return ak, sk


def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _sha256_hex(b) -> str:
    return hashlib.sha256(b if isinstance(b, bytes) else b.encode("utf-8")).hexdigest()


def _visual_call(ak: str, sk: str, action: str, body: dict) -> dict:
    """调火山视觉服务（手写签名 V4）。返回解析后的 JSON dict。"""
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    now = datetime.now(timezone.utc)
    xdate = now.strftime("%Y%m%dT%H%M%SZ")
    datestamp = now.strftime("%Y%m%d")
    host, region, service, version = (
        _JIMENG["host"], _JIMENG["region"], _JIMENG["service"], _JIMENG["version"],
    )
    cqs = "&".join(
        f"{urllib.parse.quote(k, safe='-_.~')}={urllib.parse.quote(v, safe='-_.~')}"
        for k, v in sorted({"Action": action, "Version": version}.items())
    )
    ph = _sha256_hex(payload)
    canonical_headers = (
        f"content-type:application/json\nhost:{host}\n"
        f"x-content-sha256:{ph}\nx-date:{xdate}\n"
    )
    signed_headers = "content-type;host;x-content-sha256;x-date"
    canonical_request = "\n".join(["POST", "/", cqs, canonical_headers, signed_headers, ph])
    scope = f"{datestamp}/{region}/{service}/request"
    string_to_sign = "\n".join(["HMAC-SHA256", xdate, scope, _sha256_hex(canonical_request)])
    k_sign = _sign(_sign(_sign(_sign(sk.encode("utf-8"), datestamp), region), service), "request")
    signature = hmac.new(k_sign, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    authorization = (
        f"HMAC-SHA256 Credential={ak}/{scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    req = urllib.request.Request(f"https://{host}/?{cqs}", data=payload, method="POST")
    for h, v in [
        ("Content-Type", "application/json"), ("Host", host),
        ("X-Date", xdate), ("X-Content-Sha256", ph), ("Authorization", authorization),
    ]:
        req.add_header(h, v)
    try:
        with urllib.request.urlopen(req, timeout=40, context=_ssl_ctx()) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read().decode("utf-8"))
        except Exception:
            return {"code": exc.code, "message": "HTTPError"}


def _jimeng_once(ak, sk, prompt, width, height, poll_max=25, interval=3.0):
    """提交一次文生图并轮询，成功返回图片字节，失败返回 None。"""
    submit = _visual_call(ak, sk, "CVSync2AsyncSubmitTask", {
        "req_key": _JIMENG["req_key"], "prompt": prompt,
        "width": int(width), "height": int(height),
    })
    task_id = (submit.get("data") or {}).get("task_id")
    if not task_id:
        return None, submit.get("message", "submit failed")
    for _ in range(poll_max):
        time.sleep(interval)
        res = _visual_call(ak, sk, "CVSync2AsyncGetResult", {
            "req_key": _JIMENG["req_key"], "task_id": task_id,
            "req_json": json.dumps({"return_url": True}),
        })
        data = res.get("data") or {}
        urls = data.get("image_urls")
        if urls:
            try:
                with urllib.request.urlopen(
                    urllib.request.Request(urls[0]), timeout=40, context=_ssl_ctx()
                ) as im:
                    return im.read(), None
            except Exception as exc:
                return None, f"download failed: {exc}"
        if str(res.get("code")) == "50500" or data.get("status") in ("failed", "not_found", "expired"):
            return None, res.get("message", "generation failed")
    return None, "poll timeout"


def jimeng_generate(prompt, width, height):
    """即梦文生图。尺寸非法时自动回落到已验证可用的 1024x1024。无 key/失败返回 None。"""
    ak, sk = _creds()
    if not ak or not sk:
        return None
    img, err = _jimeng_once(ak, sk, prompt, width, height)
    if img is None and (width, height) != _SAFE_SIZE:
        # 尺寸可能非法 → 回落安全尺寸再试一次
        img, err = _jimeng_once(ak, sk, prompt, *_SAFE_SIZE)
    return img


# ---------- prompt 构建（手帐风、零文字、留白叠字）----------

_KIND_HINT = {
    "火锅": "冒着热气的小火锅", "电影": "电影院的胶片和爆米花桶", "公园": "小树和长椅",
    "咖啡": "一杯拿铁咖啡", "购物": "可爱的购物袋", "展览": "画框与画作",
    "餐厅": "餐盘和餐具", "烧烤": "烤串小摊", "甜品": "蛋糕和冰淇淋", "酒吧": "鸡尾酒杯",
}


def build_prompt(stops):
    n = len(stops) or 1
    hints = "、".join(_KIND_HINT.get(s.get("kind", ""), "一个可爱小景点") for s in stops)
    return (
        "手帐拼贴风（scrapbook journal）插画，竖版 9:16 手机海报。"
        "米白纸张质感背景，淡格子/点阵纹理，边角点缀手绘波浪线和和纸胶带。"
        f"画面中央用蜡笔/马克笔涂鸦风、手绘虚线箭头串起一条蜿蜒出行路线，沿途 {n} 个拟物化地标小景："
        f"{hints}；点缀小星星、爱心、对话气泡等手帐贴纸，暖色治愈色调，留白通透。"
        "顶部和底部各留出一条干净的横向空白带。"
        "整幅画面不出现任何文字、字母或数字，不要真实品牌 logo。"
    )


# ---------- PIL 叠字 ----------

_FONT_CANDIDATES = [
    os.environ.get("JIMENG_CJK_FONT", ""),
    str(REPO_ROOT / "assets" / "fonts" / "NotoSansSC-Regular.otf"),  # 内置（如有）
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/wenquanyi/wqy-zenhei/wqy-zenhei.ttc",
]


def _find_font():
    for p in _FONT_CANDIDATES:
        if p and Path(p).exists():
            return p
    return None


def render_card(spec, bg_bytes, out_path, font_path):
    """用 PIL 合成卡片：底图（或纯色）+ 半透明纸条面板 + 干净中文文字。"""
    from PIL import Image, ImageDraw, ImageFont

    W, H = 768, 1344
    if bg_bytes:
        bg = Image.open(__import__("io").BytesIO(bg_bytes)).convert("RGB")
        # cover-fit 到画布
        scale = max(W / bg.width, H / bg.height)
        bg = bg.resize((round(bg.width * scale), round(bg.height * scale)))
        left = (bg.width - W) // 2
        top = (bg.height - H) // 2
        canvas = bg.crop((left, top, left + W, top + H))
        mode = "jimeng"
    else:
        canvas = Image.new("RGB", (W, H), (251, 246, 236))  # 手帐米白
        mode = "fallback_card"

    canvas = canvas.convert("RGBA")
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)

    def font(sz):
        return ImageFont.truetype(font_path, sz)

    ink = (74, 64, 58, 255)        # 暖褐文字
    accent = (232, 138, 90, 255)   # 暖橙点缀

    # 顶部标题带
    d.rounded_rectangle([28, 36, W - 28, 132], radius=24, fill=(255, 255, 255, 210))
    title = f"今日打卡 · {spec.get('date', '')}".strip(" ·")
    tf = font(46)
    tb = d.textbbox((0, 0), title, font=tf)
    d.text(((W - (tb[2] - tb[0])) / 2, 58), title, font=tf, fill=ink)

    # 中下部时间轴纸条面板
    stops = spec.get("stops", [])
    panel_top = int(H * 0.46)
    d.rounded_rectangle([28, panel_top, W - 28, H - 40], radius=28, fill=(255, 255, 255, 224))

    rf = font(34)
    tf2 = font(30)
    x_dot, x_text = 78, 120
    y = panel_top + 48
    row_gap = 92
    for i, s in enumerate(stops):
        # 时间轴竖线 + 圆点
        if i > 0:
            d.line([(x_dot, y - row_gap + 18), (x_dot, y + 18)], fill=accent, width=4)
        d.ellipse([x_dot - 13, y + 5, x_dot + 13, y + 31], fill=accent)
        d.text((x_dot - 8, y + 6), str(i + 1), font=font(22), fill=(255, 255, 255, 255))
        # 时间 + 店名
        d.text((x_text, y - 4), s.get("time", ""), font=tf2, fill=accent)
        d.text((x_text + 96, y - 6), s.get("name", ""), font=rf, fill=ink)
        y += row_gap

    # 底部总结
    summary = spec.get("summary", "")
    if summary:
        sf = font(30)
        # 简单按宽度折行
        line, lines = "", []
        for ch in summary:
            if d.textlength(line + ch, font=sf) > W - 120:
                lines.append(line); line = ch
            else:
                line += ch
        if line:
            lines.append(line)
        sy = H - 40 - 24 - len(lines) * 40
        for ln in lines:
            lb = d.textbbox((0, 0), ln, font=sf)
            d.text(((W - (lb[2] - lb[0])) / 2, sy), ln, font=sf, fill=(150, 110, 90, 255))
            sy += 40

    out = Image.alpha_composite(canvas, overlay).convert("RGB")
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    out.save(out_path, "PNG")
    return mode


def fallback_text(spec, out_path):
    """连 PIL/字体都没有时的纯文字小结。"""
    lines = [f"📍 今日打卡 · {spec.get('date', '')}", ""]
    for s in spec.get("stops", []):
        lines.append(f"  {s.get('time', '')}  {s.get('name', '')}")
    if spec.get("summary"):
        lines += ["", f"  {spec['summary']}"]
    txt = "\n".join(lines)
    txt_path = str(out_path) + ".txt"
    Path(txt_path).parent.mkdir(parents=True, exist_ok=True)
    Path(txt_path).write_text(txt, encoding="utf-8")
    return txt_path, txt


# ---------- CLI ----------

def cmd_card(args):
    try:
        spec = json.loads(args.spec)
    except json.JSONDecodeError as exc:
        print(json.dumps({"ok": False, "stage": "card", "error": f"spec 解析失败：{exc}"}, ensure_ascii=False))
        sys.exit(1)

    font_path = _find_font()
    try:
        import PIL  # noqa: F401
        has_pil = True
    except Exception:
        has_pil = False

    if not has_pil or not font_path:
        # 退化为纯文字
        txt_path, txt = fallback_text(spec, args.out)
        print(json.dumps({
            "ok": True, "mode": "fallback_text", "out": txt_path,
            "reason": "缺少 Pillow 或中文字体", "text": txt,
        }, ensure_ascii=False, indent=2))
        return

    bg = jimeng_generate(build_prompt(spec.get("stops", [])), 768, 1344)
    mode = render_card(spec, bg, args.out, font_path)
    print(json.dumps({"ok": True, "mode": mode, "out": args.out}, ensure_ascii=False, indent=2))


def main():
    p = argparse.ArgumentParser(description="出行小结卡片生成（即梦4.6 + 叠字）")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("card", help="生成出行小结卡片")
    c.add_argument("--spec", required=True, help="足迹 JSON")
    c.add_argument("--out", required=True, help="输出图片路径")
    c.set_defaults(func=cmd_card)
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
