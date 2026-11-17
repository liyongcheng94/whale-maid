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

import asyncio
import hashlib
import collections
import json
import os
import random
import re
import shutil
import time
import urllib.parse
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
# v4 系列默认开思考模式:语音摆件要低延迟短句,显式关闭(deepseek-chat 将于 2026-07-24 弃用,默认升级 v4-flash)
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
DEEPSEEK_THINKING = {"type": "disabled"}
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


def _cover_for(fname):
    """本地曲库歌曲的封面(点播时已存 covers/{basename}.jpg;无则 None)。"""
    if fname:
        c = COVERS_DIR / (os.path.splitext(fname)[0] + ".jpg")
        if c.exists():
            return c.name
    return None


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
    """LLM 的 play_music 参数 → (组名, 歌|None)。
    「随机」→ 全曲库随机;点歌名/别名命中本地曲库 → 返回;否则 None(前端异步找歌下载)。"""
    q = (query or "随机").lower().strip()
    if q in ("随机", "random", ""):
        return random.choice(_all_songs())
    for gname, s in _all_songs():
        hay = " ".join([s["title"]] + s.get("alias", []) + [s["file"]]).lower()
        if q in hay or any(w and w in q for w in hay.split()):
            return gname, s
    return None, None


# ---- 天气工具(Open-Meteo 免费无 key;2026-11-17 用户实测发现小鲸灵答不了天气) ----
# 用户城市默认值可在 web/backend/.env 配 WHALE_CITY=城市名
DEFAULT_CITY = os.environ.get("WHALE_CITY", "上海")

GET_WEATHER_TOOL = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "查询指定城市当前天气(温度/天气现象/湿度/风速+今日温度范围)。用户问天气、冷不冷、要不要带伞等时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "城市名(中文或拼音),如「上海」「深圳」;用户没说城市时传默认城市即可",
                },
            },
            "required": ["city"],
        },
    },
}

WEATHER_CODES = {  # WMO weather code → 中文
    0: "晴", 1: "大致晴朗", 2: "局部多云", 3: "阴",
    45: "有雾", 48: "雾凇",
    51: "毛毛雨", 53: "毛毛雨", 55: "浓毛毛雨",
    56: "冻毛毛雨", 57: "浓冻毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨",
    66: "冻雨", 67: "大冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "雪粒",
    80: "阵雨", 81: "中阵雨", 82: "强阵雨",
    85: "小阵雪", 86: "大阵雪",
    95: "雷阵雨", 96: "雷阵雨伴冰雹", 99: "强雷阵雨伴冰雹",
}


def _weather_code_text(code) -> str:
    return WEATHER_CODES.get(int(code or 0), "未知天象")


