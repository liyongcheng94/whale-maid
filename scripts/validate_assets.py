# -*- coding: utf-8 -*-
"""主机端 assets.bin 校验器(Phase D 独立证明者)。

与固件 main/assets.cc LvglStrategy::InitializePartition 同口径逐项校验,烧录前拦截格式 bug:
  1. 头部 12B:total_files(u32)+checksum(u32)+stored_len(u32),小端
  2. 表区:每文件 44B(name[32]+size(4)+offset(4)+width(2)+height(2))
  3. 数据区起始 = 12 + 44*N;offset 相对数据区;每文件数据 0x5A5A 前缀
  4. checksum = [12, 12+stored_len) 逐字节求和 & 0xFFFF
  5. index.json 可解析且 version<=1;emoji_collection 项含 name/file 且无 eaf 键
  6. srmodels/text_font 指向的文件存在;PNG 魔数正确
  7. stored_len == 44*N + Σ(2+size);总长不超分区(默认 8MB)

用法:python scripts/validate_assets.py <assets.bin> [分区大小字节,默认 0x800000]
退出码 0=全部通过;非 0=列出全部问题。
"""

import json
import struct
import sys
from pathlib import Path


def validate(path: str, partition_size: int = 0x800000):
    problems = []
    data = Path(path).read_bytes()
    n = len(data)

    # 1. 头部
    if n < 12:
        return [f"文件过小({n}B),连 12B 头都不够"]
    total_files, checksum, stored_len = struct.unpack_from("<III", data, 0)
    if total_files == 0:
        problems.append("total_files = 0")
    if total_files > 1000:
        problems.append(f"total_files 异常大:{total_files}")

    # 2. 表区与数据区边界
    table_end = 12 + 44 * total_files
    if table_end > n:
        problems.append(f"表区越界:需要 {table_end}B,文件仅 {n}B")
        return problems

    # 3. 逐条目解析
    entries = {}
    for i in range(total_files):
        off = 12 + 44 * i
        raw_name = data[off:off + 32]
        if b"\x00" in raw_name:
            name = raw_name.split(b"\x00")[0].decode("utf-8", errors="replace")
        else:
            name = raw_name.decode("utf-8", errors="replace")
            problems.append(f"条目 {i}:name 未以 NUL 结束(可能超 32B 截断)")
        size, foff, w, h = struct.unpack_from("<IIHH", data, off + 32)
        entries[name] = (size, foff, w, h)
        # 数据区校验
        data_off = table_end + foff
        if data_off + 2 + size > n:
            problems.append(f"{name}:数据越界(需要至 {data_off + 2 + size},文件 {n})")
            continue
        prefix = data[data_off:data_off + 2]
        if prefix != b"\x5a\x5a":
            problems.append(f"{name}:数据前缀非 0x5A5A(实际 {prefix.hex()})")

    # 4. 长度一致性
    expected_len = 44 * total_files + sum(2 + s for s, _, _, _ in entries.values())
    if stored_len != expected_len:
        problems.append(f"stored_len 不符:头声明 {stored_len},实际应为 {expected_len}")
    if 12 + stored_len > n:
        problems.append(f"12+stored_len({12 + stored_len}) 超文件长度({n})")

    # 5. checksum
    calc = sum(data[12:12 + stored_len]) & 0xFFFF
    if calc != checksum:
        problems.append(f"checksum 不符:头声明 {checksum}(0x{checksum:04x}),计算得 {calc}(0x{calc:04x})")

    # 6. 分区容量
    if n > partition_size:
        problems.append(f"总大小 {n}B 超过分区 {partition_size}B")

    # 7. index.json 内容合同
    if "index.json" not in entries:
        problems.append("缺 index.json(固件强依赖)")
    else:
        size, foff, _, _ = entries["index.json"]
        blob = data[table_end + foff + 2: table_end + foff + 2 + size]
        try:
            idx = json.loads(blob.decode("utf-8"))
        except Exception as e:
            problems.append(f"index.json 解析失败:{e!r}")
            idx = None
        if idx is not None:
            if idx.get("version", 99) > 1:
                problems.append(f"index.json version={idx.get('version')}>1,固件拒绝")
            for key in ("srmodels", "text_font"):
                ref = idx.get(key)
                if isinstance(ref, str) and ref not in entries:
                    problems.append(f"index.json 引用的 {key}={ref} 不在包内")
            coll = idx.get("emoji_collection")
            if isinstance(coll, list):
                for e in coll:
                    if not (isinstance(e, dict) and isinstance(e.get("name"), str)
                            and isinstance(e.get("file"), str)):
                        problems.append(f"emoji_collection 项缺 name/file:{str(e)[:50]}")
                    elif "eaf" in e:
                        problems.append(f"{e['name']}:含 eaf 键(LVGL 板拒绝)")
                    elif e["file"] not in entries:
                        problems.append(f"{e['name']}:引用 {e['file']} 不在包内")
            else:
                problems.append("index.json 缺 emoji_collection 数组")

    # 8. PNG 魔数(表宽高 0 合法:官方打包器不填,固件解码时自解析;非 0 时须一致)
    for name, (size, foff, w, h) in entries.items():
        if name.endswith(".png"):
            blob = data[table_end + foff + 2: table_end + foff + 2 + size]
            if blob[:8] != b"\x89PNG\r\n\x1a\n":
                problems.append(f"{name}:PNG 魔数错误")
                continue
            if w or h:
                pw = int.from_bytes(blob[16:18], "big")
                ph = int.from_bytes(blob[18:20], "big")
                if (w, h) != (pw, ph):
                    problems.append(f"{name}:表声明 {w}x{h} 与 PNG 实际 {pw}x{ph} 不符")

    return problems


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    path = sys.argv[1]
    part = int(sys.argv[2], 0) if len(sys.argv) > 2 else 0x800000
    problems = validate(path, part)
    if problems:
        print(f"✗ {len(problems)} 个问题:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"✓ 全部通过:{path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
