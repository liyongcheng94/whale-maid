"""小鲸灵网页版 —— 生日保底 + 人设调试台。

端点:
  GET  /            前端单页(无构建步骤)
  GET  /api/health  状态:是否配置 DeepSeek key
  GET  /api/eggs    彩蛋台词包(config/eggs_birthday.json)
  POST /api/chat    文本对话:DeepSeek → 失败回落离线台词(任何情况不冷场)
  GET  /api/tts     edge-tts 合成 mp3(带缓存;失败由前端回落 speechSynthesis)

运行(web/backend 目录):
  pip install -r requirements.txt
  set DEEPSEEK_API_KEY=sk-xxx     # 可选;不设则纯离线台词模式
  uvicorn main:app --host 0.0.0.0 --port 8100
"""

import hashlib
import collections
import json
import os
import random
import re
import time
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BACKEND = Path(__file__).resolve().parent
PROJECT = BACKEND.parent.parent  # 仓库根
CONFIG = PROJECT / "config"
FRONTEND = BACKEND.parent / "frontend"
TTS_CACHE = BACKEND / "tts_cache"
TTS_CACHE.mkdir(exist_ok=True)

EGGS = json.loads((CONFIG / "eggs_birthday.json").read_text(encoding="utf-8"))
# 歌单(config/playlist.json):唱歌升级为播真实音频(2026-11-17);组顺序即路由优先级 birthday > hachimi > songs
PLAYLIST = json.loads((CONFIG / "playlist.json").read_text(encoding="utf-8"))
MUSIC_DIR = PROJECT / "assets_audio" / "music"
# 泛化音乐词:仅对短句(≤15字)生效,长句如「你会唱歌吗」交 LLM 正常聊天
_MUSIC_GENERIC_WORDS = {"唱", "歌", "音乐", "听歌", "唱歌", "来首歌", "唱首歌"}
# 双模式人设:adult=大肥鱼标准版(docs/09 正典,默认),child=冉冉姐姐生日模式(11-27/手动切换);儿童化调整只影响 child
SYSTEM_PROMPTS = {
    "child": (CONFIG / "server_prompt.txt").read_text(encoding="utf-8").strip(),
    "adult": (CONFIG / "server_prompt_adult.txt").read_text(encoding="utf-8").strip(),
}

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
TTS_VOICE = os.environ.get("WHALE_TTS_VOICE", "zh-CN-XiaoyiNeural")

# 表情标记协议(借鉴 Open-LLM-VTuber 的 expression mapping,SVG 轻量版):
# LLM 按 config/server_prompt.txt 在回复开头输出 (开心)(害羞)(傲娇)(难过)(困),由后端剥离成结构化字段
EMO_RE = re.compile(r"^\s*[（(]\s*(开心|害羞|傲娇|难过|困)\s*[)）]\s*")
EMO_ZH2EN = {"开心": "happy", "害羞": "shy", "傲娇": "pouty", "难过": "sad", "困": "sleepy"}
# 情绪韵律:edge-tts 的语速/音调随表情起伏(声音与画面情绪一致)
EMO_PROSODY = {
    "normal": {},
    "happy": {"rate": "+8%", "pitch": "+25Hz"},
    "shy": {"rate": "-5%", "pitch": "+35Hz"},
    "pouty": {"rate": "-8%", "pitch": "+10Hz"},
    "sad": {"rate": "-12%", "pitch": "-15Hz"},
    "sleepy": {"rate": "-18%", "pitch": "-25Hz"},
}
# 多轮会话记忆(滑动窗口,最近 8 轮往返;会话按天分段,每天自然"重新认识")
SESSIONS = {}
SESSION_TURNS = 8
CHAT_LOG = PROJECT / "data" / "chat_log.jsonl"


def _load_dotenv() -> None:
    """极简 .env 支持(KEY=VALUE 每行),避免引入 python-dotenv 依赖。"""
    env = BACKEND / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()
