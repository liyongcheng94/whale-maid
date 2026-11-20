# -*- coding: utf-8 -*-
"""为服务端 play_music 生成中文名硬链接目录(R139)。

服务端 plugins_func/functions/play_music.py 用 difflib 对**文件名**模糊匹配歌名,
而 assets_audio/music/ 里是英文文件名(song_01_guyongzhe.m4a)——语音说「孤勇者」永远匹配不上。
本脚本读 config/playlist.json(歌单机器合同),把每首歌硬链接为干净中文文件名:
  assets_audio/music_cn/孤勇者.m4a  ←  assets_audio/music/song_01_guyongzhe.m4a
同名冲突加序号;已存在则先清空重建(幂等)。硬链接零拷贝占盘。

用法:python scripts/link_music_for_server.py
产物目录配到服务端 data/.config.yaml 的 plugins.play_music.music_dir。
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLAYLIST = ROOT / "config" / "playlist.json"
SRC_DIR = ROOT / "assets_audio" / "music"
DST_DIR = ROOT / "assets_audio" / "music_cn"


def clean_name(song: dict) -> str:
    """取《》内歌名;无书名号则清洗 bilibili 式长标题;剥离文件系统非法字符。"""
    title = song.get("title", "")
    m = re.search(r"《([^《》]+)》", title)
    if m:
        name = m.group(1)
    else:
        # 无书名号:按 丨/-/— 分段,取 CJK 最多的段(bilibili 下载标题常带「4K极致修复丨」前缀)
        segs = re.split(r"[丨\-—]", title)
        best = max(segs, key=lambda s: sum("\u4e00" <= c <= "\u9fff" for c in s), default=title)
        name = best or title
        name = re.sub(r"MV|2160P|1080P|Hi-?Res|4K|歌词|无损|修复|极致", "", name, flags=re.I)
    name = re.sub(r'[\\/:*?"<>|【】\s⚡️\ufe0f]+', "", name).strip("-~—'“”‘’")
    return name or Path(song["file"]).stem


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    data = json.loads(PLAYLIST.read_text(encoding="utf-8"))
    DST_DIR.mkdir(parents=True, exist_ok=True)
    for old in DST_DIR.iterdir():
        old.unlink()

    seen: dict[str, int] = {}
    linked = 0
    for group, g in data["groups"].items():
        for song in g["songs"]:
            src = SRC_DIR / song["file"]
            if not src.exists():
                print(f"✗ 缺源文件: {src}")
                continue
            name = clean_name(song)
            n = seen.get(name, 0)
            seen[name] = n + 1
            if n:
                name = f"{name}{n + 1}"
            dst = DST_DIR / f"{name}{src.suffix}"
            try:
                # Windows: os.link 需同卷(同在 D:)且目标不存在
                import os
                os.link(src, dst)
                linked += 1
                print(f"✓ {dst.name}  ←  {song['file']}  [{group}]")
            except OSError as e:
                print(f"✗ 硬链接失败 {dst.name}: {e}")
    print(f"\n完成:{linked} 首 → {DST_DIR}")
    return 0 if linked else 1


if __name__ == "__main__":
    sys.exit(main())
