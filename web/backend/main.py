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
import json
import os
import random
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


def _pick(trigger: str) -> str:
    pool = EGGS["triggers"].get(trigger) or EGGS["triggers"]["fallback"]
    return random.choice(pool)


def _offline_reply(text: str) -> str:
    """关键词 → 彩蛋池;无命中随机兜底。keyword_map 的书写顺序即优先级。"""
    for trigger, words in EGGS.get("keyword_map", {}).items():
        if any(w in text for w in words):
            return _pick(trigger)
    return _pick("fallback")


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
        return {"reply": _pick("fallback"), "source": "offline"}
    if DEEPSEEK_KEY:
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                r = await client.post(
                    DEEPSEEK_URL,
                    headers={"Authorization": f"Bearer {DEEPSEEK_KEY}"},
                    json={
                        "model": DEEPSEEK_MODEL,
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": text},
                        ],
                        "max_tokens": 100,
                        "temperature": 0.8,
                    },
                )
                r.raise_for_status()
                reply = (r.json()["choices"][0]["message"]["content"] or "").strip()
                if reply:
                    return {"reply": reply, "source": "deepseek"}
        except Exception as e:  # 网络/配额/超时——兜底,不冷场
            print(f"[chat] deepseek 失败,回落离线台词: {e!r}")
    return {"reply": _offline_reply(text), "source": "offline"}


@app.get("/api/tts")
async def tts(text: str = Query(..., max_length=150)):
    try:
        import edge_tts

        text = text.strip()
        if not text:
            raise HTTPException(400, "empty text")
        cache = TTS_CACHE / f"{hashlib.md5(text.encode()).hexdigest()}.mp3"
        if not cache.exists():
            await edge_tts.Communicate(text, TTS_VOICE).save(str(cache))
        return FileResponse(cache, media_type="audio/mpeg", filename="whale.mp3")
    except HTTPException:
        raise
    except Exception as e:  # edge-tts/网络不可用 → 前端回落 speechSynthesis
        raise HTTPException(503, f"tts unavailable: {e!r}")


app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
