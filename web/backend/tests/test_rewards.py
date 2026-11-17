"""R8/R9 奖励系统测试:首通+30/重复+5/每日完成+20;单元徽章只增不消耗。"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import learn_routes  # noqa: E402
import store  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)
CHILD = "reward-test"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA", tmp_path)
    monkeypatch.setattr(learn_routes.store, "DATA", tmp_path)
    learn_routes.LEARN_SESSIONS.clear()
    yield
    learn_routes.LEARN_SESSIONS.clear()


def _finish_level(child, session):
    client.get("/api/learn/next", params={"child": child, "level": "m1-1", "session": session})
    for _ in range(10):
        qid = learn_routes.LEARN_SESSIONS[(child, session)]["seen"][-1]
        ans = learn_routes._ALL_Q[qid]["answer"]
        body = client.post("/api/learn/answer", json={
            "child": child, "session": session, "qid": qid,
            "answer": str(ans), "time_s": 2}).json()
        if body.get("done"):
            return body
    raise AssertionError("未触发终局")


def test_首通奖励30并入XP():
    xp0 = store.load_learn(CHILD)["xp"]
    body = _finish_level(CHILD, "r1")
    assert body["xp_bonus"] == 30
    assert store.load_learn(CHILD)["xp"] == xp0 + body["xp_gain"] + 30


def test_重复通关奖励降为5():
    _finish_level(CHILD, "r2")
    body = _finish_level(CHILD, "r3")
    assert body["xp_bonus"] == 5


def test_单元徽章解锁且只增不消耗():
    _finish_level(CHILD, "r4")
    learn = store.load_learn(CHILD)
    assert "四则运算骑士" in learn["badges"]
    _finish_level(CHILD, "r5")
    assert store.load_learn(CHILD)["badges"].count("四则运算骑士") == 1


def test_地图返回徽章():
    _finish_level(CHILD, "r6")
    m = client.get("/api/learn/map", params={"child": CHILD}).json()
    assert "四则运算骑士" in m["badges"]
