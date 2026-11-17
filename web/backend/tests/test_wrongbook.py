"""R28/R29 测试:家长正确率字段 + 孩子错题本端点。"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import learn_routes  # noqa: E402
import store  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)
CHILD = "ranran"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA", tmp_path)
    monkeypatch.setattr(learn_routes.store, "DATA", tmp_path)
    learn_routes.LEARN_SESSIONS.clear()
    yield
    learn_routes.LEARN_SESSIONS.clear()


def test_错题本去重倒序():
    client.get("/api/learn/next", params={"child": CHILD, "level": "m1-1", "session": "wb"})
    for _ in range(4):
        qid = learn_routes.LEARN_SESSIONS[(CHILD, "wb")]["seen"][-1]
        client.post("/api/learn/answer", json={
            "child": CHILD, "session": "wb", "qid": qid, "answer": "99999", "time_s": 1})
    body = client.get("/api/learn/wrongbook", params={"child": CHILD}).json()
    assert body["items"], "错题本应有条目"
    qids = [i["qid"] for i in body["items"]]
    assert len(qids) == len(set(qids))  # 去重
    assert all(i["scaffold"] for i in body["items"])


def test_家长端正确率字段():
    tok = client.post("/api/parent/pin/setup", json={"pin": "2468"}).json()["token"]
    client.get("/api/learn/next", params={"child": CHILD, "level": "m1-1", "session": "acc"})
    qid = learn_routes.LEARN_SESSIONS[(CHILD, "acc")]["seen"][-1]
    client.post("/api/learn/answer", json={
        "child": CHILD, "session": "acc", "qid": qid, "answer": "99999", "time_s": 5})
    ov = client.get("/api/parent/overview", params={"token": tok}).json()
    card = next(c for c in ov["cards"] if c["child"] == CHILD)
    assert card["week_accuracy"] == 0.0  # 一次全错