async def _fetch_weather(city: str) -> str:
    """Open-Meteo 地理编码+当前天气,返回给 LLM 的工具结果文本(失败抛异常由调用方兜底)。"""
    import json as _json
    async with httpx.AsyncClient(timeout=10) as client:
        g = await client.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city, "count": 1, "language": "zh", "format": "json"})
        g.raise_for_status()
        hits = (g.json().get("results") or [])
        if not hits:
            return f"ERROR: 找不到城市「{city}」,请请用户确认城市名。"
        loc = hits[0]
        r = await client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={"latitude": loc["latitude"], "longitude": loc["longitude"],
                    "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
                    "daily": "temperature_2m_max,temperature_2m_min", "forecast_days": 1,
                    "timezone": "auto"})
        r.raise_for_status()
        d = _json.loads(r.text)
        cur, daily = d.get("current", {}), d.get("daily", {})
        return (f"{loc.get('name', city)}当前天气: {cur.get('temperature_2m')}°C "
                f"{_weather_code_text(cur.get('weather_code'))}, "
                f"湿度 {cur.get('relative_humidity_2m')}%, "
                f"风速 {cur.get('wind_speed_10m')}km/h, "
                f"今日 {daily.get('temperature_2m_min', [''])[0]}~{daily.get('temperature_2m_max', [''])[0]}°C")


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
                "idx": idx, "source": "offline", "song": None, "song_title": None, "song_pending": None}
    # 音乐路由前置拦截(在 DeepSeek 之前):命中即播歌,不进 LLM 也不入会话记忆
    music = _music_route(text)
    if music:
        reply, pool, idx, emo, song_file, song_title = music
        return {"reply": _adultize(reply, mode), "emo": emo, "pool": pool, "idx": idx,
                "source": "offline", "song": song_file, "song_title": song_title, "song_pending": None,
                "cover": _cover_for(song_file)}
    # R3 古诗路由前置:背古诗 → 随机一首,前端逐句领读
    if any(k in text for k in _POEM_KEYWORDS):
        idx, intro = _pick_idx("poem_start")
        poem = random.choice(POEMS)
        return {"reply": intro, "emo": EGGS["emo"].get("poem_start"), "pool": "poem_start",
                "idx": idx, "source": "offline", "poem": poem, "song": None, "song_title": None,
                "song_pending": None}
    # R4 数学游戏:进行中优先判答(有数字或想退出);否则命中开局词才开新局
    sid = inp.session_id[:64]
    game = MATH_GAMES.get(sid)
    if game and (any(k in text for k in _MATH_EXIT_KW) or _extract_number(text) is not None):
        if any(k in text for k in _MATH_EXIT_KW):
            MATH_GAMES.pop(sid, None)
            return _math_reply("math_done")
        ans = _extract_number(text)
        game["count"] += 1
        correct = ans == game["answer"]
        final = game["count"] >= MATH_ROUNDS
        idx, praise = _pick_idx("math_right" if correct else "math_wrong")
        if not correct:
            praise += f"(悄悄说:正确答案是 {game['answer']} 呀~)"
        if final:
            _, done_line = _pick_idx("math_done")
            MATH_GAMES.pop(sid, None)
            out = _math_reply("math_done")
            out.update({"reply": praise + done_line, "pool": None, "idx": None,
                        "streak": game["streak"] + (1 if correct else 0), "math": None})
            return out
        out = _math_reply("math_right" if correct else "math_done")  # 占位,下面覆写
        q, qtts, ans2 = _math_q()
        game["answer"] = ans2
        out.update({"reply": praise, "pool": "math_right" if correct else None,
                    "idx": idx if correct else None,
                    "streak": game["streak"], "math": {"q": q, "q_tts": qtts}})
        if correct:
            game["streak"] += 1
            out["streak"] = game["streak"]
        return out
    if any(k in text for k in _MATH_START_KW):
        q, qtts, ans2 = _math_q()
        MATH_GAMES[sid] = {"count": 0, "streak": 0, "answer": ans2}
        out = _math_reply("math_start")
        out["math"] = {"q": q, "q_tts": qtts}
        return out
    # R5 猜谜语:进行中所有消息都视为猜答;认输/揭晓/5 次不中给谜底;3 次不中自动提示
    rgame = RIDDLE_GAMES.get(sid)
    if rgame:
        r = _riddle_by_id(rgame["id"])
        if any(k in text for k in _RIDDLE_EXIT_KW):
            RIDDLE_GAMES.pop(sid, None)
            idx, reveal = _pick_idx("riddle_reveal")
            return _chat_resp("riddle_reveal", idx, reveal + f"谜底是「{r['answer']}」哦~")
        if any(k in text for k in _RIDDLE_GIVEUP_KW):
            RIDDLE_GAMES.pop(sid, None)
            idx, reveal = _pick_idx("riddle_reveal")
            return _chat_resp("riddle_reveal", idx, reveal + f"谜底是「{r['answer']}」哦~")
        if any(a in text for a in r["alias"]):
            RIDDLE_GAMES.pop(sid, None)
            idx, reply = _pick_idx("riddle_right")
            return _chat_resp("riddle_right", idx, reply)
        if "提示" in text:
            return _chat_resp(None, None, "小鲸灵偷偷告诉你哦~", {"hint_text": r["hint"]})
        rgame["miss"] += 1
        if rgame["miss"] >= 5:
            RIDDLE_GAMES.pop(sid, None)
            idx, reveal = _pick_idx("riddle_reveal")
            return _chat_resp("riddle_reveal", idx, reveal + f"谜底是「{r['answer']}」哦~")
        idx, miss = _pick_idx("riddle_miss")
        extra = {"hint_text": r["hint"]} if rgame["miss"] >= 3 else None
        return _chat_resp("riddle_miss", idx, miss, extra)
    if any(k in text for k in _RIDDLE_START_KW):
        r = random.choice(RIDDLES)
        RIDDLE_GAMES[sid] = {"id": r["id"], "miss": 0}
        idx, intro = _pick_idx("riddle_start")
        return _chat_resp("riddle_start", idx, intro,
                          {"riddle": {"id": r["id"], "q": r["q"]}, "q_audio": f"riddle_{r['id']}_q"})
    # 多轮记忆:系统提示 + 最近 N 轮 + 本句
    history = SESSIONS.setdefault(inp.session_id[:64], collections.deque(maxlen=SESSION_TURNS * 2))
    messages = [{"role": "system", "content": SYSTEM_PROMPTS[mode]}] + list(history) + [{"role": "user", "content": text}]

    reply, emo, pool, idx, source = None, None, None, None, "offline"
    song_file = song_title = song_pending = None
    if DEEPSEEK_KEY:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                # 曲库+城市注入 system 尾部:模型知道能点什么歌、用户在哪;唱歌必须走工具,不许口头假装唱
                messages = [dict(messages[0], content=messages[0]["content"] +
                            "\n曲库(可用 play_music 播放):" +
                            ";".join(f"{g}:{'/'.join(t)}" for g, t in _song_catalog().items()) +
                            "\n重要:用户点播/想听/提到任何歌曲(包括曲库里没有的歌)都必须调用 play_music,"
                            "把歌名作为 query 传入——曲库没有时系统会自动去搜,绝不要口头拒绝或假装唱完。用户没指定歌名就传「随机」。"
                            + f"\n用户所在城市:{DEFAULT_CITY}(用户问天气且没说城市时,直接用它)。"
                            + "\n天气信息只能来自 get_weather 工具,绝不要凭空编造天气。")] + messages[1:]
                r = await client.post(
                    DEEPSEEK_URL,
                    headers={"Authorization": f"Bearer {DEEPSEEK_KEY}"},
                    json={
                        "model": DEEPSEEK_MODEL,
                        "messages": messages,
                        "tools": [PLAY_MUSIC_TOOL, GET_WEATHER_TOOL],
                        "thinking": DEEPSEEK_THINKING,
                        "max_tokens": 100,
                        "temperature": 0.8,
                    },
                )
                r.raise_for_status()
                msg = r.json()["choices"][0]["message"]
                # LLM 主动调歌:function calling → 解析歌 → 二次回合让模型说一句引子
                if msg.get("tool_calls"):
                    call = msg["tool_calls"][0]
                    fname = call["function"]["name"]
                    try:
                        args = json.loads(call["function"].get("arguments") or "{}")
                    except Exception:
                        args = {}
                    if fname == "play_music":
                        gname, song = _resolve_song(args.get("query", "随机"))
                        if song is not None:
                            song_file, song_title = song["file"], song["title"]
                            result_text = f"已找到歌曲《{song_title}》,即将开始播放。请用 1 句话(开头加表情标记)邀请用户欣赏,不要复述歌词。"
                        else:
                            # 曲库没有:前端会异步找歌下载,先让模型应一句
                            song_title = args.get("query") or "那首歌"
                            song_pending = song_title
                            result_text = (f"曲库里没有《{song_title}》。请用 1 句话(开头加表情标记)告诉用户你正游去深海"
                                           f"把《{song_title}》捞上来,马上回来,不要复述歌词。")
                    elif fname == "get_weather":
                        try:
                            result_text = await _fetch_weather(args.get("city") or DEFAULT_CITY)
                        except Exception as e:
                            print(f"[chat] 天气工具失败: {e!r}")
                            result_text = "ERROR: 天气服务暂时不可用。请按人设撒娇耍赖,1 句话(开头加表情标记)。"
                    else:
                        result_text = f"ERROR: 未知工具 {fname}。"
                    follow = messages + [
                        {"role": "assistant", "content": msg.get("content"), "tool_calls": msg["tool_calls"]},
                        {"role": "tool", "tool_call_id": call["id"], "content": result_text},
                    ]
                    r2 = await client.post(
                        DEEPSEEK_URL,
                        headers={"Authorization": f"Bearer {DEEPSEEK_KEY}"},
                        json={"model": DEEPSEEK_MODEL, "messages": follow,
                              "thinking": DEEPSEEK_THINKING,
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
            "song": song_file, "song_title": song_title, "song_pending": song_pending,
            "cover": _cover_for(song_file)}


# ---- 按需找歌(2026-11-17 点播任意歌):go-music-dl web 服务实时搜索下载入库 ----
# 前提:music-dl web 服务在跑(music-dl.exe web -p 8099 --no-browser);bilibili 源实测无需 token
MUSIC_DL_URL = os.environ.get("MUSIC_DL_URL", "http://127.0.0.1:8099/music")
MUSIC_DL_DATA = os.environ.get("MUSIC_DL_DATA", os.path.join(
    os.environ.get("TEMP", "/tmp"), "wm_musicdl", "data", "downloads"))
# 搜歌源:bilibili 无需凭证;配好网易云 Cookie 后在 .env 改 MUSIC_FETCH_SOURCES=netease,bilibili(歌词随网易云源可用)
MUSIC_FETCH_SOURCES = os.environ.get("MUSIC_FETCH_SOURCES", "bilibili")
LYRICS_DIR = MUSIC_DIR / "lyrics"
LYRICS_DIR.mkdir(parents=True, exist_ok=True)
COVERS_DIR = MUSIC_DIR / "covers"
COVERS_DIR.mkdir(parents=True, exist_ok=True)
SONG_FETCH_TIMEOUT = 120  # 秒

_SONG_CARD_RE = re.compile(r'<li class="song-card"([^>]*)>')
_DATA_ATTR_RE = re.compile(r'data-([a-z-]+)="([^"]*)"')


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return (s or "track")[:40]


def _next_seq(group: str) -> int:
    n = 0
    if MUSIC_DIR.exists():
        for f in MUSIC_DIR.iterdir():
            m = re.match(rf"{group}_(\d+)_", f.name)
            if m:
                n = max(n, int(m.group(1)))
    return n + 1


def _register_playlist(group: str, fname: str, title: str, source: str):
    pl = json.loads((CONFIG / "playlist.json").read_text(encoding="utf-8"))
    g = pl["groups"].setdefault(group, {"keywords": [], "songs": []})
    entry = {"file": fname, "title": title[:40], "alias": [title[:12]], "source": source}
    g["songs"].append(entry)
    (CONFIG / "playlist.json").write_text(json.dumps(pl, ensure_ascii=False, indent=2), encoding="utf-8")
    return entry


class MusicFetchIn(BaseModel):
    query: str
    group: str = "songs"


@app.post("/api/music/fetch")
async def music_fetch_api(inp: MusicFetchIn):
    """点播曲库外任意歌:go-music-dl(bilibili 源)搜索→下载→入库→登记歌单。
    长轮询(最多 ~2 分钟),成功返回 {ok, song, title};失败 503 由前端 TTS 兜底。"""
    query = inp.query.strip()[:60]
    if not query:
        raise HTTPException(400, "empty query")
    # 1) 搜索(bilibili 源,25s~420s 过滤试听片段与超长合集)
    html = (await client_get(f"{MUSIC_DL_URL}/search",
                             params={"q": query, "sources": MUSIC_FETCH_SOURCES, "page": "1"})).text
    cards = []
    for attrs_html in _SONG_CARD_RE.findall(html):
        a = dict(_DATA_ATTR_RE.findall(attrs_html))
        try:
            dur = int(a.get("duration") or 0)
        except ValueError:
            dur = 0
        if 25 <= dur <= 420:
            cards.append(a)
    if not cards:
        raise HTTPException(503, f"没找到《{query}》的可用音频")
    with_cover = [c for c in cards if c.get("cover")]
    song = with_cover[0] if with_cover else cards[0]  # MV 类卡片常无封面,优先选带封面的
    # 2) 入下载队列
    body = {"request_id": f"wm-{int(time.time()*1000)}",
            "songs": [{"id": song.get("id", ""), "source": song.get("source", "bilibili"),
                       "name": song.get("name", ""), "artist": song.get("artist", ""),
                       "album": song.get("album", ""), "cover": song.get("cover", ""),
                       "extra": song.get("extra", ""), "embed": False}]}
    import httpx as _hx
    async with _hx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{MUSIC_DL_URL}/api/downloads/queue", json=body,
                         headers={"X-Requested-With": "XMLHttpRequest"})
        r.raise_for_status()
        # 3) 轮询下载记录(文件落盘由 music-dl 完成)
        deadline = time.time() + SONG_FETCH_TIMEOUT
        rel = None
        while time.time() < deadline:
            await asyncio.sleep(4)
            rec = (await c.get(f"{MUSIC_DL_URL}/api/downloads/records?page=1",
                               headers={"X-Requested-With": "XMLHttpRequest"})).json()
            for item in rec.get("records", []):
                if song["name"][:12] in (item.get("Name") or ""):
                    if item.get("Status") == "success":
                        rel = item.get("RelPath")
                        break
                    if item.get("Status") == "failed":
                        raise HTTPException(503, f"下载失败: {(item.get('Error') or '')[:80]}")
            if rel:
                break
        if not rel:
            raise HTTPException(503, "下载超时")
    # 4) 入库(ASCII 重命名)+登记歌单;PLAYLIST 缓存同步刷新
    # 产物定位优先 RelPath(records 精确给出;Name 可能含 𝐇𝐢-𝐑𝐞𝐬 类数学字母,与磁盘文件名不一致)
    src = None
    if rel:
        cand = os.path.join(MUSIC_DL_DATA, rel)
        if os.path.isfile(cand):
            src = cand
    if not src:
        for f in os.listdir(MUSIC_DL_DATA):
            if song["name"][:12] in f:
                src = os.path.join(MUSIC_DL_DATA, f)
                break
    if not src:
        raise HTTPException(503, "下载完成但未找到产物文件")
    group = inp.group if inp.group in PLAYLIST["groups"] else "songs"
    fname = "%s_%02d_%s.m4a" % (group, _next_seq(group), _slugify(song["name"]))
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, MUSIC_DIR / fname)
    entry = _register_playlist(group, fname, song["name"], song.get("source", "bilibili"))
    PLAYLIST.clear()
    PLAYLIST.update(json.loads((CONFIG / "playlist.json").read_text(encoding="utf-8")))
    # 5) 歌词:music-dl /lyric 端点拉 LRC(bilibili 无词,netease/qq 源有;失败静默不阻塞)
    lyric_saved = False
    try:
        lq = urllib.parse.urlencode({"id": song.get("id", ""), "source": song.get("source", ""),
                                     "name": song.get("name", ""), "artist": song.get("artist", ""),
                                     "album": song.get("album", ""), "duration": song.get("duration", 0),
                                     "format": "line"})
        lrc_body = (await client_get(f"{MUSIC_DL_URL}/lyric?{lq}")).text
        if lrc_body.strip() and "纯音乐" not in lrc_body[:30] and len(lrc_body) > 60:
            LYRICS_DIR.mkdir(parents=True, exist_ok=True)
            (LYRICS_DIR / (os.path.splitext(fname)[0] + ".lrc")).write_text(lrc_body, encoding="utf-8")
            lyric_saved = True
    except Exception as e:
        print(f"[music] 歌词获取失败(不阻塞): {e!r}")
    # 6) 封面:经 music-dl cover_proxy 代理拉图存本地(bilibili 封面 URL 直连有防盗链)
    cover_saved = None
    if song.get("cover"):
        try:
            img_resp = (await client_get(f"{MUSIC_DL_URL}/cover_proxy",
                                         params={"url": song["cover"], "source": song.get("source", "")}))
            if img_resp.status_code == 200 and len(img_resp.content) > 1000:  # proxy 是 chunked,无 content-length 头
                cov_name = os.path.splitext(fname)[0] + ".jpg"
                (COVERS_DIR / cov_name).write_bytes(img_resp.content)
                cover_saved = cov_name
        except Exception as e:
            print(f"[music] 封面获取失败(不阻塞): {e!r}")
    print(f"[music] 点播入库: {query} -> {fname} (歌词: {lyric_saved}, 封面: {bool(cover_saved)})")
    return {"ok": True, "song": fname, "title": entry["title"], "lyric": lyric_saved, "cover": cover_saved}


