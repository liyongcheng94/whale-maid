"""R120 徽章获得日期测试:u1 徽章需三关全通;新徽章记录获得日期,成就墙端点下发。"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import learn_routes  # noqa: E402
import store  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)
CHILD = "date-test"


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


def test_单元徽章带日期():
    """u1 徽章需三关全通;badge_dates 记录获得日期。"""
    for s, lv in [("b1", "m1-1"), ("b2", "m1-2"), ("b3", "m1-3")]:
        _finish(CHILD, s, level=lv)
    a = client.get("/api/learn/achievements", params={"child": CHILD}).json()
    assert "四则运算骑士" in a["badges"]
    assert a["badge_dates"]["四则运算骑士"]  # 日期字符串非空
