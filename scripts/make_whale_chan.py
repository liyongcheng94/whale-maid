#!/usr/bin/env python3
"""从官方 Q 版设定图抠出正面立绘 -> web/frontend/assets/whale_chan.png

用法（Windows venv 或任意带 Pillow+numpy+scipy 的 Python）:
    python make_whale_chan.py <设定图路径> [输出路径]

流程:
  1. 裁剪前视图区域（含完整左侧头发: x 从 0 起）
  2. scipy.ndimage.label 做连通域背景泛洪（从边缘起），白底 -> 透明
  3. 近白晕圈羽化（与背景相邻的近白像素 -> 半透明）
  4. alpha bbox 裁紧 + 自检（左/右/上/下边缘不得有硬切内容）
"""
import sys
import numpy as np
from PIL import Image
from scipy import ndimage

# 前视图在 1448x1086 设定图中的范围（左上角起）
CROP = (0, 0, 555, 618)   # left, top, right, bottom —— left=0 保住左侧飘发
BG_THRESHOLD = 240        # 亮度 >= 此值视为候选背景
HALO_THRESHOLD = 225      # 与背景相邻且亮度 >= 此值 -> 半透明晕圈


def extract(src_path: str, out_path: str) -> Image.Image:
    im = Image.open(src_path).convert("RGB")
    crop = im.crop(CROP)
    a = np.asarray(crop).astype(np.int16)
    lum = a.mean(axis=2)

    # 背景候选：亮色像素
    bright = lum >= BG_THRESHOLD
    # 只保留与图像边缘连通的亮色区域（角色内部的白色围裙/头饰不受影响）
    labels, _ = ndimage.label(bright)
    border_labels = set(
        np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
    )
    border_labels.discard(0)
    bg = np.isin(labels, list(border_labels))

    alpha = np.where(bg, 0, 255).astype(np.uint8)

    # 晕圈：与背景相邻的近白像素降为半透明，软化 JPEG 白边
    near_white = (lum >= HALO_THRESHOLD) & ~bg
    neighbor_bg = ndimage.binary_dilation(bg, iterations=1)
    halo = near_white & neighbor_bg
    alpha[halo] = 120

    rgba = np.dstack([np.asarray(crop).astype(np.uint8), alpha])
    out = Image.fromarray(rgba, "RGBA")

    # 只保留最大不透明连通域（清除侧视图泄漏的发丝等孤立残留）
    solid = alpha > 60
    clabels, cnum = ndimage.label(solid)
    if cnum > 1:
        sizes = ndimage.sum(solid, clabels, range(1, cnum + 1))
        keep = int(np.argmax(sizes)) + 1
        removed = cnum - 1
        alpha[clabels != keep] = 0
        rgba = np.dstack([np.asarray(crop).astype(np.uint8), alpha])
        out = Image.fromarray(rgba, "RGBA")
        print(f"[clean] 移除 {removed} 个孤立碎块")

    # 裁紧到内容 bbox
    bbox = out.getbbox()
    out = out.crop(bbox)

    # 自检：四边不应有大量不透明像素贴边（硬切痕迹）
    arr = np.asarray(out)[:, :, 3]
    edges = {"top": arr[0], "bottom": arr[-1], "left": arr[:, 0], "right": arr[:, -1]}
    for name, line in edges.items():
        solid = int((line > 200).sum())
        if solid > 40:
            print(f"[WARN] {name} 边缘有 {solid} 个硬切像素，裁剪框可能不足")
    return out


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "q版设定图_官方.jpg"
    out_path = (
        sys.argv[2]
        if len(sys.argv) > 2
        else "web/frontend/assets/whale_chan.png"
    )
    out = extract(src, out_path)
    out.save(out_path)
    print(f"OK -> {out_path}  size={out.size[0]}x{out.size[1]}")


if __name__ == "__main__":
    main()