async def client_get(url: str, params: dict | None = None):
    import httpx as _hx
    async with _hx.AsyncClient(timeout=30) as c:
        return await c.get(url, params=params)


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

app.mount("/music-lyrics", StaticFiles(directory=str(LYRICS_DIR)), name="music-lyrics")
app.mount("/music-covers", StaticFiles(directory=str(COVERS_DIR)), name="music-covers")


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


# ---- R4 数学小游戏(docs/10):10 以内加减,会话内连答 5 题;支持中文数字作答 ----
MATH_GAMES = {}  # session_id -> {"count": 已答, "streak": 连对}
MATH_ROUNDS = 5
_MATH_START_KW = ("数学", "算术", "算算", "加法")
_MATH_EXIT_KW = ("不玩", "结束", "停止", "休息")
_ZH_NUM = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _math_q():
    """生成 10 以内加减题,返回 (算式显示, TTS 读法, 答案)。"""
    a, b = random.randint(0, 5), random.randint(0, 5)
    if random.random() < 0.5 or a < b:
        a, b = max(a, b), min(a, b)
        if random.random() < 0.5:
            return f"{a}+{b}", f"{a}加{b}", a + b
    return f"{a}-{b}", f"{a}减{b}", a - b


def _extract_number(text: str):
    """取第一个阿拉伯数字;否则尝试中文数字(含「十」「X十Y」)。无 → None。"""
    m = re.search(r"\d+", text)
    if m:
        return int(m.group())
    for zh, val in _ZH_NUM.items():
        if zh in text:
            if zh == "十":
                return 10
            m2 = re.search(r"([一二三四五六七八九]?)十([一二三四五六七八九]?)", text)
            if m2:
                tens = _ZH_NUM.get(m2.group(1), 1) * 10 if m2.group(1) else 10
                ones = _ZH_NUM.get(m2.group(2), 0) if m2.group(2) else 0
                return tens + ones
            return val
    return None


