# -*- coding: utf-8 -*-
"""重建学园 assets.bin(官方底座 + 鲸鱼娘表情集,阶梯尺寸)。

用法:python rebuild_assets.py [size]  # size ∈ 64|128|240,默认 64(官方基线档)
index.json 从零构建(srmodels/text_font/skin/display_config 字段与官方口径一致)。
产物:tools/xueyuan_assets_{size}.bin——烧录前必须过 scripts/validate_assets.py。
"""
import json
import sys
from pathlib import Path

SIZE = int(sys.argv[1]) if len(sys.argv) > 1 else 64
OFFICIAL = Path(r"D:\project\whale-maid\tools\official_files")
SRC = Path(rf"D:\project\whale-maid\config\assets_source_{SIZE}")
OUT = Path(rf"D:\project\whale-maid\tools\xueyuan_assets_{SIZE}.bin")

# ---- 1. 收集文件:官方底座(srmodels/字体/背景) + 鲸鱼娘 16 情绪 PNG ----
all_files = {}
for f in sorted(OFFICIAL.iterdir()):
    if f.name == "index.json":
        continue  # 官方 index.json 提取不完整,弃用;自建完整版
    all_files[f.name] = f.read_bytes()

EMOTIONS = ["neutral", "happy", "laughing", "sad", "angry", "crying", "loving",
            "embarrassed", "surprised", "shocked", "thinking", "winking", "cool",
            "relaxed", "delicious", "sleepy"]
for name in EMOTIONS:
    p = SRC / (name + ".png")
    if p.exists():
        all_files[name + ".png"] = p.read_bytes()

# ---- 2. index.json(学园版) ----
emoji_collection = [{"name": name.rsplit(".", 1)[0], "file": name}
                    for name in sorted(all_files) if name.endswith(".png")]
final_index = {
    "version": 1,
    "chip_model": "esp32s3",
    "display_config": {"width": 412, "height": 412, "monochrome": False, "color": "RGB565"},
    "srmodels": "srmodels.bin",
    "text_font": "font_noto_sans_common_16_4.bin",
    "emoji_collection": emoji_collection,
    "skin": {"light": {"text_color": "#FFFFFF", "background_color": "#0B3D66"},
             "dark": {"text_color": "#FFFFFF", "background_color": "#072A4A"}},
}
all_files["index.json"] = json.dumps(final_index, ensure_ascii=False, indent=2).encode("utf-8")

# ---- 3. 打包(map: name[32]+size(4)+offset(4)+w(2)+h(2);数据前缀 0x5A5A) ----
entries = []
merged = bytearray()
for name in sorted(all_files):
    data = all_files[name]
    w = h = 0
    if name.endswith(".png"):
        w = int.from_bytes(data[16:18], "big")
        h = int.from_bytes(data[18:20], "big")
    entries.append((name, len(data), len(merged), w, h))
    merged += b"\x5a\x5a" + data

mmap = bytearray()
for name, size, foff, w, h in entries:
    mmap += name.encode("utf-8")[:32].ljust(32, b"\x00")
    mmap += size.to_bytes(4, "little")
    mmap += foff.to_bytes(4, "little")
    mmap += w.to_bytes(2, "little")
    mmap += h.to_bytes(2, "little")

combined = bytes(mmap) + bytes(merged)
checksum = sum(combined) & 0xFFFF

out = bytearray()
out += len(entries).to_bytes(4, "little")
out += checksum.to_bytes(4, "little")
out += len(combined).to_bytes(4, "little")
out += combined
OUT.write_bytes(out)

print(f"OK {len(entries)} files -> {OUT} ({len(out)}B)")
for name, size, foff, w, h in entries:
    print(f"  {name:40s} {size:8d}B {w}x{h}")
