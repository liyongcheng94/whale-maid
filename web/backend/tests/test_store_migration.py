"""R10 schema v2 迁移测试(结构性改动):v1 档案读入即迁移,字段无损,幂等。"""
import sys
from pathlib import Path

import store  # noqa: E402


def test_v1档案迁移到v2(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA", tmp_path)
    v1 = {"child": "ranran", "xp": 95, "levels": {"m1-1": {"done": True, "best": 5}}}
    store.save_json(store.learn_path("ranran"), v1)
    data = store.load_learn("ranran")
    assert data["v"] == 2 and data["xp"] == 95
    assert data["badges"] == [] and "adjust_log" in data and "daily_done" in data
    # 幂等:再读一次不变形
    again = store.load_learn("ranran")
    assert again == data
