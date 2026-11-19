"""R125 今日学情端点测试:作答数/分钟/正确率/星星(孩子端自己的旅程)。"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import learn_routes  # noqa: E402
import store  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)
CHILD = "today-test"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA", tmp_path)
    monkeypatch.setattr(learn_routes.store, "DATA", tmp_path)
    learn_routes.LEARN_SESSIONS.clear()
    yield
    learn_routes.LEARN_SESSIONS.clear()


def test_空状态():
    body = client.get("/api/learn/today", params={"child": CHILD}).json()
    assert body["answers"] == 0 and body["minutes"] == 0
    assert body["accuracy"] is None and body["xp"] == 0 and body["stars"] == 0


def test_今日作答统计(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA", tmp_path)
    client.get("/api/learn/next", params={"child": CHILD, "level": "m1-1", "session": "td"})
    qid = learn_routes.LEARN_SESSIONS[(CHILD, "td")]["seen"][-1]
    ans = learn_routes._ALL_Q[qid]["answer"]
    client.post("/api/learn/answer", json={
        "child": CHILD, "session": "td", "qid": qid, "answer": str(ans), "time_s": 30})
    body = client.get("/api/learn/today", params={"child": CHILD}).json()
    assert body["answers"] == 1
    assert body["minutes"] == 0.5
    assert body["accuracy"] == 1.0
    assert body["xp"] == 10
