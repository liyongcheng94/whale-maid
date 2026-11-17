#!/usr/bin/env python3
"""从官方 Q 版设定图抠出正面立绘 -> web/frontend/assets/whale_chan.png

用法（Windows venv 或任意带 Pillow+numpy+scipy 的 Python）:
    python make_whale_chan.py <设定图路径> [输出路径]

流程:
  1. 裁剪前视图区域（含完整左侧头发: x 从 0 起）
  2. scipy.ndimage.label 做连通域背景泛洪（从边缘起），白底 -> 透明
  3. 边缘白晕直接透明化（2026-11-17 v2: 半透明白在页面深色背景上呈亮圈，弃用）
  4. 底座椭圆清除（设定图脚下白色投影盘，与鞋连通、泛洪够不到 -> 形状判据剔除）
  5. alpha bbox 裁紧 + 自检（左/右/上/下边缘不得有硬切内容）
"""
import sys
import numpy as np
from PIL import Image
from scipy import ndimage

# 前视图在 1448x1086 设定图中的范围（左上角起）
CROP = (0, 0, 555, 618)   # left, top, right, bottom —— left=0 保住左侧飘发
BG_THRESHOLD = 240        # 亮度 >= 此值视为候选背景
HALO_THRESHOLD = 200      # 与背景相邻且亮度 >= 此值 -> 直接透明（去白边）
BASE_LUM = 238            # 底座判定亮度
BASE_RATIO = 4.0          # 底座 bbox 宽高比下限
BASE_WIDTH = 0.25         # 底座 bbox 宽度占全图比例下限
BASE_Y = 0.85             # 底座质心 y 位置下限（图像底部）


def extract(src_path: str, out_path: str) -> Image.Image:
    im = Image.open(src_path).convert("RGB")
    crop = im.crop(CROP)
    a = np.asarray(crop).astype(np.int16)
    lum = a.mean(axis=2)
    h, w = lum.shape

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

    # 白晕：与背景相邻的近白像素 -> 完全透明（半透明白在深色页面上是亮边）
    near_white = (lum >= HALO_THRESHOLD) & ~bg
    neighbor_bg = ndimage.binary_dilation(bg, iterations=1)
    halo = near_white & neighbor_bg
    alpha[halo] = 0

    # 底座椭圆清除：alpha 内的亮白连通块，扁形（宽高比大）、够宽、位于底部
    white_inside = (lum >= BASE_LUM) & (alpha > 0)
    wlabels, wn = ndimage.label(white_inside)
    for i in range(1, wn + 1):
        ys, xs = np.where(wlabels == i)
        bw, bh = xs.max() - xs.min() + 1, ys.max() - ys.min() + 1
        cy = ys.mean() / h
        if bw / max(bh, 1) >= BASE_RATIO and bw >= BASE_WIDTH * w and cy >= BASE_Y:
            alpha[wlabels == i] = 0
            print(f"[clean] 移除底座椭圆: bbox {bw}x{bh} @ y均值 {cy:.2f}")

    # 底座灰带清扫（椭圆渐变边缘 lum 208-214，低于椭圆阈值漏网）:
    # 底部区域 + 亮 + 5x5 邻域无深色轮廓(鞋子高光贴着深色鞋面,不会被误删) -> 透明
    band_y = int(h * 0.96)
    minlum = ndimage.minimum_filter(lum, size=5)
    band_core = (
        (np.arange(h)[:, None] >= band_y)
        & (lum >= 190)
        & (minlum > 120)
        & (alpha > 0)
    )
    alpha[band_core] = 0
    if band_core.sum():
        print(f"[clean] 底座灰带: {int(band_core.sum())} px")
    # 迭代 2 轮: 与已透明区相邻的残余亮像素继续清（贴鞋轮廓的灰带衔接处）
    for _ in range(2):
        near_clear = ndimage.binary_dilation(alpha == 0, iterations=1)
        edge_band = (
            (np.arange(h)[:, None] >= band_y)
            & (lum >= 190)
            & near_clear
            & (alpha > 0)
        )
        alpha[edge_band] = 0

    # 封闭背景清除: 两腿之间的设定图纸面背景（被腿/鞋/裙摆围住, 泛洪够不到）。
    # 判据: 纯白(lum>=235) 低饱和(sat<=12) 连通块, bbox 完全落在两腿之间窗口内。
    # 窗口按本设定图几何实测: 裙撑/袜子白有蓝灰阴影 sat>=15 不受影响;
    # 袜子高光块 bbox 越出窗口边界而保留。
    sat = a.max(axis=2) - a.min(axis=2)
    enclosed = (lum >= 235) & (sat <= 12) & (alpha > 0)
    elabels, en = ndimage.label(enclosed)
    # 窗口为源图(裁剪内)坐标: 两腿之间区域, 按几何实测。
    # 右界 292 必须避开右袜蕾丝(源图 x>=291)——过宽会吃掉袜子白色蕾丝
    WX0, WX1, WY0, WY1 = 218, 289, 544, 602
    removed_enc = 0
    for i in range(1, en + 1):
        ys, xs = np.where(elabels == i)
        if xs.min() >= WX0 and xs.max() <= WX1 and ys.min() >= WY0 and ys.max() <= WY1:
            alpha[elabels == i] = 0
            removed_enc += int((elabels == i).sum())
    if removed_enc:
        print(f"[clean] 封闭背景(两腿之间): {removed_enc} px")

    # 两鞋之间残线(底座上缘 1-2px, 上下皆鞋面深色, minlum/near_clear 判据均够不到)
    # ——定点清除: 左鞋右侧白线 x231-249 与中部 x250-306, 亮度窗口避开鞋面高光(250+)
    strip = np.zeros_like(alpha, dtype=bool)
    strip[589:595, 225:312] = True
    strip &= (lum >= 190) & (lum <= 240) & (alpha > 0)
    alpha[strip] = 0
    if strip.sum():
        print(f"[clean] 两鞋之间残线: {int(strip.sum())} px")

    # 发丝/尾部间隙的封闭背景白点: 纯白低饱和连通块, 且整体落在轮廓边缘区
    # (源图 x<95 或 x>415, 即左右发梢与鲸尾外缘; 躯干中央的衬衫前襟/围裙/
    #  头饰/袖口纯白高光全部在此范围之外, 不会误伤)
    speck = (lum >= 235) & (sat <= 12) & (alpha > 0)
    slabels, sn = ndimage.label(speck)
    removed_speck = 0
    for i in range(1, sn + 1):
        m = slabels == i
        cnt = int(m.sum())
        if cnt < 100:
            continue
        ys, xs = np.where(m)
        if not (xs.max() < 95 or xs.min() > 415):
            continue
        alpha[m] = 0
        removed_speck += cnt
    if removed_speck:
        print(f"[clean] 发丝间隙背景白点: {removed_speck} px")

    # 收尾: 与透明区相邻的残余亮像素两轮清扫(覆盖前面各步的边缘衔接)
    for _ in range(2):
        near_clear = ndimage.binary_dilation(alpha == 0, iterations=1)
        edge_band = (lum >= 225) & (sat <= 16) & near_clear & (alpha > 0)
        alpha[edge_band] = 0

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
