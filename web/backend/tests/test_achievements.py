"""R48-R52 成就墙测试:里程碑徽章(七日/百题/错题清零)只增不消耗+成就墙端点。"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import learn_routes  # noqa: E402
import store  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)
CHILD = "achv-test"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA", tmp_path)
    monkeypatch.setattr(learn_routes.store, "DATA", tmp_path)
    learn_routes.LEARN_SESSIONS.clear()
    yield
    learn_routes.LEARN_SESSIONS.clear()


def _day(n):
    import time as t
    return t.strftime("%Y-%m-%d %H:%M:%S", t.localtime(t.time() - n * 86400))


def test_百题徽章():
    learn = store.load_learn(CHILD)
    learn["sessions"] = [{"ts": _day(0), "qid": f"q{i}", "topic": "m_addsub_rel",
                          "level": "m1-1", "correct": True, "time_s": 1} for i in range(100)]
    store.save_learn(CHILD, learn)
    learn2 = store.load_learn(CHILD)
    learn_routes._milestone_badges(learn2)
    store.save_learn(CHILD, learn2)
    assert "百题斩" in store.load_learn(CHILD)["badges"]


def test_七日连续徽章():
    learn = store.load_learn(CHILD)
    for n in range(7):
        learn["sessions"].append({"ts": _day(n), "qid": f"d{n}", "topic": "m_addsub_rel",
                                  "level": "m1-1", "correct": True, "time_s": 1})
    store.save_learn(CHILD, learn)
    learn2 = store.load_learn(CHILD)
    learn_routes._milestone_badges(learn2)
    store.save_learn(CHILD, learn2)
    assert "七日不辍" in store.load_learn(CHILD)["badges"]


def test_错题清零徽章():
    learn = store.load_learn(CHILD)
    learn["sessions"] = [
        {"ts": _day(2), "qid": "a11", "topic": "m_addsub_rel", "level": "m1-1", "correct": False, "time_s": 1},
        {"ts": _day(1), "qid": "a12", "topic": "m_addsub_rel", "level": "m1-1", "correct": False, "time_s": 1},
        {"ts": _day(0), "qid": "a11", "topic": "m_addsub_rel", "level": "m1-1", "correct": True, "time_s": 1},
        {"ts": _day(0), "qid": "a12", "topic": "m_addsub_rel", "level": "m1-1", "correct": True, "time_s": 1},
    ]
    # 再补一些正确记录(≥10 会话门槛)
    for i in range(8):
        learn["sessions"].append({"ts": _day(0), "qid": f"ok{i}", "topic": "m_addsub_rel",
                                  "level": "m1-1", "correct": True, "time_s": 1})
    store.save_learn(CHILD, learn)
    learn2 = store.load_learn(CHILD)
    learn_routes._check_wrongbook_clear(learn2)
    store.save_learn(CHILD, learn2)
    assert "错题清零大师" in store.load_learn(CHILD)["badges"]


def test_成就墙端点字段():
    body = client.get("/api/learn/achievements", params={"child": CHILD}).json()
    assert set(body) >= {"badges", "streak_days", "daily_streak", "total_answers", "wrong_left"}
