# -*- coding: utf-8 -*-
"""R114 伴听白噪音生成(纯 stdlib,无第三方依赖)。

产物:assets_audio/noise/{white,pbrown,waves}.wav(各 60s,22050Hz 16-bit 单声道)
- white: 白噪音(掩盖环境杂音)
- pbrown: 布朗噪音(更低沉,像雨声)
- waves: 缓慢起伏的布朗噪音(像海浪,贴合鲸鱼主题)
运行:python scripts/make_noise.py(约 10 秒;产物 gitignore,可重复生成)
"""
import math
import random
import struct
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets_audio" / "noise"
SR = 22050
SECONDS = 60
MAXAMP = 32767 * 0.55  # 留余量防爆音


def write_wav(name, samples):
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        frames = b"".join(struct.pack("<h", max(-32767, min(32767, int(s * MAXAMP)))) for s in samples)
        w.writeframes(frames)
    print(f"ok {path.name} ({path.stat().st_size // 1024}KB)")


def gen_white():
    rnd = random.Random(42)
    return [rnd.uniform(-1, 1) for _ in range(SR * SECONDS)]


def gen_brown():
    rnd = random.Random(7)
    out, last = [], 0.0
    for _ in range(SR * SECONDS):
        last = (last + 0.02 * rnd.uniform(-1, 1)) / 1.02
        out.append(last * 3.5)
    return out


def gen_waves():
    """布朗噪音叠加缓慢的音量起伏,模拟海浪。"""
    base = gen_brown()
    rnd = random.Random(11)
    swell = []
    phase = 0.0
    for i, v in enumerate(base):
        phase += 2 * math.pi * 0.08 / SR
        swell.append(v * (0.55 + 0.45 * math.sin(phase * 3)))
    return swell


if __name__ == "__main__":
    import sys
    sys.setrecursionlimit(10000)
    write_wav("white", gen_white())
    write_wav("pbrown", gen_brown())
    write_wav("waves", gen_waves())
