# -*- coding: utf-8 -*-
"""假设备 WS 客户端:端到端验证语音点歌(play_music→opus 音频帧)。

流程:连 ws://192.168.1.9:8000/xiaozhi/v1/(带 device-id 头)→ hello 握手 →
发文本指令(listen.text 跳过 ASR)→ 断言:
  1) 收到 stt 消息(识别回显)
  2) 收到大量二进制 opus 帧(歌在流)
  3) 服务端日志出现「找到最匹配的歌曲」(另查 server log)
用法:venv311 python tools/test_music_ws.py [指令文本] [收流秒数=45]
"""
import asyncio
import json
import sys
import time

import websockets

WS_URL = "ws://192.168.1.9:8000/xiaozhi/v1/"
DEVICE_ID = "test-music-client-001"


async def main():
    text = sys.argv[1] if len(sys.argv) > 1 else "放一首孤勇者"
    listen_secs = float(sys.argv[2]) if len(sys.argv) > 2 else 45
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    frames = 0
    texts = []
    closed_by = None
    try:
        conn = websockets.connect(
            WS_URL, max_size=2**22, ping_interval=5,
            additional_headers={"device-id": DEVICE_ID, "client-id": DEVICE_ID},
        )
    except TypeError:
        conn = websockets.connect(
            WS_URL, max_size=2**22, ping_interval=5,
            extra_headers={"device-id": DEVICE_ID, "client-id": DEVICE_ID},
        )
    async with conn as ws:
        hello = {
            "version": 1, "type": "hello", "transport": "websocket",
            "device_id": DEVICE_ID, "client_id": DEVICE_ID,
            "audio_params": {"format": "opus", "sample_rate": 16000, "channels": 1, "frame_duration": 60},
        }
        await ws.send(json.dumps(hello))

        # 等 server hello(吞掉中途的欢迎音频二进制帧)
        server_hello = None
        for _ in range(50):
            msg = await asyncio.wait_for(ws.recv(), 10)
            if isinstance(msg, bytes):
                continue
            j = json.loads(msg)
            if j.get("type") == "hello":
                server_hello = j
                break
        print("<< hello:", "OK" if server_hello else "NONE", str(server_hello or "")[:120])

        await ws.send(json.dumps({"type": "listen", "mode": "auto", "state": "detect", "text": text}))
        print(f">> listen text: {text}")

        t0 = time.time()
        try:
            while time.time() - t0 < listen_secs:
                msg = await asyncio.wait_for(ws.recv(), 15)
                if isinstance(msg, bytes):
                    frames += 1
                    if frames % 200 == 0:
                        print(f"   ... {frames} opus frames")
                else:
                    j = json.loads(msg)
                    t = j.get("type")
                    if t == "tts":
                        texts.append(f"tts:{j.get('state')}")
                    elif t == "stt":
                        texts.append(f"stt:{j.get('text')}")
                    elif t == "llm":
                        texts.append(f"llm:{j.get('emotion', '')}{j.get('text', '')[:50]}")
                    else:
                        texts.append(f"{t}:{json.dumps(j, ensure_ascii=False)[:80]}")
        except (asyncio.TimeoutError, TimeoutError):
            pass
        except websockets.exceptions.ConnectionClosed as e:
            closed_by = f"server closed: {e}"

    dur = listen_secs
    print(f"\n=== {dur:.0f}s 窗口:opus 帧 {frames} 个" + (f"({closed_by})" if closed_by else ""))
    print("=== 控制消息:")
    for t in texts[:15]:
        print("  ", t)
    has_stt = any(x.startswith("stt:") for x in texts)
    verdict = "PASS" if frames > 50 and has_stt else "FAIL"
    print(f"=== VERDICT: {verdict}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
