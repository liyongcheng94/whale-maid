"""学园课程合同测试(docs/prd §1 课程锚点:四下 2026 春,无超纲/无低幼偏移)。"""
import json
import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import store  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)
ROOT = Path(__file__).resolve().parents[3]
CURR = json.loads((ROOT / "config" / "curriculum" / "g4s2_math.json").read_text(encoding="utf-8"))
KG = json.loads((ROOT / "config" / "curriculum" / "knowledge_graph.json").read_text(encoding="utf-8"))
ALL_Q = {q["id"]: q for u in CURR["units"] for l in u.get("levels", []) for q in l.get("questions", [])}


class TestCurriculumContract:
    def test_单元顺序与四下章节名(self):
        names = [u["name"] for u in CURR["units"]]
        assert names[:4] == ["四则运算", "观察物体(二)", "运算定律", "小数的意义和性质"]
        assert "小数的加法和减法" in names  # 2026 春四下含小数单元,不可沿用旧版目录

    def test_题库字段完备(self):
        for qid, q in ALL_Q.items():
            assert q["tier"] in ("basic", "standard", "challenge"), qid
            assert q["prompt"].strip() and q["scaffold"].strip(), qid
            assert isinstance(q["answer"], (int, float)), qid

    def test_答案与数值自洽(self):
        """直接求解型(结尾 =?)的算式 eval 后必须等于 answer;
        「已知…=Z」类逆运算题的给定算式必须为真命题(防内容手滑)。"""
        import re
        num = r"\d+(?:\.\d+)?"
        op = r"\s*[+×x*/÷\-]\s*"
        expr_re = re.compile(rf"({num}(?:{op}{num})+?)\s*=\s*(\??)({num})?")
        direct, given = 0, 0
        for qid, q in ALL_Q.items():
            m = expr_re.search(q["prompt"])
            if not m:
                continue
            expr = m.group(1).replace("×", "*").replace("x", "*").replace("÷", "/")
            val = eval(expr)
            inverse = "直接写出" in q["prompt"] or q["prompt"].startswith(("已知", "根据"))
            if inverse:
                given += 1
                assert abs(val - float(m.group(3))) < 1e-9, f"{qid}: 给定算式 {expr}={val} 与题面矛盾"
            elif m.group(2) == "?":
                direct += 1
                assert abs(val - q["answer"]) < 1e-9, f"{qid}: {expr}={val} 但 answer={q['answer']}"
        assert direct >= 5 and given >= 5  # 直接求解型与逆运算型都要有覆盖

    def test_脚手架不给答案(self):
        """PRD:失败给下一步动作,不直接展示正确答案(两位数答案用 token 级检查,一位数豁免)。"""
        for qid, q in ALL_Q.items():
            if len(str(q["answer"])) < 2:
                continue
            assert not re.search(rf"(?<!\d){re.escape(str(q['answer']))}(?!\d)", q["scaffold"]), \
                f"{qid} 的 scaffold 泄露答案 {q['answer']}"

    def test_知识图谱节点与题库话题对齐(self):
        kg_ids = {t["id"] for t in KG["topics"]}
        topic_of = {q["id"]: l["topic"] for u in CURR["units"] for l in u.get("levels", [])
                    for q in l.get("questions", [])}
        for qid, topic in topic_of.items():
            assert topic in kg_ids, f"{qid} 的 topic {topic} 不在图谱"

    def test_先修边字段与强度合法(self):
        ids = {t["id"] for t in KG["topics"]}
        for e in KG["edges"]:
            assert e["topicId"] in ids and e["prerequisiteId"] in ids
            assert e["strength"] in ("hard", "soft") and e["reason"].strip()

    def test_四下节点带课标映射或章节(self):
        for t in KG["topics"]:
            assert t["chapter"] and t["grade"] in (3, 4)
            assert t["grade"] <= 4  # 四下锚定:不出现五年级及以上节点


class TestKidEndpoints:
    def test_课程地图含锁定单元与首关解锁(self, tmp_path, monkeypatch):
        import learn_routes
        monkeypatch.setattr(store, "DATA", tmp_path)
        monkeypatch.setattr(learn_routes.store, "DATA", tmp_path)
        r = client.get("/api/learn/map", params={"child": "ranran"})
        assert r.status_code == 200
        body = r.json()
        units = {u["name"]: u for u in body["units"]}
        assert units["四则运算"]["levels"], "第一单元应有可玩关卡"
        assert units["运算定律"]["planned"] is True
        assert body["title"] == "新手航海员"
