"""R8/R9 奖励系统测试:首通+30/重复+5/每日完成+20;单元徽章(全单元关卡 done)只增不消耗。

XP 口径:每答对 10 分,连对≥3 每题+5;首通奖励 30 —— m1-1 五连对总入账 = 10+10+15+15+15+30 = 95。
"""
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


def _finish_level(child, session, level="m1-1"):
    client.get("/api/learn/next", params={"child": child, "level": level, "session": session})
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
    # m1-1 五连对:10+10+15+15+15 = 65,加首通 30 → 95
    assert store.load_learn(CHILD)["xp"] == xp0 + 65 + 30


def test_重复通关奖励降为5():
    _finish_level(CHILD, "r2")
    xp_before = store.load_learn(CHILD)["xp"]
    body = _finish_level(CHILD, "r3")
    assert body["xp_bonus"] == 5
    assert store.load_learn(CHILD)["xp"] == xp_before + 65 + 5


def test_单元徽章解锁且只增不消耗():
    """u1 徽章需要三关全通(m1-1/m1-2/m1-3)。"""
    _finish_level(CHILD, "r4a")
    assert "四则运算骑士" not in store.load_learn(CHILD).get("badges", [])  # 只通一关不给
    _finish_level(CHILD, "r4b", level="m1-2")
    _finish_level(CHILD, "r4c", level="m1-3")
    learn = store.load_learn(CHILD)
    assert "四则运算骑士" in learn["badges"]
    _finish_level(CHILD, "r4d")
    assert store.load_learn(CHILD)["badges"].count("四则运算骑士") == 1  # 幂等


def test_地图返回徽章():
    for s, lv in [("ma", "m1-1"), ("mb", "m1-2"), ("mc", "m1-3")]:
        _finish_level(CHILD, s, level=lv)
    m = client.get("/api/learn/map", params={"child": CHILD}).json()
    assert "四则运算骑士" in m["badges"]
