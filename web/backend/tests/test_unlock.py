"""R25 单元解锁链测试(结构性):首单元直接解锁,后续单元需前一可玩单元全通关。"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import learn_routes  # noqa: E402
import store  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)
CHILD = "unlock-test"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA", tmp_path)
    monkeypatch.setattr(learn_routes.store, "DATA", tmp_path)
    learn_routes.LEARN_SESSIONS.clear()
    yield
    learn_routes.LEARN_SESSIONS.clear()


def _finish(child, session, level):
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


def test_首单元解锁_后续锁定():
    m = client.get("/api/learn/map", params={"child": CHILD}).json()
    st = {u["name"]: u for u in m["units"]}
    assert st["四则运算"]["unlocked"] is True
    assert st["运算定律"]["unlocked"] is False


def test_通关后解锁下一单元():
    for s, lv in [("a", "m1-1"), ("b", "m1-2"), ("c", "m1-3")]:
        _finish(CHILD, s, level=lv)
    m = client.get("/api/learn/map", params={"child": CHILD}).json()
    st = {u["name"]: u for u in m["units"]}
    assert st["四则运算"]["unlocked"] is True and st["四则运算"]["done_n"] == 3
    assert st["运算定律"]["unlocked"] is True
    assert st["小数的意义和性质"]["unlocked"] is False


def test_planned单元恒锁():
    m = client.get("/api/learn/map", params={"child": CHILD}).json()
    st = {u["name"]: u for u in m["units"]}
    assert st["观察物体(二)"]["unlocked"] is False
