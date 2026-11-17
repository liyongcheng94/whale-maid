"""对话路由与表情协议测试。

规格即测试(借鉴 quant-lab:docstring 预登记口径):
- 关键词路由按 config/eggs_birthday.json 的 keyword_map 书写顺序优先
- /api/chat 返回 {reply, emo(前端英文键), pool, idx, source}——pool+idx 对齐预生成音频 {pool}_{idx}.mp3
- 表情标记协议:回复开头 (中文词) 五选一,后端剥离并映射成前端英文键;全角/半角括号都收
- 多轮记忆:滑动窗口最近 SESSION_TURNS 轮往返;离线回复同样入记忆
- 离线兜底原则:任何输入都有回应(source=offline)
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/ 入 sys.path
from main import (EMO_PROSODY, EMO_RE, SESSIONS, SESSION_TURNS, _offline_reply,  # noqa: E402
                  _pick_idx, _split_emo, app)

client = TestClient(app)
VALID_EMO = {"normal", "happy", "shy", "pouty", "sad", "sleepy"}


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


class TestProsody:
    def test_韵律表覆盖六态(self):
        assert set(EMO_PROSODY) == VALID_EMO

    def test_韵律参数格式合法(self):
        for params in EMO_PROSODY.values():
            if "rate" in params:
                assert params["rate"].endswith("%") and params["rate"][0] in "+-"
            if "pitch" in params:
                assert params["pitch"].endswith("Hz") and params["pitch"][0] in "+-"


class TestOfflineRouting:
    """关键词路由(前置:conftest 已清 key,必为 offline)。"""

    def test_生日关键词进生日池(self):
        r = client.post("/api/chat", json={"text": "明天是我生日哦"})
        body = r.json()
        assert r.status_code == 200 and body["source"] == "offline"
        assert body["pool"] == "birthday" and "生日" in body["reply"]
        assert body["emo"] == "happy" and 1 <= body["idx"] <= 4

    def test_说胖触发体态梗(self):
        body = client.post("/api/chat", json={"text": "你是不是胖了呀"}).json()
        assert body["pool"] == "called_fat" and "滤食性动物" in body["reply"]
        assert body["emo"] == "pouty"

    def test_唱歌关键词进唱歌池(self):
        body = client.post("/api/chat", json={"text": "给我唱首歌吧"}).json()
        assert body["pool"] == "sing"
        assert ("唱" in body["reply"]) or ("歌" in body["reply"]) or ("♪" in body["reply"])

    def test_无命中回落兜底池(self):
        body = client.post("/api/chat", json={"text": "你好呀"}).json()
        assert body["source"] == "offline" and body["pool"] == "fallback"
        assert 1 <= body["idx"] <= 3

    def test_空白输入回落兜底(self):
        body = client.post("/api/chat", json={"text": "   "}).json()
        assert body["source"] == "offline" and body["pool"] == "fallback"

    def test_回复永不冷场(self):
        """任意输入都有非空回应(离线兜底原则)。"""
        for text in ["", "???", "讲个故事", "你好呀", "白饭白饭"]:
            body = client.post("/api/chat", json={"text": text}).json()
            assert body["reply"].strip()

    def test_池序号与预生成音频对齐(self):
        """pool+idx 必须落在真实台词数组范围内(前端零延迟音频的对齐契约)。"""
        import json
        eggs = json.loads((Path(__file__).resolve().parents[3] / "config" / "eggs_birthday.json")
                          .read_text(encoding="utf-8"))
        for _ in range(20):
            body = client.post("/api/chat", json={"text": "唱个歌"}).json()
            assert body["idx"] <= len(eggs["triggers"]["sing"])


class TestMusicRouting:
    """歌单路由契约(2026-11-17 唱歌升级为播真实音频;music_fetch.py 入库)。"""

    def test_点歌名跨组命中(self):
        body = client.post("/api/chat", json={"text": "来一首孤勇者"}).json()
        assert body["song"] == "song_01_guyongzhe.m4a" and body["song_title"] == "孤勇者"
        assert body["pool"] == "sing"  # 引子固定取 sing 池

    def test_生日歌分流到生日组(self):
        body = client.post("/api/chat", json={"text": "唱生日歌"}).json()
        assert body["song"] == "birthday_01_happy_birthday.m4a" and body["pool"] == "sing"

    def test_哈基米专属词进哈基米组(self):
        body = client.post("/api/chat", json={"text": "来点哈基米吧！"}).json()
        assert body["song"] == "hachimi_01_hamanbo.m4a" and body["pool"] == "sing"

    def test_通用音乐词短句进歌曲组随机(self):
        body = client.post("/api/chat", json={"text": "唱首歌吧"}).json()
        assert body["pool"] == "sing"
        assert body["song"] in {"song_01_guyongzhe.m4a", "song_02_wayawa.m4a"}

    def test_生日语境不误触歌单(self):
        body = client.post("/api/chat", json={"text": "明天是我生日哦"}).json()
        assert body["pool"] == "birthday" and body["song"] is None

    def test_长句不误触歌单(self):
        """泛化词只对 ≤15 字短句生效;长句不播真实音频(可落 sing 台词池口癖回应)。"""
        body = client.post("/api/chat", json={"text": "你说你会唱歌那你说说歌是什么呀我好想知道"}).json()
        assert body["song"] is None

    def test_音乐返回引子对齐sing池(self):
        import json
        eggs = json.loads((Path(__file__).resolve().parents[3] / "config" / "eggs_birthday.json").read_text(encoding="utf-8"))
        for _ in range(10):
            body = client.post("/api/chat", json={"text": "听歌"}).json()
            assert body["idx"] <= len(eggs["triggers"]["sing"]) and body["reply"].strip()


class TestSessionMemory:
    def test_多轮记忆累积(self):
        """同 session 连说两句,历史应有 2 轮往返(4 条)。"""
        SESSIONS.clear()
        sid = "test-mem"
        client.post("/api/chat", json={"text": "你好呀", "session_id": sid})
        client.post("/api/chat", json={"text": "讲个故事", "session_id": sid})
        assert len(SESSIONS[sid]) == 4
        assert SESSIONS[sid][0]["role"] == "user"
        assert SESSIONS[sid][-1]["role"] == "assistant"

    def test_滑动窗口上限(self):
        """超过 SESSION_TURNS 轮后,记忆长度封顶在 SESSION_TURNS*2。"""
        SESSIONS.clear()
        sid = "test-trim"
        for i in range(SESSION_TURNS + 3):
            client.post("/api/chat", json={"text": f"第{i}句话", "session_id": sid})
        assert len(SESSIONS[sid]) == SESSION_TURNS * 2

    def test_不同session互相隔离(self):
        SESSIONS.clear()
        client.post("/api/chat", json={"text": "你好呀", "session_id": "a"})
        client.post("/api/chat", json={"text": "你好呀", "session_id": "b"})
        assert len(SESSIONS["a"]) == 2 and len(SESSIONS["b"]) == 2


class TestModes:
    """标准(大肥鱼)/生日(冉冉姐姐生日版)双模式:同一台词池,称呼统一「冉冉姐姐」(2026-11-17 用户拍板)。
    真不变量(对池内所有随机台词都成立):任何模式回复绝不出现「鱼片」,生日语境出现「冉冉姐姐」。"""

    def test_标准模式称呼不串台(self):
        for _ in range(6):
            body = client.post("/api/chat", json={"text": "明天是我生日哦"}).json()
            assert "鱼片" not in body["reply"], body["reply"]

    def test_生日模式称呼不串台(self):
        for _ in range(6):
            body = client.post("/api/chat", json={"text": "明天是我生日哦", "mode": "child"}).json()
            assert "鱼片" not in body["reply"], body["reply"]

    def test_非法mode回落标准模式(self):
        for _ in range(3):
            body = client.post("/api/chat", json={"text": "明天是我生日哦", "mode": "hack"}).json()
            assert "鱼片" not in body["reply"], body["reply"]


class TestHistory:
    def test_历史接口只读且不抛错(self):
        r = client.get("/api/history?limit=10")
        assert r.status_code == 200
        assert isinstance(r.json()["items"], list)

    def test_对话后历史可查(self):
        client.post("/api/chat", json={"text": "你好呀", "session_id": "hist-test"})
        items = client.get("/api/history?limit=5").json()["items"]
        assert any(it.get("user") == "你好呀" for it in items)


class TestHealth:
    def test_健康检查(self):
        body = client.get("/api/health").json()
        assert body["deepseek"] is False  # conftest 清了 key
        assert body["model"] == "deepseek-v4-flash"  # 2026-11-17 升级,chat 名 2026-07 弃用


class TestEggsEndpoint:
    def test_eggs下发与本地一致(self):
        """前端零硬编码契约:/api/eggs 返回的池与 config 文件完全一致。"""
        from main import EGGS
        assert client.get("/api/eggs").json() == EGGS


class TestEggAudio:
    def test_预生成音频可下发(self):
        """assets_audio 存在时,/{pool}_{idx}.mp3 直接 200(零延迟契约)。"""
        mp3 = Path(__file__).resolve().parents[3] / "assets_audio" / "mp3" / "greeting_1.mp3"
        if not mp3.exists():
            pytest.skip("音频未生成的环境")
        r = client.get("/egg-audio/greeting_1.mp3")
        assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg"

    def test_不存在的音频404并触发前端回落(self):
        r = client.get("/egg-audio/greeting_99.mp3")
        assert r.status_code == 404


class TestMusicAudio:
    def test_歌单音频可下发(self):
        """assets_audio/music 存在时,/music-audio/ 直接 200(引子→歌曲接力契约)。"""
        music_dir = Path(__file__).resolve().parents[3] / "assets_audio" / "music"
        if not music_dir.exists() or not any(music_dir.glob("*.m4a")):
            pytest.skip("歌单音频未入库的环境")
        r = client.get("/music-audio/song_01_guyongzhe.m4a")
        assert r.status_code == 200 and "audio" in r.headers["content-type"]

    def test_不存在的歌404并触发前端回落(self):
        r = client.get("/music-audio/nope_99.m4a")
        assert r.status_code == 404


def test_离线回复直调口径():
    """_offline_reply 返回 (台词, 池, 序号, 表情) 四元组。"""
    reply, pool, idx, emo = _offline_reply("好胖")
    assert pool == "called_fat" and "滤食性动物" in reply
    assert idx == 1 and emo == "pouty"


def test_resolve_song点歌口径():
    """LLM play_music 参数解析:点歌名 > 组关键词 > 随机兜底。"""
    from main import _resolve_song
    g, s = _resolve_song("孤勇者")
    assert g == "songs" and s["file"] == "song_01_guyongzhe.m4a"
    g, s = _resolve_song("来一首生日快乐歌")
    assert g == "birthday" and s["title"] == "生日快乐歌"
    g, s = _resolve_song("随便来个哈基米")
    assert g == "hachimi"
    g, s = _resolve_song("随机")
    assert g in {"birthday", "hachimi", "songs"} and s["file"]


def test_pick_idx序号口径():
    """_pick_idx 返回 1-based 序号,对应 {pool}_{idx}.mp3 命名。"""
    idx, text = _pick_idx("greeting")
    assert 1 <= idx <= 2 and isinstance(text, str)