def _math_reply(pool, math_state=None):
    idx, reply = _pick_idx(pool)
    return {"reply": reply, "emo": EGGS["emo"].get(pool), "pool": pool, "idx": idx,
            "math": math_state, "source": "offline", "song": None, "song_title": None,
            "song_pending": None}


# ---- R5 猜谜语(docs/10):alias 判答;3 次不中自动提示,5 次/认输揭晓;谜面预生成 ----
RIDDLES = json.loads((CONFIG / "riddles.json").read_text(encoding="utf-8"))["riddles"]
RIDDLE_GAMES = {}  # session_id -> {"id":…, "miss": int}
_RIDDLE_START_KW = ("猜谜语", "谜语", "出谜语", "猜个谜")
_RIDDLE_GIVEUP_KW = ("不知道", "猜不出", "揭晓", "认输", "答案是什么")
_RIDDLE_EXIT_KW = ("不猜", "结束")


def _riddle_by_id(rid):
    return next((r for r in RIDDLES if r["id"] == rid), RIDDLES[0])


def _chat_resp(pool, idx, reply, extra=None):
    """离线响应统一形状(与 chat 返回字段对齐)。"""
    out = {"reply": reply, "emo": EGGS["emo"].get(pool), "pool": pool, "idx": idx,
           "source": "offline", "song": None, "song_title": None, "song_pending": None}
    if extra:
        out.update(extra)
    return out


