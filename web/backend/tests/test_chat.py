"""对话路由与表情协议测试。

规格即测试(借鉴 quant-lab:docstring 预登记口径):
- 关键词路由按 config/eggs_birthday.json 的 keyword_map 书写顺序优先
- 表情标记协议:回复开头 (中文词) 五选一,后端剥离成结构化字段;全角/半角括号都收
- 离线兜底原则:任何输入都有回应(source=offline)
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/ 入 sys.path
from main import EMO_RE, _offline_reply, _pick, _split_emo, app  # noqa: E402

client = TestClient(app)


class TestSplitEmo:
    """表情标记剥离协议(后端解析层)。"""

    @pytest.mark.parametrize("tag", ["开心", "害羞", "傲娇", "难过", "困"])
    def test_五种半角标记(self, tag):
        """Given 合法标记+正文 When 解析 Then 标记剥离且正文干净。"""
        body, emo = _split_emo(f"({tag})冉冉姐姐你来啦!")
        assert emo == tag
        assert body == "冉冉姐姐你来啦!"

    @pytest.mark.parametrize("tag", ["开心", "困"])
    def test_全角括号也收(self, tag):
        """LLM 输出全角括号时同样剥离。"""
        body, emo = _split_emo(f"（{tag}）好呀")
        assert emo == tag and body == "好呀"

    def test_无标记返回None(self):
        body, emo = _split_emo("普通回复")
        assert emo is None and body == "普通回复"

    def test_非法标记不剥离(self):
        """白名单外的括号词是正文的一部分,不吞。"""
        body, emo = _split_emo("(挥手)再见")
        assert emo is None and body == "(挥手)再见"


class TestOfflineRouting:
    """关键词路由(前置:conftest 已清 key,必为 offline)。"""

    def test_生日关键词进生日池(self):
        r = client.post("/api/chat", json={"text": "明天是我生日哦"})
        body = r.json()
        assert r.status_code == 200
        assert body["source"] == "offline"
        assert "生日" in body["reply"]  # birthday 池四句全部含「生日」口径

    def test_说胖触发体态梗(self):
        r = client.post("/api/chat", json={"text": "你是不是胖了呀"})
        assert "滤食性动物" in r.json()["reply"]

    def test_唱歌关键词进唱歌池(self):
        r = client.post("/api/chat", json={"text": "给我唱首歌吧"})
        reply = r.json()["reply"]
        assert ("唱" in reply) or ("歌" in reply) or ("♪" in reply)

    def test_无命中回落兜底池(self):
        r = client.post("/api/chat", json={"text": "你好呀"})
        body = r.json()
        assert body["source"] == "offline"
        assert body["reply"] in {
            "唔……冉冉姐姐说的话好深奥,让我再想亿会儿。",
            "嘿嘿,冉冉姐姐继续说,小鲸灵听着呢!",
            "咕噜噜?我没太听懂,不过只要是冉冉姐姐说的,都是好的!",
        }

    def test_空白输入回落兜底(self):
        r = client.post("/api/chat", json={"text": "   "})
        assert r.json()["source"] == "offline"

    def test_回复永不冷场(self):
        """任意输入都有非空回应(离线兜底原则)。"""
        for text in ["", "???", "讲个故事", "你好呀", "白饭白饭"]:
            r = client.post("/api/chat", json={"text": text})
            assert r.json()["reply"].strip()


class TestHealth:
    def test_健康检查(self):
        r = client.get("/api/health")
        body = r.json()
        assert r.status_code == 200
        assert body["deepseek"] is False  # conftest 清了 key
        assert body["model"] == "deepseek-chat"


class TestEggsEndpoint:
    def test_eggs下发与本地一致(self):
        """前端零硬编码契约:/api/eggs 返回的池与 config 文件完全一致。"""
        import json
        from main import EGGS
        r = client.get("/api/eggs")
        assert r.json() == EGGS


def test_关键词池定向性():
    """_offline_reply 对每个 keyword_map 词都能路由到对应池(抽样口径)。"""
    assert "滤食性动物" in _offline_reply("好胖")
    assert "白饭" in _offline_reply("饿了")
