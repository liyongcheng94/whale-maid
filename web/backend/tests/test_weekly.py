"""R130 学而思式 LLM 周报测试:聚合事实→描述性总结(token 保护;无 key 走事实兜底)。"""
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
    return client.post("/api/parent/pin/setup", json={"pin": "5555"}).json()["token"]


def test_无记录兜底文案(tok, tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA", tmp_path)
    monkeypatch.setattr(learn_routes.store, "DATA", tmp_path)
    r = client.post("/api/parent/weekly-summary", params={"token": tok},
                    json={"child": CHILD})
    assert r.status_code == 200
    assert "还没有学习记录" in r.json()["summary"]


def test_有记录生成事实兜底(tok, tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA", tmp_path)
    monkeypatch.setattr(learn_routes.store, "DATA", tmp_path)
    import time as t
    learn = store.load_learn(CHILD)
    for i in range(4):
        ts = t.strftime("%Y-%m-%d %H:%M:%S", t.localtime(t.time() - (i % 3) * 86400))
        learn["sessions"].append({"ts": ts, "qid": f"q{i}", "topic": "m_addsub_rel",
                                  "level": "m1-1", "correct": i % 2 == 0, "time_s": 60})
    store.save_learn(CHILD, learn)
    r = client.post("/api/parent/weekly-summary", params={"token": tok},
                    json={"child": CHILD})
    body = r.json()
    assert "分钟" in body["summary"] and body["facts"]["answers"] == 4


def test_无token401(tok):
    assert client.post("/api/parent/weekly-summary", params={"token": ""},
                       json={"child": CHILD}).status_code == 401
