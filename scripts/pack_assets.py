# -*- coding: utf-8 -*-
"""R136 阶段二: 小鲸灵学园 assets.bin 生成器(对照 78/xiaozhi-assets-generator SpiffsGenerator.js 逐行移植)。

格式:
  header: total_files(4) + checksum(4, 16bit 求和截断) + combined_data_length(4)
  mmap_table: 每文件 44B = name[32] + size(4) + offset(4) + width(2) + height(2),按扩展名+文件名排序
  file_data: 每文件前缀 0x5A 0x5A + 原始文件数据(PNG 原样内嵌)

用法: python pack_assets.py
输入: config/assets_source/ 下的 PNG(表情集,文件名=官方情绪名)
输出: xueyuan_assets.bin → 烧写至 assets 分区 0x800000
"""
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "config" / "assets_source"
OUT = ROOT / "tools" / "xueyuan_assets.bin"

# 学园表情集 → 官方表情名映射(xiaozhi 情绪集)
EMOJI_MAP = {
    "neutral.png": "neutral",
    "happy.png": "happy",
    "laughing.png": "laughing",
    "sad.png": "sad",
    "angry.png": "angry",
    "crying.png": "crying",
    "loving.png": "loving",
    "embarrassed.png": "embarrassed",
    "surprised.png": "surprised",
    "shocked.png": "shocked",
    "thinking.png": "thinking",
    "winking.png": "winking",
    "cool.png": "cool",
    "relaxed.png": "relaxed",
    "delicious.png": "delicious",
    "sleepy.png": "sleepy",
}

DISPLAY_W = 412
DISPLAY_H = 412


def png_size(data: bytes):
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        w = int.from_bytes(data[16:18], "big")
        h = int.from_bytes(data[18:20], "big")
        return w, h
    return 0, 0


def compute_checksum(data: bytes) -> int:
    return sum(data) & 0xFFFF


def main():
    files = []  # (entry_name.png, data, w, h)
    for png in sorted(SRC_DIR.glob("*.png")):
        entry = EMOJI_MAP.get(png.name)
        if entry is None:
            continue
        data = png.read_bytes()
        w, h = png_size(data)
        files.append((entry + ".png", data, w, h))

    if not files:
        print("assets_source/ 没有 PNG")
        return 1

    # R136 修复:index.json 必须内嵌(固件 assets.cc 强依赖 index.json)
    index_json = (ROOT / "config" / "assets_index_example.json").read_bytes()
    files.insert(0, ("index.json", index_json, 0, 0))

    # 排序:扩展名(全部 png)→ 文件名(与 JS sortFiles 一致)
    files.sort(key=lambda f: (f[0].rsplit(".", 1)[-1], f[0].rsplit(".", 1)[0]))

    total_files = len(files)
    file_info_list = []
    merged_data_size = 0
    for fname, fdata, w, h in files:
        file_info_list.append({"filename": fname, "data": fdata, "size": len(fdata),
                               "offset": merged_data_size, "width": w, "height": h})
        merged_data_size += 2 + len(fdata)

    # 映射表:44B/文件
    mmap = bytearray()
    for fi in file_info_list:
        mmap += fi["filename"].encode("utf-8")[:32].ljust(32, b"\x00")
        mmap += struct.pack("<I", fi["size"])
        mmap += struct.pack("<I", fi["offset"])
        mmap += struct.pack("<H", fi["width"])
        mmap += struct.pack("<H", fi["height"])

    # 合并文件数据(0x5A5A 前缀)
    merged = bytearray()
    for fi in file_info_list:
        merged += b"\x5A\x5A" + fi["data"]

    checksum = compute_checksum(mmap + merged)
    combined_len = len(mmap) + len(merged)

    out = bytearray()
    out += struct.pack("<I", total_files)
    out += struct.pack("<I", checksum)
    out += struct.pack("<I", combined_len)
    out += mmap + merged

    OUT.write_bytes(out)
    print(f"OK {total_files} files -> {OUT} ({len(out)} bytes)")
    for fi in file_info_list:
        print(f"  {fi['filename']:20s} {fi['width']}x{fi['height']} {fi['size']}B")

    # 生成配套 index.json(供参考/固件 index 解析对照;官方生成器同款结构)
    index = {
        "version": 1,
        "chip_model": "esp32s3",
        "display_config": {"width": DISPLAY_W, "height": DISPLAY_H,
                           "monochrome": False, "color": "RGB565"},
        "emoji_collection": [{"name": fi["filename"].rsplit(".", 1)[0],
                              "file": fi["filename"]} for fi in file_info_list],
        "skin": {"light": {"text_color": "#FFFFFF", "background_color": "#0B3D66"},
                 "dark": {"text_color": "#FFFFFF", "background_color": "#072A4A"}},
    }
    (ROOT / "config" / "assets_index_example.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    print("index example -> config/assets_index_example.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
