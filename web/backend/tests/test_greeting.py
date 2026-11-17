"""R2 时间感知问候测试(docs/10)。

口径:0-23 时 → 五段问候池;深夜池情绪必为 sleepy;/api/greeting 返回池内真实台词。
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # noqa: E402
from main import _greeting_pool, app  # noqa: E402

client = TestClient(app)


class TestGreetingPool:
    @pytest.mark.parametrize("hour,expect", [
        (23, "greeting_night"), (2, "greeting_night"), (4, "greeting_night"),
        (5, "greeting_morning"), (8, "greeting_morning"), (10, "greeting_morning"),
        (11, "greeting_noon"), (13, "greeting_noon"),
        (14, "greeting_afternoon"), (18, "greeting_afternoon"),
        (19, "greeting_evening"), (22, "greeting_evening"),
    ])
    def test_时段划分(self, hour, expect):
        pool, _ = _greeting_pool(hour)
        assert pool == expect

    def test_深夜是哄睡情绪(self):
        for h in (23, 0, 3):
            assert _greeting_pool(h)[1] == "sleepy"

    def test_其余时段默认开心(self):
        for h in (8, 12, 16, 20):
            assert _greeting_pool(h)[1] == "happy"


class TestGreetingApi:
    def test_问候端点返回池内真实台词(self):
        body = client.get("/api/greeting").json()
        import main
        from main import EGGS
        pool, _ = main._greeting_pool(__import__("time").localtime().tm_hour)
        assert body["pool"] == pool
        assert body["text"] in EGGS["triggers"][pool]
        assert 1 <= body["idx"] <= len(EGGS["triggers"][pool])