DEEPSEEK_KEY = os.environ.get("DEEPSEEK_API_KEY", "")

app = FastAPI(title="whale-maid web", version="2.0-birthday")


class ChatIn(BaseModel):
    text: str
    session_id: str = "toy"
    mode: str = "adult"  # adult(默认 · 大肥鱼) | child(生日模式)


def _split_emo(reply: str):
    """剥离回复开头的表情标记,返回 (正文, 表情或 None)。兼容 Python 3.9。"""
    m = EMO_RE.match(reply)
    if not m:
        return reply, None
    return reply[m.end():], m.group(1)


def _pick_idx(trigger: str):
    """从池中随机取一句,返回 (1-based 序号, 台词)——序号对齐预生成音频命名 {pool}_{idx}.mp3。"""
    pool = EGGS["triggers"].get(trigger) or EGGS["triggers"]["fallback"]
    i = random.randrange(len(pool))
    return i + 1, pool[i]


def _pick(trigger: str) -> str:
    return _pick_idx(trigger)[1]


def _adultize(reply: str, mode: str) -> str:
    """称呼统一为「冉冉姐姐」(2026-11-17 用户拍板):台词池基准称呼即最终称呼,
    不再做大人模式替换,保留函数签名以稳调用点与测试。"""
    return reply.replace("鱼片", "冉冉姐姐")  # 兜底:池外来源若含旧称呼也归一


def _music_result(song):
    """命中歌单:引子固定取 sing 池(台词语义已预告「唱整首」),歌文件由前端接力播放。"""
    idx, reply = _pick_idx("sing")
    return reply, "sing", idx, EGGS["emo"].get("sing"), song["file"], song["title"]


def _music_route(text: str):
    """三段式路由:①点歌名(alias 子串,跨全组) > ②③组关键词随机(组顺序即优先级)。
    命中返回 (引子台词, "sing", idx, emo, 歌文件, 歌名);未命中返回 None。
    在 DeepSeek 之前拦截——音乐请求不进 LLM,有 key 时点歌也生效。"""
    t = text.lower()
    for g in PLAYLIST["groups"].values():
        for s in g["songs"]:
            if any(a.lower() in t for a in s.get("alias", [])):
                return _music_result(s)
        for k in g.get("keywords", []):
            if k in t and (k not in _MUSIC_GENERIC_WORDS or len(t) <= 15):
                return _music_result(random.choice(g["songs"]))
    return None


def _offline_reply(text: str):
    """关键词 → 彩蛋池;无命中随机兜底。keyword_map 的书写顺序即优先级。
    返回 (台词, 池名, 序号, 前端表情键)——池+序号让前端能命中零延迟的预生成音频。"""
    for trigger, words in EGGS.get("keyword_map", {}).items():
        if any(w in text for w in words):
            idx, reply = _pick_idx(trigger)
            return reply, trigger, idx, EGGS["emo"].get(trigger)
    idx, reply = _pick_idx("fallback")
    return reply, "fallback", idx, EGGS["emo"].get("fallback")


@app.get("/api/health")
async def health():
    return {"deepseek": bool(DEEPSEEK_KEY), "model": DEEPSEEK_MODEL, "voice": TTS_VOICE,
            "music_tools": bool(DEEPSEEK_KEY),  # DeepSeek 接入即支持 LLM 调歌(function calling)
            "songs": _song_catalog()}


def _song_catalog():
    """歌单目录(health 下发 + LLM system prompt 注入,让模型知道能点什么)。"""
    catalog = {}
    for gname, g in PLAYLIST["groups"].items():
        catalog[gname] = [s["title"] for s in g["songs"]]
    return catalog


def _all_songs():
    return [(gname, s) for gname, g in PLAYLIST["groups"].items() for s in g["songs"]]


