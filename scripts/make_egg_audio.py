"""生日彩蛋 TTS 预生成:config/eggs_birthday.json → mp3(edge-tts)→ wav(ffmpeg,可选)。

产物:
  assets_audio/mp3/<name>.mp3   网页/调试直接可用
  assets_audio/wav/<name>.wav   16-bit PCM 24kHz mono,供上游 ogg_converter 转 ogg 嵌固件
                                (需 ffmpeg;缺失时跳过并提示)

命名遵循 docs/06 规范:小写+下划线,池名_序号(touch_head_1 / birthday_2 …)。
运行(任一装有 edge-tts 的 Python):
  python scripts/make_egg_audio.py [--voice zh-CN-XiaoyiNeural]
嵌入固件:wav → src/xiaozhi-esp32/scripts/ogg_converter/xiaozhi_ogg_converter.py → ogg
  → 拷入 main/assets/common/ → 重编译(见 docs/02 §四;hello_master 同名覆盖即生日开机问候)。
"""

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EGGS_JSON = ROOT / "config" / "eggs_birthday.json"
MP3_DIR = ROOT / "assets_audio" / "mp3"
WAV_DIR = ROOT / "assets_audio" / "wav"


async def synth(text: str, voice: str, out: Path) -> None:
    import edge_tts

    await edge_tts.Communicate(text, voice).save(str(out))


def to_wav(mp3: Path, wav: Path) -> bool:
    if not shutil.which("ffmpeg"):
        return False
    # 固件输出采样率 24000(docs/00 §二 I2S OUT),16-bit 单声道 PCM
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3),
         "-ar", "24000", "-ac", "1", "-sample_fmt", "s16", str(wav)],
        check=True,
    )
    return True


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--voice", default="zh-CN-XiaoyiNeural")
    args = ap.parse_args()

    data = json.loads(EGGS_JSON.read_text(encoding="utf-8"))
    MP3_DIR.mkdir(parents=True, exist_ok=True)
    WAV_DIR.mkdir(parents=True, exist_ok=True)

    have_ffmpeg = bool(shutil.which("ffmpeg"))
    if not have_ffmpeg:
        print("!! ffmpeg 不在 PATH:只生成 mp3;装好后再跑一次即补 wav(ogg 链需要 ffmpeg)")

    jobs = []  # (name, text)
    for pool, lines in data["triggers"].items():
        for i, text in enumerate(lines, 1):
            jobs.append((f"{pool}_{i}", text))
    # R3 古诗小课堂:poems.json 逐首生成 开场(0)+逐句(1..n)
    poems_path = ROOT / "config" / "poems.json"
    if poems_path.exists():
        poems = json.loads(poems_path.read_text(encoding="utf-8"))["poems"]
        for poem in poems:
            intro = f"跟我一起背《{poem['title']}》!作者,{poem['author']}。"
            jobs.append((f"poem_{poem['id']}_0", intro))
            for i, line in enumerate(poem["lines"], 1):
                jobs.append((f"poem_{poem['id']}_{i}", line))

    failed = []
    for name, text in jobs:
        mp3 = MP3_DIR / f"{name}.mp3"
        try:
            if not mp3.exists():
                await synth(text, args.voice, mp3)
            wav_ok = to_wav(mp3, WAV_DIR / f"{name}.wav") if have_ffmpeg else False
            print(f"ok {name:18s} mp3={mp3.stat().st_size:>6d}B" + (" wav ✓" if wav_ok else ""))
        except Exception as e:
            failed.append(name)
            print(f"FAIL {name}: {e!r}")

    print(f"\n共 {len(jobs)} 句,失败 {len(failed)}。")
    if failed:
        print("失败清单:", ", ".join(failed))
        return 1
    print("下一步:wav → ogg_converter(需 ffmpeg)→ main/assets/common/ → 重编译(docs/02 §四)。")
    print("固件触发映射:touch_head_* → 摸头随机池;touch_belly_* → 摸肚;birthday_* → 生日模式;"
          "greeting_1 同名覆盖 hello_master 即生日开机问候。")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
