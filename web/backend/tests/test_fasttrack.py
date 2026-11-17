"""R26/R27 测试:快速学习者通道(连对3跳两档)+先修诊断闭环。"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import learn_routes  # noqa: E402
import store  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)
CHILD = "fast-test"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA", tmp_path)
    monkeypatch.setattr(learn_routes.store, "DATA", tmp_path)
    learn_routes.LEARN_SESSIONS.clear()
    yield
    learn_routes.LEARN_SESSIONS.clear()


def _answer(session):
    qid = learn_routes.LEARN_SESSIONS[(CHILD, session)]["seen"][-1]
    ans = learn_routes._ALL_Q[qid]["answer"]
    return client.post("/api/learn/answer", json={
        "child": CHILD, "session": session, "qid": qid,
        "answer": str(ans), "time_s": 2}).json()


class TestFastTrack:
    def test_连对3跳两档(self):
        # 从 basic 档出发:连对 2 升到 standard,连对 3 直接跳到 challenge(跳两档)
        learn = store.load_learn(CHILD)
        learn.setdefault("topic_state", {}).setdefault("m_addsub_rel", {"tier": "basic"})
        store.save_learn(CHILD, learn)
        client.get("/api/learn/next", params={"child": CHILD, "level": "m1-1", "session": "ft"})
        for _ in range(3):
            _answer("ft")
        st = store.load_learn(CHILD)["topic_state"]["m_addsub_rel"]
        assert st["tier"] == "challenge"
        assert any("跳级" in e["reason"] for e in store.load_learn(CHILD)["adjust_log"])

    def test_连对2只升一档(self):
        cid = CHILD + "b"
        client.get("/api/learn/next", params={"child": cid, "level": "m1-1", "session": "ftb"})
        for _ in range(2):
            qid = learn_routes.LEARN_SESSIONS[(cid, "ftb")]["seen"][-1]
            ans = learn_routes._ALL_Q[qid]["answer"]
            client.post("/api/learn/answer", json={
                "child": cid, "session": "ftb", "qid": qid, "answer": str(ans), "time_s": 2})
        st = store.load_learn(cid)["topic_state"]["m_addsub_rel"]
        assert st["tier"] == "challenge"
        assert not any("跳级" in e["reason"] for e in store.load_learn(cid)["adjust_log"])


class TestPrereqLoop:
    def test_先修诊断答对加5分(self):
        r = client.post("/api/learn/prereq-answer", json={
            "child": CHILD, "prereq_id": "m_dec_prelim", "answer": "1.2"})
        assert r.json()["correct"] is True
        assert store.load_learn(CHILD)["xp"] == 5

    def test_先修诊断答错引导(self):
        r = client.post("/api/learn/prereq-answer", json={
            "child": CHILD, "prereq_id": "m_dec_prelim", "answer": "不知道"})
        assert r.json()["correct"] is False and "课本" in r.json()["message"]
