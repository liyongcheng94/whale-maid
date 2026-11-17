"""R16/R17 家长总览增强测试:周对比(prev_week_minutes)、未学提醒(last_days_ago)。"""
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
    t = client.post("/api/parent/pin/setup", json={"pin": "4321"}).json()["token"]
    yield t


def _learn_session(days_ago: int, correct=True, time_s=60):
    import time as _t
    ts = _t.strftime("%Y-%m-%d %H:%M:%S", _t.localtime(_t.time() - days_ago * 86400))
    return {"ts": ts, "level": "m1-1", "qid": "a11", "topic": "m_addsub_rel",
            "correct": correct, "time_s": time_s}


class TestOverviewEnhanced:
    def test_周对比字段存在(self, tok):
        learn = store.load_learn(CHILD)
        learn["sessions"] = [_learn_session(2), _learn_session(9)]  # 本周 1 次,上周 1 次
        store.save_learn(CHILD, learn)
        ov = client.get("/api/parent/overview", params={"token": tok}).json()
        card = next(c for c in ov["cards"] if c["child"] == CHILD)
        assert card["week_minutes"] == 1.0 and card["prev_week_minutes"] == 1.0

    def test_两天未学出现在待处理(self, tok):
        learn = store.load_learn(CHILD)
        learn["sessions"] = [_learn_session(3)]  # 最近一次 3 天前
        store.save_learn(CHILD, learn)
        ov = client.get("/api/parent/overview", params={"token": tok}).json()
        card = next(c for c in ov["cards"] if c["child"] == CHILD)
        assert card["last_days_ago"] == 3
        assert any("还没" in p or "陪" in p for p in card["pending"])

    def test_天天学不提醒(self, tok):
        learn = store.load_learn(CHILD)
        learn["sessions"] = [_learn_session(0), _learn_session(1)]
        store.save_learn(CHILD, learn)
        ov = client.get("/api/parent/overview", params={"token": tok}).json()
        card = next(c for c in ov["cards"] if c["child"] == CHILD)
        assert not any("还没" in p for p in card["pending"])
