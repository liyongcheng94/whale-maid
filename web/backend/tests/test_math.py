"""R4 数学小游戏测试(docs/10)。

口径:开局词(数学/算术/算算/加法)建局;进行中有数字/退出词优先判答;
10 以内加减;支持阿拉伯数字与中文数字作答;5 题终局清状态;泛聊不消耗局。
"""
import random
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # noqa: E402
from main import MATH_GAMES, MATH_ROUNDS, _extract_number, _math_q, app  # noqa: E402

client = TestClient(app)
SID = "math-test"


@pytest.fixture(autouse=True)
def clean_games():
    MATH_GAMES.clear()
    yield
    MATH_GAMES.clear()


class TestNumberExtraction:
    @pytest.mark.parametrize("text,expect", [
        ("是3!", 3), ("12个", 12), ("10", 10), ("答案:7", 7),
        ("三", 3), ("十", 10), ("十二", 12), ("二十三", 23),
        ("没有数字呀", None), ("嗯嗯", None),
    ])
    def test_阿拉伯与中文数字(self, text, expect):
        assert _extract_number(text) == expect


class TestQuestionGen:
    def test_四则混合口径(self):
        """R15:三种形态((a+b)×c / a×b-c / a÷c+b),eval 自洽,答案为正整数。"""
        forms = set()
        for _ in range(60):
            q, qtts, ans = _math_q()
            assert ans > 0 and ans == eval(q.replace("×", "*").replace("÷", "/"))
            assert ("(" in q) or ("×" in q) or ("÷" in q)
            forms.add(("(" if "(" in q else "×" if "×" in q else "÷"))
        assert len(forms) == 3  # 三种形态都被覆盖


class TestMathGame:
    def _start(self):
        return client.post("/api/chat", json={"text": "我们来玩数学吧", "session_id": SID}).json()

    def test_开局建局并出题(self):
        body = self._start()
        assert body["pool"] == "math_start" and body["math"]["q_tts"]
        assert SID in MATH_GAMES and 0 <= MATH_GAMES[SID]["answer"] <= 10

    def test_答对连题与终局(self):
        self._start()
        last = None
        for i in range(MATH_ROUNDS):
            ans = MATH_GAMES[SID]["answer"]
            body = client.post("/api/chat", json={"text": str(ans), "session_id": SID}).json()
            last = body
        assert last["pool"] is None and last["math"] is None  # 终局走动态合成
        assert SID not in MATH_GAMES

    def test_答错提示正确答案不冷场(self):
        self._start()
        wrong = client.post("/api/chat", json={"text": "0", "session_id": SID}).json()  # 答案恒≥3,0 必错
        assert wrong["pool"] is None  # 动态合成(含正确答案)走实时 TTS
        assert "正确答案" in wrong["reply"]
        assert SID in MATH_GAMES  # 局还活着

    def test_退出清局(self):
        self._start()
        body = client.post("/api/chat", json={"text": "不玩啦", "session_id": SID}).json()
        assert body["pool"] == "math_done" and SID not in MATH_GAMES

    def test_泛聊不消耗局(self):
        self._start()
        before = dict(MATH_GAMES[SID])
        body = client.post("/api/chat", json={"text": "你好呀", "session_id": SID}).json()
        assert body.get("math") is None
        assert MATH_GAMES[SID]["count"] == before["count"]

    def test_中文数字作答(self):
        self._start()
        ans = MATH_GAMES[SID]["answer"]
        if ans > 10:
            body = client.post("/api/chat", json={"text": str(ans), "session_id": SID}).json()
        else:
            zh = {0: "零", 1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "七", 8: "八", 9: "九", 10: "十"}
            body = client.post("/api/chat", json={"text": zh[ans], "session_id": SID}).json()
        assert body["pool"] == "math_right" or (body["pool"] is None and MATH_ROUNDS == 1)
