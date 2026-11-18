"""R103 语文角测试:每日 3 词(日期种子可复现)+音频预生成+端点。"""
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import store  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)
CHILD = "cn-test"
ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA", tmp_path)
    monkeypatch.setattr(__import__("learn_routes").store, "DATA", tmp_path)
    yield


class TestChineseCorner:
    def test_每日三词可复现(self):
        a = client.get("/api/learn/chinese/daily", params={"child": CHILD}).json()
        b = client.get("/api/learn/chinese/daily", params={"child": CHILD}).json()
        assert [w["word"] for w in a["words"]] == [w["word"] for w in b["words"]]
        assert len(a["words"]) == 3

    def test_音频三件套预生成(self):
        mp3 = ROOT / "assets_audio" / "mp3"
        if not mp3.exists():
            pytest.skip("音频未生成的环境")
        data = json.loads((ROOT / "config" / "chinese_words.json").read_text(encoding="utf-8"))
        for w in data["words"]:
            assert (mp3 / f"chinese_{w['word']}.mp3").exists()
            assert (mp3 / f"chinese_{w['word']}_sent.mp3").exists()
