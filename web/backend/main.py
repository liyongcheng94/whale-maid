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
SYSTEM_PROMPT = (CONFIG / "server_prompt.txt").read_text(encoding="utf-8").strip()

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
    return {"deepseek": bool(DEEPSEEK_KEY), "model": DEEPSEEK_MODEL, "voice": TTS_VOICE}


@app.get("/api/eggs")
async def eggs():
    return EGGS


@app.post("/api/chat")
async def chat(inp: ChatIn):
    text = inp.text.strip()[:500]
    if not text:
        idx, reply = _pick_idx("fallback")
        return {"reply": reply, "emo": EGGS["emo"].get("fallback"), "pool": "fallback",
                "idx": idx, "source": "offline"}
    # 多轮记忆:系统提示 + 最近 N 轮 + 本句
    history = SESSIONS.setdefault(inp.session_id[:64], collections.deque(maxlen=SESSION_TURNS * 2))
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + list(history) + [{"role": "user", "content": text}]

    reply, emo, pool, idx, source = None, None, None, None, "offline"
    if DEEPSEEK_KEY:
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                r = await client.post(
                    DEEPSEEK_URL,
                    headers={"Authorization": f"Bearer {DEEPSEEK_KEY}"},
                    json={
                        "model": DEEPSEEK_MODEL,
                        "messages": messages,
                        "max_tokens": 100,
                        "temperature": 0.8,
                    },
                )
                r.raise_for_status()
                raw = (r.json()["choices"][0]["message"]["content"] or "").strip()
                if raw:
                    body, zh = _split_emo(raw)
                    if body:
                        reply, emo, source = body, EMO_ZH2EN.get(zh), "deepseek"
        except Exception as e:  # 网络/配额/超时——兜底,不冷场
            print(f"[chat] deepseek 失败,回落离线台词: {e!r}")
    if reply is None:
        reply, pool, idx, emo = _offline_reply(text)

    # 会话记忆(离线回复也入记忆,LLM 恢复后能接上刚才的话题)
    history.append({"role": "user", "content": text})
    history.append({"role": "assistant", "content": reply})
    # 本地对话日志:家长可查 + 排障;只落本地文件,不上传
    try:
        CHAT_LOG.parent.mkdir(exist_ok=True)
        with CHAT_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                                "session": inp.session_id[:64], "user": text,
                                "whale": reply, "source": source}, ensure_ascii=False) + "\n")
    except Exception:
        pass
    return {"reply": reply, "emo": emo, "pool": pool, "idx": idx, "source": source}


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


app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
