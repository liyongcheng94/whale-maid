"""R5 每日挑战错题优先测试(docs/11 轮次 5)。

口径:有近期错题时,每日挑战第 1 题来自错题;无错题时纯日期种子;
同日两次请求结果一致(可复现)。
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # noqa: E402
import store  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)
CHILD = "daily-test"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA", tmp_path)
    monkeypatch.setattr(__import__("learn_routes").store, "DATA", tmp_path)
    yield


class TestDailyReview:
    def test_昨日错题优先掺入(self):
        import learn_routes
        learn = store.load_learn(CHILD)
        learn["sessions"] = [{"ts": "2026-11-17 10:00:00", "qid": "a11", "topic": "m_addsub_rel",
                              "level": "m1-1", "correct": False, "time_s": 3}]
        store.save_learn(CHILD, learn)
        body = client.get("/api/learn/daily", params={"child": CHILD}).json()
        assert body["review"] is True
        assert body["questions"][0]["qid"] == "a11"
        assert len(body["questions"]) == 3

    def test_无错题纯种子(self):
        body = client.get("/api/learn/daily", params={"child": CHILD}).json()
        assert body["review"] is False
        assert len(body["questions"]) == 3

    def test_同日可复现(self):
        a = client.get("/api/learn/daily", params={"child": CHILD}).json()
        b = client.get("/api/learn/daily", params={"child": CHILD}).json()
        assert [q["qid"] for q in a["questions"]] == [q["qid"] for q in b["questions"]]
