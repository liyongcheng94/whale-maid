"""学园自适应引擎测试(docs/prd §1 难度自适应 + §2 借鉴机制)。

口径:70%~85% 心流区间;连对 2 升一档;连错 2 降一档并插脚手架(不给答案);
判答数值容差;XP 公式(基础 10+连对 5,每日×2);每日挑战按日期种子可复现。
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # noqa: E402
import learn_routes  # noqa: E402
import store  # noqa: E402
from learn_routes import (_pick_question, _tier_shift, _title_for, _verify_answer)  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)
CHILD = "adaptive-test"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA", tmp_path)
    monkeypatch.setattr(learn_routes.store, "DATA", tmp_path)
    learn_routes.LEARN_SESSIONS.clear()
    yield
    learn_routes.LEARN_SESSIONS.clear()


class TestTiers:
    def test_三档相邻移动(self):
        assert _tier_shift("standard", up=True) == "challenge"
        assert _tier_shift("standard", up=False) == "basic"
        assert _tier_shift("challenge", up=True) == "challenge"   # 到顶不再升
        assert _tier_shift("basic", up=False) == "basic"          # 到底不再降

    def test_判答数值容差(self, ):
        q = {"answer": 100}
        assert _verify_answer(q, "100") is True
        assert _verify_answer(q, "100.0") is True
        assert _verify_answer(q, "99") is False
        assert _verify_answer(q, "abc") is False


class TestQuestionPick:
    def test_按档位选题且避开已见(self):
        seen = set()
        q = _pick_question("standard", "m_addsub_rel", seen)
        assert q["tier"] == "standard" and q["topic"] == "m_addsub_rel"
        seen.add(q["id"])
        q2 = _pick_question("standard", "m_addsub_rel", seen)
        assert q2["id"] != q["id"]

    def test_档位耗尽回落相邻档(self):
        seen = {f"a{i}" for i in "123456"}  # a1x 全部 basic 已见(a11-a1f 共 15 个)
        q = _pick_question("basic", "m_addsub_rel", seen)
        assert q is not None and q["id"] not in seen

    def test_四下锚定_不超纲(self):
        for q in learn_routes._ALL_Q.values():
            assert q["tier"] in ("basic", "standard", "challenge")
            assert q["topic"].startswith("m_")
            assert isinstance(q["answer"], (int, float))


class TestXP:
    def test_称号阈值表(self):
        assert _title_for(0) == "新手航海员"
        assert _title_for(250) == "见习研究员"
        assert _title_for(3000) == "学园传说"


class TestAdaptiveFlow:
    def test_答对两次升一档并写理由(self, tmp_path):
        client.get("/api/learn/next", params={"child": CHILD, "level": "m1-1", "session": "s-up"})
        for i in range(2):
            qid = learn_routes.LEARN_SESSIONS[(CHILD, "s-up")]["seen"][-1]
            answer = learn_routes._ALL_Q[qid]["answer"]
            r = client.post("/api/learn/answer", json={
                "child": CHILD, "session": "s-up", "qid": qid,
                "answer": str(answer), "time_s": 3}).json()
            last = r
        assert last["tier_change"] and last["tier_change"]["to"] == "challenge"
        learn = store.load_learn(CHILD)
        assert learn["adjust_log"][-1]["reason"].startswith("连续答对")

    def test_答错两次降一档带脚手架(self):
        """R6 起梯度为三次错过题:第二次错触发降档+中间步提示,第三次错过题。"""
        learn = store.load_learn(CHILD + "x")
        learn.setdefault("topic_state", {}).setdefault("m_addsub_rel", {"tier": "standard"})
        store.save_learn(CHILD + "x", learn)
        sess = client.get("/api/learn/next",
                          params={"child": CHILD + "x", "level": "m1-1", "session": "sx"}).json()
        qid = sess["qid"]
        r1 = client.post("/api/learn/answer", json={
            "child": CHILD + "x", "session": "sx", "qid": qid, "answer": "99999", "time_s": 2}).json()
        assert r1["retry"] is True and r1["scaffold"]  # 第一次错:脚手架+同题重试
        r2 = client.post("/api/learn/answer", json={
            "child": CHILD + "x", "session": "sx", "qid": qid, "answer": "99999", "time_s": 2}).json()
        assert r2["retry"] is True and r2.get("step_hint")  # 第二次错:中间步提示
        assert r2["tier_change"] and r2["tier_change"]["to"] == "basic"  # 连错 2 次降档
        r3 = client.post("/api/learn/answer", json={
            "child": CHILD + "x", "session": "sx", "qid": qid, "answer": "99999", "time_s": 2}).json()
        assert r3["retry"] is False  # 第三次错:过题换新题
        assert r3.get("next") or r3.get("done")

    def test_答错不公布答案给下一步动作(self):
        learn = store.load_learn(CHILD + "y")
        learn.setdefault("topic_state", {}).setdefault("m_muldiv_rel", {"tier": "basic"})
        store.save_learn(CHILD + "y", learn)
        sess = client.get("/api/learn/next",
                          params={"child": CHILD + "y", "level": "m1-2", "session": "sy"}).json()
        r = client.post("/api/learn/answer", json={
            "child": CHILD + "y", "session": "sy", "qid": sess["qid"],
            "answer": "88888", "time_s": 2}).json()
        assert r["scaffold"] and "正确答案是" not in r["scaffold"]

    def test_五题终局与XP累计(self):
        sess = client.get("/api/learn/next",
                          params={"child": CHILD + "z", "level": "m1-1", "session": "sz"}).json()
        xp0 = store.load_learn(CHILD + "z")["xp"]
        for _ in range(5):
            cur = learn_routes.LEARN_SESSIONS[(CHILD + "z", "sz")]
            # 直接判对:从内存 seen 里取最新一题作答
            qid = cur["seen"][-1]
            answer = learn_routes._ALL_Q[qid]["answer"]
            body = client.post("/api/learn/answer", json={
                "child": CHILD + "z", "session": "sz", "qid": qid,
                "answer": str(answer), "time_s": 3}).json()
            if body.get("done"):
                break
        learn = store.load_learn(CHILD + "z")
        assert learn["xp"] > xp0
        assert body.get("done") is True and body["summary"]["title"]


class TestDaily:
    def test_按日期种子可复现(self):
        d1 = client.get("/api/learn/daily", params={"child": CHILD}).json()
        d2 = client.get("/api/learn/daily", params={"child": CHILD}).json()
        assert [q["qid"] for q in d1["questions"]] == [q["qid"] for q in d2["questions"]]
        assert len(d1["questions"]) == 4 and not d1["done"]
