"""R38/R40 副屏测试:sub 摘要端点(token)+孩子端当前任务上报。"""
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


@pytest.fixture()
def tok(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA", tmp_path)
    monkeypatch.setattr(learn_routes.store, "DATA", tmp_path)
    learn_routes.LEARN_SESSIONS.clear()
    return client.post("/api/parent/pin/setup", json={"pin": "1357"}).json()["token"]


def test_当前任务上报(tok, isolated=None):
    r = client.post("/api/learn/current", json={"child": CHILD, "level": "m1-1"})
    assert r.status_code == 200
    learn = store.load_learn(CHILD)
    assert learn["current"]["name"] == "加减法的意义与关系"


def test_副屏摘要(tok):
    client.post("/api/learn/current", json={"child": CHILD, "level": "m1-1"})
    r = client.get("/api/parent/sub", params={"child": CHILD, "token": tok})
    body = r.json()
    assert r.status_code == 200
    assert body["name"] == "冉冉" and body["today_answers"] == 0
    assert "name" in body["current"]


def test_副屏需要token(tok):
    assert client.get("/api/parent/sub", params={"child": CHILD, "token": ""}).status_code == 401
