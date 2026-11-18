"""R101/R102 星级评价测试(洪恩式):0 错=3星,少量错=2星,多错=1星;地图下发最佳星数。"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import learn_routes  # noqa: E402
import store  # noqa: E402
from learn_routes import _stars_for  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)
CHILD = "star-test"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA", tmp_path)
    monkeypatch.setattr(learn_routes.store, "DATA", tmp_path)
    learn_routes.LEARN_SESSIONS.clear()
    yield
    learn_routes.LEARN_SESSIONS.clear()


class TestStarsCalc:
    def test_零错三星(self):
        assert _stars_for(0, 5) == 3

    def test_少量错两星(self):
        """口径:limit=5 时错 1 题(≤limit//3=1)仍有 2 星;2 错及以上 1 星。"""
        assert _stars_for(1, 5) == 2
        assert _stars_for(2, 5) == 1

    def test_多错一星(self):
        assert _stars_for(3, 5) == 1


class TestStarsFlow:
    def _answer_all_correct(self, session, level="m1-1"):
        client.get("/api/learn/next", params={"child": CHILD, "level": level, "session": session})
        for _ in range(10):
            qid = learn_routes.LEARN_SESSIONS[(CHILD, session)]["seen"][-1]
            ans = learn_routes._ALL_Q[qid]["answer"]
            body = client.post("/api/learn/answer", json={
                "child": CHILD, "session": session, "qid": qid,
                "answer": str(ans), "time_s": 2}).json()
            if body.get("done"):
                return body
        raise AssertionError("未终局")

    def test_全对首过三星并写入档案(self):
        body = self._answer_all_correct("s3")
        assert body["stars"] == 3
        learn = store.load_learn(CHILD)
        assert learn["levels"]["m1-1"]["stars"] == 3

    def test_地图下发最佳星数(self):
        self._answer_all_correct("s4")  # 先通关,再验证地图下发最佳星数
        m = client.get("/api/learn/map", params={"child": CHILD}).json()
        lvl = next(l for u in m["units"] for l in u["levels"] if l["id"] == "m1-1")
        assert lvl["stars"] == 3
