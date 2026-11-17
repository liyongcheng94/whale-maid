"""生成 PWA 图标(WhatsApp 式圆底鲸鱼娘)。

产物:web/frontend/icon-512.png / icon-192.png / apple-touch-icon.png
依赖:pillow(一次性资产生成,产物已入库,CI 不需要装)
运行:pip install pillow && python scripts/make_icon.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "web" / "frontend"

BODY = (126, 200, 247, 255)
BELLY = (207, 234, 255, 255)
FIN = (108, 182, 234, 255)
DARK = (38, 51, 63, 255)
BLUSH = (255, 158, 181, 235)
BOW = (255, 158, 181, 255)
BOW2 = (255, 183, 201, 255)


def draw(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    S = size / 340.0  # 以 SVG viewBox 340 为几何基准

    def E(x0, y0, x1, y1, fill):
        d.ellipse([x0 * S, y0 * S, x1 * S, y1 * S], fill=fill)

    # 圆角海蓝底
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=int(size * 0.22), fill=(20, 144, 200, 255))
    # 尾巴
    d.polygon([(258 * S, 150 * S), (330 * S, 118 * S), (322 * S, 142 * S),
               (330 * S, 168 * S), (262 * S, 172 * S)], fill=FIN)
    # 身体 + 肚皮
    E(52, 79, 268, 231, BODY)
    E(84, 158, 236, 238, BELLY)
    # 女仆头饰弧带
    d.arc([86 * S, 30 * S, 234 * S, 122 * S], start=205, end=335,
          fill=(255, 255, 255, 255), width=int(17 * S))
    # 蝴蝶结
    d.polygon([(70 * S, 84 * S), (96 * S, 72 * S), (96 * S, 92 * S)], fill=BOW)
    d.polygon([(96 * S, 92 * S), (122 * S, 84 * S), (104 * S, 62 * S)], fill=BOW2)
    E(92, 76, 104, 88, (255, 127, 160, 255))
    # 眼睛 + 高光
    E(114, 128, 142, 158, DARK)
    E(172, 128, 200, 158, DARK)
    E(128, 133, 137, 142, (255, 255, 255, 255))
    E(186, 133, 195, 142, (255, 255, 255, 255))
    # 腮红 + 微笑
    E(92, 160, 118, 176, BLUSH)
    E(198, 160, 224, 176, BLUSH)
    d.arc([146 * S, 168 * S, 174 * S, 192 * S], start=15, end=165,
          fill=DARK, width=int(4 * S))
    return img


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for size, name in [(512, "icon-512.png"), (192, "icon-192.png"), (180, "apple-touch-icon.png")]:
        draw(size).save(OUT / name)
        print(f"ok {name} ({size}x{size})")


if __name__ == "__main__":
    main()