# ---- R2 时间感知问候(docs/10):按时段选问候池,深夜自动转哄睡语气 ----
def _greeting_pool(hour: int):
    """0-23 时 → (池名, 表情)。深夜 23~5 哄睡,5~11 早,11~14 午,14~19 下午,19~23 晚。"""
    if 23 <= hour or hour < 5:
        return "greeting_night", "sleepy"
    if hour < 11:
        return "greeting_morning", "happy"
    if hour < 14:
        return "greeting_noon", "happy"
    if hour < 19:
        return "greeting_afternoon", "happy"
    return "greeting_evening", "happy"


@app.get("/api/greeting")
async def greeting():
    pool, emo = _greeting_pool(time.localtime().tm_hour)
    idx, text = _pick_idx(pool)
    return {"pool": pool, "idx": idx, "text": text, "emo": EGGS["emo"].get(pool, emo)}


# ---- R3 古诗小课堂(docs/10):config/poems.json 逐句领读,音频 poem_{id}_{n}.mp3 预生成 ----
POEMS = json.loads((CONFIG / "poems.json").read_text(encoding="utf-8"))["poems"]
_POEM_KEYWORDS = ("古诗", "背诗", "读诗", "念诗", "唐诗")


@app.get("/api/poem/random")
async def poem_random():
    return random.choice(POEMS)


