"""playlist.json 机器合同(歌单单一来源;2026-11-17 唱歌升级)。

对 config/playlist.json 做结构与磁盘对齐校验——
前端接力播放与固件 play_music 同步都依赖这份文件,坏一处就冷场。
"""

import json
import re
from pathlib import Path

import pytest

PL_PATH = Path(__file__).resolve().parents[3] / "config" / "playlist.json"
MUSIC_DIR = Path(__file__).resolve().parents[3] / "assets_audio" / "music"
PL = json.loads(PL_PATH.read_text(encoding="utf-8"))

GROUP_ORDER = ("birthday", "hachimi", "songs")  # 组顺序即路由优先级


class TestPlaylistContract:
    def test_组名合法且顺序即优先级(self):
        assert list(PL["groups"].keys()) == list(GROUP_ORDER)

    def test_每首歌必备字段(self):
        for gname, g in PL["groups"].items():
            assert isinstance(g.get("keywords"), list) and g["keywords"], f"{gname} 缺 keywords"
            for s in g["songs"]:
                assert re.fullmatch(r"[a-z0-9_]+\.(m4a|mp3)", s["file"]), f"{gname}/{s['file']} 命名不合规"
                assert s.get("title"), f"{gname}/{s['file']} 缺 title"
                assert s.get("alias"), f"{gname}/{s['file']} 缺 alias(点歌名匹配集)"
                assert s.get("source"), f"{gname}/{s['file']} 缺 source(溯源)"

    def test_alias不跨组冲突(self):
        """同一 alias 只能命中一首歌,否则点歌路由歧义。"""
        seen = {}
        for gname, g in PL["groups"].items():
            for s in g["songs"]:
                for a in s.get("alias", []):
                    low = a.lower()
                    assert low not in seen, f"alias「{a}」跨组冲突: {seen[low]} vs {gname}"
                    seen[low] = gname

    def test_file与磁盘对齐(self):
        """file 必须真实存在于 assets_audio/music/(前端 404 回落是兜底,不是借口)。"""
        if not MUSIC_DIR.exists():
            pytest.skip("歌单音频未入库的环境(CI)")
        on_disk = {f.name for f in MUSIC_DIR.iterdir() if f.suffix in (".m4a", ".mp3")}
        for gname, g in PL["groups"].items():
            for s in g["songs"]:
                assert s["file"] in on_disk, f"{gname}/{s['file']} 登记了但磁盘缺失"

    def test_磁盘孤儿文件登记(self):
        """入库未登记的文件 = 永远播不到的死资产(警告级:不 fail,但 CI 会提醒)。"""
        if not MUSIC_DIR.exists():
            pytest.skip("歌单音频未入库的环境(CI)")
        registered = {s["file"] for g in PL["groups"].values() for s in g["songs"]}
        orphans = [f.name for f in MUSIC_DIR.iterdir()
                   if f.suffix in (".m4a", ".mp3") and f.name not in registered]
        assert not orphans, f"磁盘有未登记歌曲: {orphans}(跑 music_fetch.py --sync 或手动登记)"

    def test_生日组优先于泛化词(self):
        """「生日歌」必须是 birthday 组 alias/keyword,避免被 songs 组泛化词抢路由。"""
        b = PL["groups"]["birthday"]
        assert "生日歌" in b["keywords"] and "生日歌" in b["songs"][0]["alias"]
