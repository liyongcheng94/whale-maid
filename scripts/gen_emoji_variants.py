# -*- coding: utf-8 -*-
"""生成鲸鱼娘 16 情绪表情变体(阶梯尺寸 64/128/240)。

基础:web/frontend/assets/whale_chan.png 居中裁剪 → 按情绪叠加程序化元素(腮红/泪滴/Zz/墨镜…)。
元素位置按画面比例定位(先跑通显示,美化属后续里程碑)。
用法:python scripts/gen_emoji_variants.py
输出:config/assets_source_{size}/{emotion}.png ×16 ×3 档
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "web" / "frontend" / "assets" / "whale_chan.png"
SIZES = [64, 128, 240]

# 眼睛/嘴的相对位置(whale_chan 立绘裁剪后经验值)
EYE_Y = 0.38
EYE_L_X = 0.36
EYE_R_X = 0.64
MOUTH_Y = 0.52
BLUSH_Y = 0.46
BLUSH_L_X = 0.24
BLUSH_R_X = 0.76


def load_base(size: int) -> Image.Image:
    img = Image.open(BASE).convert("RGBA")
    w, h = img.size
    side = min(w, h)
    crop = img.crop(((w - side) // 2, 0, (w - side) // 2 + side, side))
    crop.thumbnail((size, size), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(crop, ((size - crop.width) // 2, (size - crop.height) // 2), crop)
    return canvas


def P(canvas, fx, fy):
    """相对坐标 → 像素坐标"""
    return int(canvas.width * fx), int(canvas.height * fy)


def draw_eyes(canvas, style="open"):
    d = ImageDraw.Draw(canvas)
    s = canvas.width
    lw = max(2, s // 40)
    el, er = P(canvas, EYE_L_X, EYE_Y), P(canvas, EYE_R_X, EYE_Y)
    r = max(3, s // 22)
    if style == "open":
        for e in (el, er):
            d.ellipse([e[0] - r, e[1] - r, e[0] + r, e[1] + r], fill=(38, 51, 63, 255))
    elif style == "happy":  # 弯月眼 ^ ^
        for e in (el, er):
            d.arc([e[0] - r, e[1] - r, e[0] + r, e[1] + r], start=200, end=340,
                  fill=(38, 51, 63, 255), width=lw)
    elif style == "closed":
        for e in (el, er):
            d.line([e[0] - r, e[1], e[0] + r, e[1]], fill=(38, 51, 63, 255), width=lw)
    elif style == "wink":  # 左闭右开
        d.arc([el[0] - r, el[1] - r, el[0] + r, el[1] + r], start=200, end=340,
              fill=(38, 51, 63, 255), width=lw)
        d.ellipse([er[0] - r, er[1] - r, er[0] + r, er[1] + r], fill=(38, 51, 63, 255))


def draw_mouth(canvas, style="smile"):
    d = ImageDraw.Draw(canvas)
    s = canvas.width
    lw = max(2, s // 36)
    m = P(canvas, 0.5, MOUTH_Y)
    r = max(3, s // 16)
    if style == "smile":
        d.arc([m[0] - r, m[1] - r, m[0] + r, m[1] + r], start=15, end=165,
              fill=(38, 51, 63, 255), width=lw)
    elif style == "open":
        d.ellipse([m[0] - r, m[1] - r // 2, m[0] + r, m[1] + r], fill=(38, 51, 63, 255))
    elif style == "flat":
        d.line([m[0] - r, m[1], m[0] + r, m[1]], fill=(38, 51, 63, 255), width=lw)


def draw_blush(canvas, strong=False):
    d = ImageDraw.Draw(canvas)
    s = canvas.width
    r = max(4, s // (12 if strong else 18))
    a = 200 if strong else 140
    for fx in (BLUSH_L_X, BLUSH_R_X):
        c = P(canvas, fx, BLUSH_Y)
        d.ellipse([c[0] - r, c[1] - r // 2, c[0] + r, c[1] + r // 2], fill=(255, 158, 181, a))


def draw_tears(canvas, double=False):
    d = ImageDraw.Draw(canvas)
    s = canvas.width
    r = max(3, s // 24)
    pts = [P(canvas, EYE_L_X - 0.04, EYE_Y + 0.07)]
    if double:
        pts.append(P(canvas, EYE_R_X + 0.04, EYE_Y + 0.07))
    for p in pts:
        d.polygon([(p[0], p[1] - r * 2), (p[0] - r, p[1] + r), (p[0] + r, p[1] + r)],
                  fill=(120, 190, 240, 230))


def draw_brows(canvas, angry=False):
    d = ImageDraw.Draw(canvas)
    s = canvas.width
    lw = max(2, s // 36)
    r = max(3, s // 20)
    for fx, slope in ((EYE_L_X, -1 if angry else 1), (EYE_R_X, 1 if angry else -1)):
        e = P(canvas, fx, EYE_Y - 0.09)
        d.line([e[0] - r, e[1] + slope * lw, e[0] + r, e[1] - slope * lw],
               fill=(38, 51, 63, 255), width=lw)


def draw_zz(canvas):
    d = ImageDraw.Draw(canvas)
    s = canvas.width
    try:
        font = ImageFont.truetype("arial.ttf", max(10, s // 6))
    except Exception:
        font = None
    for i, (fx, fy) in enumerate(((0.72, 0.16), (0.82, 0.08), (0.90, 0.02))):
        p = P(canvas, fx, fy)
        d.text(p, "Z", fill=(232, 245, 255, 240), font=font)


def draw_glasses(canvas):
    d = ImageDraw.Draw(canvas)
    s = canvas.width
    r = max(4, s // 14)
    for fx in (EYE_L_X, EYE_R_X):
        e = P(canvas, fx, EYE_Y)
        d.rounded_rectangle([e[0] - r, e[1] - r // 2, e[0] + r, e[1] + r // 2],
                            radius=r // 3, fill=(20, 25, 30, 235))
    b1, b2 = P(canvas, EYE_L_X + 0.07, EYE_Y), P(canvas, EYE_R_X - 0.07, EYE_Y)
    d.line([b1, b2], fill=(20, 25, 30, 235), width=max(2, s // 40))


def draw_bubble(canvas):
    d = ImageDraw.Draw(canvas)
    s = canvas.width
    for fx, fy, r in ((0.78, 0.12, 0.030), (0.86, 0.06, 0.022), (0.92, 0.015, 0.016)):
        c = P(canvas, fx, fy)
        rr = max(2, int(s * r))
        d.ellipse([c[0] - rr, c[1] - rr, c[0] + rr, c[1] + rr],
                  outline=(240, 248, 255, 230), width=max(1, s // 60))


def draw_sweat(canvas):
    d = ImageDraw.Draw(canvas)
    s = canvas.width
    r = max(3, s // 22)
    p = P(canvas, 0.80, EYE_Y - 0.10)
    d.polygon([(p[0], p[1] - r), (p[0] - r, p[1] + r), (p[0] + r, p[1] + r)],
              fill=(150, 210, 245, 230))


EMOTIONS = {
    "neutral":      lambda c: (draw_eyes(c, "open"), draw_mouth(c, "smile")),
    "happy":        lambda c: (draw_eyes(c, "happy"), draw_mouth(c, "smile"), draw_blush(c)),
    "laughing":     lambda c: (draw_eyes(c, "closed"), draw_mouth(c, "open")),
    "sad":          lambda c: (draw_eyes(c, "open"), draw_mouth(c, "flat"), draw_brows(c), draw_tears(c)),
    "angry":        lambda c: (draw_eyes(c, "open"), draw_mouth(c, "flat"), draw_brows(c, angry=True), draw_blush(c, strong=True)),
    "crying":       lambda c: (draw_eyes(c, "closed"), draw_mouth(c, "open"), draw_tears(c, double=True)),
    "loving":       lambda c: (draw_eyes(c, "happy"), draw_mouth(c, "smile"), draw_blush(c, strong=True)),
    "embarrassed":  lambda c: (draw_eyes(c, "open"), draw_mouth(c, "flat"), draw_blush(c, strong=True), draw_sweat(c)),
    "surprised":    lambda c: (draw_eyes(c, "open"), draw_mouth(c, "open"), draw_brows(c)),
    "shocked":      lambda c: (draw_eyes(c, "open"), draw_mouth(c, "open"), draw_sweat(c)),
    "thinking":     lambda c: (draw_eyes(c, "open"), draw_mouth(c, "flat"), draw_bubble(c)),
    "winking":      lambda c: (draw_eyes(c, "wink"), draw_mouth(c, "smile"), draw_blush(c)),
    "cool":         lambda c: (draw_glasses(c), draw_mouth(c, "smile")),
    "relaxed":      lambda c: (draw_eyes(c, "closed"), draw_mouth(c, "smile")),
    "delicious":    lambda c: (draw_eyes(c, "happy"), draw_mouth(c, "open"), draw_blush(c)),
    "sleepy":       lambda c: (draw_eyes(c, "closed"), draw_mouth(c, "open"), draw_zz(c)),
}


def main():
    for size in SIZES:
        out = ROOT / "config" / f"assets_source_{size}"
        out.mkdir(parents=True, exist_ok=True)
        for name, decorate in EMOTIONS.items():
            canvas = load_base(size)
            decorate(canvas)
            canvas.save(out / f"{name}.png")
        print(f"ok {size}px: {len(EMOTIONS)} 张 -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
