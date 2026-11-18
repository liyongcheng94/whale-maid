"""R107 SRS 间隔复习测试:错题次日必复习;答对 3 天后的题衰减重测;新题补位到 4。"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import learn_routes  # noqa: E402
import store  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)
CHILD = "srs-test"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA", tmp_path)
    monkeypatch.setattr(learn_routes.store, "DATA", tmp_path)
    learn_routes.LEARN_SESSIONS.clear()
    yield
    learn_routes.LEARN_SESSIONS.clear()


def _learn_session(days_ago, qid, correct):
    import time as t
    ts = t.strftime("%Y-%m-%d %H:%M:%S", t.localtime(t.time() - days_ago * 86400))
    return {"ts": ts, "qid": qid, "topic": "m_addsub_rel", "level": "m1-1",
            "correct": correct, "time_s": 2}


class TestSRS:
    def test_昨日错题进今日挑战(self, tmp_path, monkeypatch):
        monkeypatch.setattr(store, "DATA", tmp_path)
        monkeypatch.setattr(learn_routes.store, "DATA", tmp_path)
        learn = store.load_learn(CHILD)
        learn["sessions"] = [_learn_session(1, "a11", False)]
        store.save_learn(CHILD, learn)
        body = client.get("/api/learn/daily", params={"child": CHILD}).json()
        assert "a11" in [q["qid"] for q in body["questions"]]

    def test_答对3天衰减重测(self, tmp_path, monkeypatch):
        monkeypatch.setattr(store, "DATA", tmp_path)
        monkeypatch.setattr(learn_routes.store, "DATA", tmp_path)
        learn = store.load_learn(CHILD)
        learn["sessions"] = [_learn_session(4, "a11", True)]  # 4 天前答对 → 衰减复习
        store.save_learn(CHILD, learn)
        body = client.get("/api/learn/daily", params={"child": CHILD}).json()
        assert "a11" in [q["qid"] for q in body["questions"]]

    def test_昨天刚答对不重测(self, tmp_path, monkeypatch):
        monkeypatch.setattr(store, "DATA", tmp_path)
        monkeypatch.setattr(learn_routes.store, "DATA", tmp_path)
        learn = store.load_learn(CHILD)
        learn["sessions"] = [_learn_session(0, "a11", True)]  # 今天刚答对
        store.save_learn(CHILD, learn)
        body = client.get("/api/learn/daily", params={"child": CHILD}).json()
        assert "a11" not in [q["qid"] for q in body["questions"]]

    def test_总题数保持4(self, tmp_path, monkeypatch):
        monkeypatch.setattr(store, "DATA", tmp_path)
        monkeypatch.setattr(learn_routes.store, "DATA", tmp_path)
        learn = store.load_learn(CHILD)
        learn["sessions"] = [_learn_session(1, "a11", False), _learn_session(4, "a12", True)]
        store.save_learn(CHILD, learn)
        body = client.get("/api/learn/daily", params={"child": CHILD}).json()
        assert len(body["questions"]) == 4
