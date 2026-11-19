"""R121-R123 测试:错题重做后错题本刷新数据 + 家长总览错因统计。"""
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
    return client.post("/api/parent/pin/setup", json={"pin": "8080"}).json()["token"]


def test_带错因的会话进统计(tok, tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA", tmp_path)
    monkeypatch.setattr(learn_routes.store, "DATA", tmp_path)
    import time as t
    learn = store.load_learn(CHILD)
    ts = t.strftime("%Y-%m-%d %H:%M:%S")
    learn["sessions"] = [
        {"ts": ts, "qid": "a11", "topic": "m_addsub_rel", "level": "m1-1",
         "correct": False, "time_s": 2, "error_type": "计算"},
        {"ts": ts, "qid": "a12", "topic": "m_addsub_rel", "level": "m1-1",
         "correct": False, "time_s": 2, "error_type": "计算"},
        {"ts": ts, "qid": "a13", "topic": "m_addsub_rel", "level": "m1-1",
         "correct": False, "time_s": 2, "error_type": "审题"},
    ]
    store.save_learn(CHILD, learn)
    ov = client.get("/api/parent/overview", params={"token": tok}).json()
    card = next(c for c in ov["cards"] if c["child"] == CHILD)
    assert card["error_types"] == {"计算": 2, "审题": 1}


def test_无错因时统计为空(tok, tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA", tmp_path)
    monkeypatch.setattr(learn_routes.store, "DATA", tmp_path)
    ov = client.get("/api/parent/overview", params={"token": tok}).json()
    card = next(c for c in ov["cards"] if c["child"] == CHILD)
    assert card["error_types"] == {}
