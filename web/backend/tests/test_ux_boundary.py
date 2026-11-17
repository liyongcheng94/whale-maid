"""R18/R19/R20 学园 UX 与边界测试(docs/11 轮次 18-20)。

口径:
- R18 地图:每关错题数 wrong 与单元完成度 done_n/total_n 下发
- R19 文案:孩子端(mode=child)离线兜底走学园语气包(eggs_xueyuan.json),
  禁低幼词;legacy 台词包与学园包互不污染
- R20 边界:判答对非数字输入优雅处理(不计对,返回脚手架)
"""
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import learn_routes  # noqa: E402
import store  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)
ROOT = Path(__file__).resolve().parents[3]
FRONTEND = ROOT / "web" / "frontend"
KID = (FRONTEND / "kid.html").read_text(encoding="utf-8")
CHILD = "tone-test"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA", tmp_path)
    monkeypatch.setattr(learn_routes.store, "DATA", tmp_path)
    learn_routes.LEARN_SESSIONS.clear()
    yield
    learn_routes.LEARN_SESSIONS.clear()


class TestR18Map:
    def test_地图下发错题数与完成度(self, isolated):
        client.get("/api/learn/next", params={"child": CHILD, "level": "m1-1", "session": "m"})
        for _ in range(3):
            qid = learn_routes.LEARN_SESSIONS[(CHILD, "m")]["seen"][-1]
            client.post("/api/learn/answer", json={
                "child": CHILD, "session": "m", "qid": qid, "answer": "99999", "time_s": 1})
        m = client.get("/api/learn/map", params={"child": CHILD}).json()
        u1 = next(u for u in m["units"] if u["id"] == "u1")
        assert u1["total_n"] == 3 and u1["done_n"] == 0
        lvl = next(l for l in u1["levels"] if l["id"] == "m1-1")
        assert lvl["wrong"] >= 3


class TestR19Tone:
    def test_学园兜底台词包存在且无低幼词(self):
        data = json.loads((ROOT / "config" / "eggs_xueyuan.json").read_text(encoding="utf-8"))
        assert "xfallback" in data["triggers"]
        banned = ["白饭", "晒屁股", "宝贝", "睡觉觉", "手手", "咕噜噜"]
        for pool, lines in data["triggers"].items():
            for line in lines:
                assert not any(b in line for b in banned), f"{pool} 台词含低幼词: {line}"

    def test_孩子端离线兜底走学园包(self, isolated):
        body = client.post("/api/chat", json={"text": "这是个没见过的句子", "session_id": "t", "mode": "child"}).json()
        assert body["pool"] == "xfallback"
        assert body["reply"] in json.loads((ROOT / "config" / "eggs_xueyuan.json").read_text(encoding="utf-8"))["triggers"]["xfallback"]

    def test_学园包与legacy包互不污染(self):
        xy = json.loads((ROOT / "config" / "eggs_xueyuan.json").read_text(encoding="utf-8"))
        lg = json.loads((ROOT / "config" / "eggs_birthday.json").read_text(encoding="utf-8"))
        assert set(xy["triggers"]).isdisjoint(set(lg["triggers"]))

    def test_kid页面无低幼词(self):
        banned = ["白饭", "晒屁股", "睡觉觉", "手手", "宝贝"]
        for b in banned:
            assert b not in KID, f"kid.html 含低幼词 {b}"


class TestR20Boundary:
    def test_非数字答案优雅处理(self, isolated):
        client.get("/api/learn/next", params={"child": CHILD, "level": "m1-1", "session": "b1"})
        qid = learn_routes.LEARN_SESSIONS[(CHILD, "b1")]["seen"][-1]
        r = client.post("/api/learn/answer", json={
            "child": CHILD, "session": "b1", "qid": qid, "answer": "我不知道", "time_s": 1})
        assert r.status_code == 200
        body = r.json()
        assert body["correct"] is False and body["scaffold"]  # 走脚手架,不崩

    def test_服务重启后会话失效也能优雅作答(self, isolated):
        """R20:重启清空内存会话后,ghost 会话隐式重建(学习不因重启中断)。"""
        r = client.post("/api/learn/answer", json={
            "child": CHILD, "session": "ghost", "qid": "a11", "answer": "1", "time_s": 1})
        assert r.status_code == 200 and "retry" in r.json()
