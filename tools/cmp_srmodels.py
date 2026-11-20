# -*- coding: utf-8 -*-
"""对比各档 assets.bin 内 srmodels.bin 条目的 md5,定位唤醒模型装错档位。"""
import hashlib
import struct
from pathlib import Path

def extract_srmodels(path):
    data = Path(path).read_bytes()
    n, _, stored = struct.unpack("<III", data[:12])
    off = 12
    for _ in range(n):
        name = data[off:off + 32].rstrip(b"\x00").decode()
        size, foff = struct.unpack("<II", data[off + 32:off + 40])
        if name == "srmodels.bin":
            start = 12 + 44 * n + 2 + foff
            return hashlib.md5(data[start:start + size]).hexdigest(), size
        off += 44
    return None, 0

refs = {}
for p in [Path(r"D:\project\whale-maid\tools\srmodels_xiaoai.bin"),
          Path(r"D:\project\whale-maid\tools\official_files\srmodels.bin")]:
    refs[hashlib.md5(p.read_bytes()).hexdigest()] = f"{p.name} ({p.stat().st_size}B)"

for b in ["64", "128", "240", "412"]:
    h, s = extract_srmodels(Path(rf"D:\project\whale-maid\tools\xueyuan_assets_{b}.bin"))
    match = refs.get(h, "NO-MATCH")
    print(f"{b}: srmodels {s}B md5={h[:10]} -> {match}")
print("refs:", {k[:10]: v for k, v in refs.items()})
