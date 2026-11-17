"""R3 古诗小课堂测试(docs/10)。

口径:poems.json 每首 ≥3 句、id 全 ascii 小写、音频逐句预生成;
chat 关键词(古诗/背诗/读诗/念诗/唐诗)前置路由返回随机诗;泛聊不触发。
"""
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # noqa: E402
from main import POEMS, app  # noqa: E402

client = TestClient(app)
ROOT = Path(__file__).resolve().parents[3]


class TestPoemsContract:
    def test_诗目数量与字段(self):
        assert len(POEMS) >= 6
        for p in POEMS:
            assert p["id"].isascii() and p["id"].islower() and p["id"].isalnum()
            assert p["title"] and p["author"]
            assert len(p["lines"]) >= 3 and all(l.strip() for l in p["lines"])

    def test_音频逐句预生成(self):
        mp3 = ROOT / "assets_audio" / "mp3"
        if not mp3.exists():
            pytest.skip("音频未生成的环境")
        for p in POEMS:
            for n in range(0, len(p["lines"]) + 1):  # 0=开场,1..n=逐句
                assert (mp3 / f"poem_{p['id']}_{n}.mp3").exists(), f"缺 poem_{p['id']}_{n}.mp3"


class TestPoemApi:
    def test_随机端点返回合法诗(self):
        for _ in range(4):
            p = client.get("/api/poem/random").json()
            assert p in POEMS

    def test_背古诗路由返回诗对象(self):
        body = client.post("/api/chat", json={"text": "我们来背古诗吧"}).json()
        assert body["pool"] == "poem_start" and body["source"] == "offline"
        assert body["poem"] in POEMS

    @pytest.mark.parametrize("kw", ["背诗", "读诗", "念诗", "唐诗"])
    def test_关键词全覆盖(self, kw):
        body = client.post("/api/chat", json={"text": f"{kw}吧"}).json()
        assert body["poem"] in POEMS

    def test_泛聊不触发诗路由(self):
        body = client.post("/api/chat", json={"text": "你好呀"}).json()
        assert body.get("poem") is None
