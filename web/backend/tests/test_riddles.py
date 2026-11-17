"""R5 猜谜语测试(docs/10)。

口径:开局词建局(alias 判答);「不知道/答案」认输揭晓;3 次不中给提示,5 次揭晓;
「提示」要提示不计数;谜面预生成 riddle_{id}_q.mp3;非谜语聊天不受影响。
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # noqa: E402
from main import RIDDLES, RIDDLE_GAMES, app  # noqa: E402

client = TestClient(app)
SID = "riddle-test"


@pytest.fixture(autouse=True)
def clean():
    RIDDLE_GAMES.clear()
    yield
    RIDDLE_GAMES.clear()


class TestRiddleContract:
    def test_谜语数量与字段(self):
        assert len(RIDDLES) >= 10
        for r in RIDDLES:
            assert r["id"].isascii() and r["id"].islower()
            assert r["q"] and r["alias"] and r["answer"] and r["hint"]

    def test_谜面音频预生成(self):
        mp3 = Path(__file__).resolve().parents[3] / "assets_audio" / "mp3"
        if not mp3.exists():
            pytest.skip("音频未生成的环境")
        for r in RIDDLES:
            assert (mp3 / f"riddle_{r['id']}_q.mp3").exists()


class TestRiddleGame:
    def _start(self):
        return client.post("/api/chat", json={"text": "我们来猜谜语吧", "session_id": SID}).json()

    def test_开局(self):
        body = self._start()
        assert body["pool"] == "riddle_start"
        assert body["riddle"]["q"] and body["q_audio"].startswith("riddle_")
        assert SID in RIDDLE_GAMES

    def test_答对清局夸奖(self):
        self._start()
        rid = RIDDLE_GAMES[SID]["id"]
        r = next(x for x in RIDDLES if x["id"] == rid)
        body = client.post("/api/chat", json={"text": f"是{r['alias'][0]}!", "session_id": SID}).json()
        assert body["pool"] == "riddle_right" and SID not in RIDDLE_GAMES

    def test_不中计数到提示到揭晓(self):
        self._start()
        body = client.post("/api/chat", json={"text": "苹果", "session_id": SID}).json()
        assert body["pool"] == "riddle_miss" and body.get("hint_text") is None
        body = client.post("/api/chat", json={"text": "香蕉", "session_id": SID}).json()
        assert body["pool"] == "riddle_miss" and body.get("hint_text") is None
        body = client.post("/api/chat", json={"text": "西瓜", "session_id": SID}).json()
        assert body["pool"] == "riddle_miss" and "hint_text" in body  # 第 3 次给提示
        body = client.post("/api/chat", json={"text": "月亮", "session_id": SID}).json()
        body = client.post("/api/chat", json={"text": "白云", "session_id": SID}).json()
        assert body["pool"] == "riddle_reveal" and "谜底是" in body["reply"]
        assert SID not in RIDDLE_GAMES

    def test_认输直接揭晓(self):
        self._start()
        rid = RIDDLE_GAMES[SID]["id"]
        r = next(x for x in RIDDLES if x["id"] == rid)
        body = client.post("/api/chat", json={"text": "我不知道啦", "session_id": SID}).json()
        assert body["pool"] == "riddle_reveal" and r["answer"] in body["reply"]
        assert SID not in RIDDLE_GAMES

    def test_要提示不计数(self):
        self._start()
        body = client.post("/api/chat", json={"text": "给我提示", "session_id": SID}).json()
        assert body.get("hint_text") and RIDDLE_GAMES[SID]["miss"] == 0

    def test_退出(self):
        self._start()
        body = client.post("/api/chat", json={"text": "不猜了", "session_id": SID}).json()
        assert body["pool"] == "riddle_reveal" and SID not in RIDDLE_GAMES

    def test_开局词不在局内误判(self):
        self._start()
        rid = RIDDLE_GAMES[SID]["id"]
        r = next(x for x in RIDDLES if x["id"] == rid)
        # 重复说「猜谜语」:alias 命中谜底才算对;此谜底若含「谜语」字样的极端情况跳过
        body = client.post("/api/chat", json={"text": "猜谜语", "session_id": SID}).json()
        if not any(a in "猜谜语" for a in r["alias"]):
            assert body["pool"] in ("riddle_miss", "riddle_reveal")