# DeepSeek function calling:LLM 可主动调 play_music(2026-11-17 对话升级)
PLAY_MUSIC_TOOL = {
    "type": "function",
    "function": {
        "name": "play_music",
        "description": "为用户播放歌曲。用户想听歌/想让你唱歌/点具体歌名/要听哈基米或生日歌时调用。曲库:生日快乐歌(birthday);哈基米曼波(hachimi);孤勇者、挖呀挖(songs)。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "歌名或描述,如「孤勇者」「哈基米」「生日歌」;用户没指定就传「随机」",
                },
            },
            "required": [],
        },
    },
}


def _resolve_song(query: str):
    """LLM 的 play_music 参数 → (组名, 歌)。点歌名/别名子串 > 组关键词 > 全曲库随机。"""
    q = (query or "随机").lower().strip()
    if q not in ("随机", "random", ""):
        for gname, s in _all_songs():
            hay = " ".join([s["title"]] + s.get("alias", []) + [s["file"]]).lower()
            if q in hay or any(w in q for w in hay.split()):
                return gname, s
        for gname, g in PLAYLIST["groups"].items():
            if any(k.lower() in q for k in g.get("keywords", [])):
                return gname, random.choice(g["songs"])
    return random.choice(_all_songs())


@app.get("/api/eggs")
async def eggs():
    return EGGS


@app.post("/api/chat")
async def chat(inp: ChatIn):
    text = inp.text.strip()[:500]
    mode = inp.mode if inp.mode in SYSTEM_PROMPTS else "adult"
    if not text:
        idx, reply = _pick_idx("fallback")
        return {"reply": _adultize(reply, mode), "emo": EGGS["emo"].get("fallback"), "pool": "fallback",
                "idx": idx, "source": "offline", "song": None, "song_title": None}
    # 音乐路由前置拦截(在 DeepSeek 之前):命中即播歌,不进 LLM 也不入会话记忆
    music = _music_route(text)
    if music:
        reply, pool, idx, emo, song_file, song_title = music
        return {"reply": _adultize(reply, mode), "emo": emo, "pool": pool, "idx": idx,
                "source": "offline", "song": song_file, "song_title": song_title}
    # 多轮记忆:系统提示 + 最近 N 轮 + 本句
    history = SESSIONS.setdefault(inp.session_id[:64], collections.deque(maxlen=SESSION_TURNS * 2))
    messages = [{"role": "system", "content": SYSTEM_PROMPTS[mode]}] + list(history) + [{"role": "user", "content": text}]

    reply, emo, pool, idx, source = None, None, None, None, "offline"
    song_file = song_title = None
    if DEEPSEEK_KEY:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                # 曲库注入 system 尾部:模型知道能点什么歌
                messages = [dict(messages[0], content=messages[0]["content"] +
                            "\n曲库(可用 play_music 播放):" +
                            ";".join(f"{g}:{'/'.join(t)}" for g, t in _song_catalog().items()))] + messages[1:]
                r = await client.post(
                    DEEPSEEK_URL,
                    headers={"Authorization": f"Bearer {DEEPSEEK_KEY}"},
                    json={
                        "model": DEEPSEEK_MODEL,
                        "messages": messages,
                        "tools": [PLAY_MUSIC_TOOL],
                        "max_tokens": 100,
                        "temperature": 0.8,
                    },
                )
                r.raise_for_status()
                msg = r.json()["choices"][0]["message"]
                # LLM 主动调歌:function calling → 解析歌 → 二次回合让模型说一句引子
                if msg.get("tool_calls"):
                    call = msg["tool_calls"][0]
                    if call["function"]["name"] == "play_music":
                        try:
                            args = json.loads(call["function"].get("arguments") or "{}")
                        except Exception:
                            args = {}
                        gname, song = _resolve_song(args.get("query", "随机"))
                        song_file, song_title = song["file"], song["title"]
                        follow = messages + [
                            {"role": "assistant", "content": msg.get("content"), "tool_calls": msg["tool_calls"]},
                            {"role": "tool", "tool_call_id": call["id"],
                             "content": f"已找到歌曲《{song_title}》,即将开始播放。请用 1 句话(开头加表情标记)邀请用户欣赏,不要复述歌词。"},
                        ]
                        r2 = await client.post(
                            DEEPSEEK_URL,
                            headers={"Authorization": f"Bearer {DEEPSEEK_KEY}"},
                            json={"model": DEEPSEEK_MODEL, "messages": follow,
                                  "tool_choice": "none", "max_tokens": 60, "temperature": 0.8},
                        )
                        r2.raise_for_status()
                        raw2 = (r2.json()["choices"][0]["message"]["content"] or "").strip()
                        if raw2:
                            body, zh = _split_emo(raw2)
                            reply = body or f"(开心)♪ 马上为你唱《{song_title}》哦!"
                            emo = EMO_ZH2EN.get(zh, "happy")
                            source = "deepseek"
                elif (msg.get("content") or "").strip():
                    raw = msg["content"].strip()
                    body, zh = _split_emo(raw)
                    if body:
                        reply, emo, source = body, EMO_ZH2EN.get(zh), "deepseek"
        except Exception as e:  # 网络/配额/超时——兜底,不冷场
            print(f"[chat] deepseek 失败,回落离线台词: {e!r}")
    if reply is None:
        reply, pool, idx, emo = _offline_reply(text)
        reply = _adultize(reply, mode)

    # 会话记忆(离线回复也入记忆,LLM 恢复后能接上刚才的话题)
    history.append({"role": "user", "content": text})
    history.append({"role": "assistant", "content": reply})
    # 本地对话日志:家长可查 + 排障;只落本地文件,不上传
    try:
        CHAT_LOG.parent.mkdir(exist_ok=True)
        with CHAT_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                                "session": inp.session_id[:64], "user": text,
                                "whale": reply, "source": source,
                                "song": song_title or ""}, ensure_ascii=False) + "\n")
    except Exception:
        pass
    return {"reply": reply, "emo": emo, "pool": pool, "idx": idx, "source": source,
            "song": song_file, "song_title": song_title}


