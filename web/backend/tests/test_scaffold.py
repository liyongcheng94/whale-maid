"""R6/R7 脚手架分级与先修链归因测试(docs/11 轮次 6-7)。

口径:同一题答错梯度 = 第一次脚手架(概念级)→ 第二次中间步提示(step_hint/通用)
→ 第三次过题并返回先修点(hard 边优先,含诊断问题不给答案);
降档判定仍在连续错 2 次触发,与过题时机解耦。
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # noqa: E402
import learn_routes  # noqa: E402
import store  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)
CHILD = "scaffold-test"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA", tmp_path)
    monkeypatch.setattr(learn_routes.store, "DATA", tmp_path)
    learn_routes.LEARN_SESSIONS.clear()
    yield
    learn_routes.LEARN_SESSIONS.clear()


def _wrong(session):
    return client.post("/api/learn/answer", json={
        "child": CHILD, "session": session, "qid": cur_qid(session), "answer": "99999", "time_s": 1}).json()


def cur_qid(session):
    return learn_routes.LEARN_SESSIONS[(CHILD, session)]["seen"][-1]


class TestScaffoldGrading:
    def test_三级梯度(self):
        client.get("/api/learn/next", params={"child": CHILD, "level": "m1-1", "session": "g1"})
        r1 = _wrong("g1")
        assert r1["retry"] is True and r1["scaffold"] and not r1.get("step_hint")
        r2 = _wrong("g1")
        assert r2["retry"] is True and r2.get("step_hint")  # 中间步提示
        r3 = _wrong("g1")
        assert r3["retry"] is False and r3["count"] == 1    # 过题
        assert r3.get("next") or r3.get("done")

    def test_同题两次错降档仍触发(self):
        client.get("/api/learn/next", params={"child": CHILD, "level": "m1-1", "session": "g2"})
        _wrong("g2"); _wrong("g2")
        learn = store.load_learn(CHILD)
        assert learn["topic_state"]["m_addsub_rel"]["tier"] == "basic"

    def test_带step_hint的题第二次返回具体步骤(self):
        client.get("/api/learn/next", params={"child": CHILD, "level": "m1-1", "session": "g3"})
        r2 = None
        for _ in range(40):
            qid = cur_qid("g3")
            r1 = _wrong("g3")
            if qid == "a11":
                r2 = _wrong("g3")  # a11 的第二次错 → step_hint
                break
        if r2 is None:
            pytest.skip("a11 未在 40 次内出现")
        assert "460-120" in r2.get("step_hint", "")


class TestPrereqAttribution:
    def test_小数意义错题归因到三下先修点(self):
        client.get("/api/learn/next", params={"child": CHILD, "level": "m4-1", "session": "p1"})
        for _ in range(3):
            r = _wrong("p1")
            if r.get("prereq"):
                break
        assert r.get("prereq"), "小数题错三次应返回先修点"
        assert r["prereq"]["id"] == "m_dec_prelim"
        assert r["prereq"]["question"]  # 诊断问题存在但不给答案

    def test_归因写入家长可见日志(self):
        client.get("/api/learn/next", params={"child": CHILD, "level": "m4-1", "session": "p2"})
        for _ in range(3):
            r = _wrong("p2")
            if r.get("prereq"):
                break
        learn = store.load_learn(CHILD)
        assert any("先修点" in e["reason"] for e in learn.get("adjust_log", []))
