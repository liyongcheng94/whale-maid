"""R109 学情趋势测试:本周/上周按话题正确率对比(弧线而非单点)。"""
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
    return client.post("/api/parent/pin/setup", json={"pin": "1111"}).json()["token"]


def test_趋势按话题对比两周(tok, tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA", tmp_path)
    monkeypatch.setattr(learn_routes.store, "DATA", tmp_path)
    import time as t
    learn = store.load_learn(CHILD)
    def sess(days, correct):
        ts = t.strftime("%Y-%m-%d %H:%M:%S", t.localtime(t.time() - days * 86400))
        return {"ts": ts, "qid": f"q{days}{correct}", "topic": "m_addsub_rel",
                "level": "m1-1", "correct": correct, "time_s": 2}
    learn["sessions"] = [sess(2, True), sess(2, True), sess(2, False),  # 本周 2/3
                          sess(10, False), sess(10, False)]              # 上周 0/2
    store.save_learn(CHILD, learn)
    r = client.get("/api/parent/report", params={"child": CHILD, "days": 14, "token": tok})
    body = r.json()
    tr = body["trends"]["加减法的意义与关系"]
    assert tr["this_week"] == 0.67
    assert tr["last_week"] == 0.0