@app.get("/api/tts")
async def tts(text: str = Query(..., max_length=150), emo: str = Query("normal")):
    try:
        import edge_tts

        text = text.strip()
        if not text:
            raise HTTPException(400, "empty text")
        pros = EMO_PROSODY.get(emo, {})
        cache = TTS_CACHE / f"{hashlib.md5((emo + '|' + text).encode()).hexdigest()}.mp3"
        if not cache.exists():
            await edge_tts.Communicate(text, TTS_VOICE, **pros).save(str(cache))
        return FileResponse(cache, media_type="audio/mpeg", filename="whale.mp3")
    except HTTPException:
        raise
    except Exception as e:  # edge-tts/网络不可用 → 前端回落 speechSynthesis
        raise HTTPException(503, f"tts unavailable: {e!r}")


# 预生成彩蛋音频:零延迟下发(assets_audio 由 make_egg_audio.py 产出,CI 环境缺失时跳过挂载,前端自动回落)
if (PROJECT / "assets_audio" / "mp3").exists():
    app.mount("/egg-audio", StaticFiles(directory=str(PROJECT / "assets_audio" / "mp3")), name="egg-audio")

# 歌单音频(assets_audio/music,go-music-dl 下载入库;缺失时跳过挂载,前端回落 TTS)
if MUSIC_DIR.exists():
    app.mount("/music-audio", StaticFiles(directory=str(MUSIC_DIR)), name="music-audio")


@app.get("/api/history")
async def history(limit: int = 100):
    """本地对话日志只读接口(家长查看;文件缺省/损坏时返回空,不抛错)。"""
    if not CHAT_LOG.exists():
        return {"items": []}
    items = []
    try:
        lines = CHAT_LOG.read_text(encoding="utf-8").strip().splitlines()
        for ln in lines[-max(1, min(limit, 500)):]:
            try:
                items.append(json.loads(ln))
            except Exception:
                pass
    except Exception:
        pass
    return {"items": items}


app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