# ---- R1 习惯打卡星星系统(docs/10):data/stars.json 持久化,打卡=星星+1 ----
STARS_FILE = PROJECT / "data" / "stars.json"
STAR_TASKS = {"brush": "刷牙", "tidy": "收拾玩具", "sleep": "早睡"}
_STAR_REPEAT_WINDOW = 60  # 同一任务 60s 内重复打卡不加分


def _load_stars() -> dict:
    try:
        data = json.loads(STARS_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "total" in data:
            return data
    except Exception:
        pass
    return {"total": 0, "log": [], "first_seen": time.strftime("%Y-%m-%d")}


def _save_stars(data: dict) -> None:
    STARS_FILE.parent.mkdir(exist_ok=True)
    STARS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


@app.get("/api/stars")
async def stars_get():
    """星星总览:总数 + 今日打卡数 + 相识首日(R11 成长纪念用)。"""
    data = _load_stars()
    today = time.strftime("%Y-%m-%d")
    return {"total": data.get("total", 0),
            "today": sum(1 for e in data.get("log", []) if str(e.get("ts", "")).startswith(today)),
            "first_seen": data.get("first_seen", today),
            "tasks": STAR_TASKS}


class StarIn(BaseModel):
    task: str


@app.post("/api/stars")
async def stars_post(inp: StarIn):
    """打卡:task ∈ {brush,tidy,sleep} → 星星+1,返回夸奖台词(池+序号对齐预生成音频)。"""
    if inp.task not in STAR_TASKS:
        raise HTTPException(400, f"unknown task: {inp.task}")
    data = _load_stars()
    now = time.time()
    today = time.strftime("%Y-%m-%d")
    recent = [e for e in data.get("log", [])
              if e.get("task") == inp.task and now - float(e.get("epoch", 0)) < _STAR_REPEAT_WINDOW]
    if recent:
        idx, reply = _pick_idx("star_repeat")
        return {"total": data.get("total", 0), "added": 0, "task": STAR_TASKS[inp.task],
                "reply": reply, "emo": EGGS["emo"].get("star_repeat"),
                "pool": "star_repeat", "idx": idx}
    idx, praise = _pick_idx("star_praise")
    data["total"] = data.get("total", 0) + 1
    data.setdefault("log", []).append({"ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                                       "epoch": now, "task": inp.task, "label": STAR_TASKS[inp.task]})
    data.setdefault("first_seen", today)
    _save_stars(data)
    return {"total": data["total"], "added": 1, "task": STAR_TASKS[inp.task],
            "reply": praise, "emo": EGGS["emo"].get("star_praise"),
            "pool": "star_praise", "idx": idx}


app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
