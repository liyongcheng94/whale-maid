"""R1 习惯打卡星星系统测试(docs/10)。

口径:打卡 = data/stars.json 持久化 +1;同任务 60s 窗口内重复不加分(防连点);
非法 task 400;夸奖台词池/序号对齐预生成音频。测试用临时 STARS_FILE 隔离。
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # noqa: E402
import main  # noqa: E402
from main import STAR_TASKS, app  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "STARS_FILE", tmp_path / "stars.json")
    return TestClient(app)


class TestStarsApi:
    def test_初始状态为空(self, client):
        body = client.get("/api/stars").json()
        assert body["total"] == 0 and body["today"] == 0
        assert set(body["tasks"]) == set(STAR_TASKS)

    def test_打卡加分与持久化(self, client, tmp_path):
        r1 = client.post("/api/stars", json={"task": "brush"}).json()
        assert r1["added"] == 1 and r1["total"] == 1 and r1["pool"] == "star_praise"
        r2 = client.post("/api/stars", json={"task": "tidy"}).json()
        assert r2["total"] == 2
        # 持久化:同文件再读
        again = client.get("/api/stars").json()
        assert again["total"] == 2 and again["today"] == 2
        assert (tmp_path / "stars.json").exists()

    def test_同任务60秒窗口防连点(self, client):
        r1 = client.post("/api/stars", json={"task": "brush"}).json()
        r2 = client.post("/api/chat" if False else "/api/stars", json={"task": "brush"}).json()
        assert r1["added"] == 1 and r2["added"] == 0
        assert r2["pool"] == "star_repeat" and r2["total"] == r1["total"]

    def test_非法任务400(self, client):
        assert client.post("/api/stars", json={"task": "hack"}).status_code == 400

    def test_夸奖台词非空且表情为开心(self, client):
        body = client.post("/api/stars", json={"task": "sleep"}).json()
        assert body["reply"].strip() and body["emo"] == "happy"

    def test_日志记录任务标签(self, client, tmp_path):
        client.post("/api/stars", json={"task": "tidy"})
        import json
        data = json.loads((tmp_path / "stars.json").read_text(encoding="utf-8"))
        assert data["log"][0]["label"] == "收拾玩具"
