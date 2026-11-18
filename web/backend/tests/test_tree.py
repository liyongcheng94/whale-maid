"""R46/R47 技能树测试:掌握判定(7天≥5题≥80%→mastered)、状态排序、只呈现≤4年级节点。"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import learn_routes  # noqa: E402
import store  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)
CHILD = "tree-test"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA", tmp_path)
    monkeypatch.setattr(learn_routes.store, "DATA", tmp_path)
    learn_routes.LEARN_SESSIONS.clear()
    yield
    learn_routes.LEARN_SESSIONS.clear()


def test_状态判定与排序():
    import time
    learn = store.load_learn(CHILD)
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    # m_addsub_rel:5 题全对(7 天内)→ mastered
    for i in range(5):
        learn["sessions"].append({"ts": now, "level": "m1-1", "qid": f"x{i}", "topic": "m_addsub_rel",
                                  "correct": True, "time_s": 2})
    # m_muldiv_rel:2 题半对半错 → learning
    for c in (True, False):
        learn["sessions"].append({"ts": now, "level": "m1-1", "qid": f"y{c}", "topic": "m_muldiv_rel",
                                  "correct": c, "time_s": 2})
    store.save_learn(CHILD, learn)
    body = client.get("/api/learn/tree", params={"child": CHILD}).json()
    st = {s["id"]: s["status"] for s in body["skills"]}
    assert st["m_addsub_rel"] == "mastered"
    assert st["m_muldiv_rel"] == "learning"
    assert st["m_dec_mean"] == "locked"
    assert body["mastered_count"] == 1
    # 排序:mastered 在 learning 前
    statuses = [s["status"] for s in body["skills"]]
    assert statuses.index("mastered") < statuses.index("learning")


def test_无超纲节点():
    body = client.get("/api/learn/tree", params={"child": CHILD}).json()
    assert all(s["grade"] <= 4 for s in body["skills"])
