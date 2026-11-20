# -*- coding: utf-8 -*-
"""复位设备并抓取串口日志,输出关键行并给出绿/红判定。

阶梯烧录验证协议(Phase D):
  复位 → 抓 N 秒 → 断言:
    绿: 出现主题刷新/资产加载标记,且无崩溃标记、无重复开机横幅(boot loop)
    红: Guru Meditation / abort / 反复 "esp32-s3-touch-lcd-1.46" 开机横幅

用法:python watch_serial.py [秒数=90] [输出文件=serial_capture.txt]
"""
import sys
import time

import serial

PORT = "COM3"
BAUD = 115200

GREEN_KEYS = ["Refreshing display theme", "theme", "assets", "emoji", "srmodels",
              "wake_word", "WiFi", "wifi", "IP", "Connected", "Listening"]
RED_KEYS = ["Guru Meditation", "abort()", "panic", "assert", "LoadProhibited",
            "StoreProhibited", "InstrFetchProhibited", "rebooting...", "rst:0x10"]
BANNER = "esp32-s3-touch-lcd-1.46"


def main():
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 90
    out_path = sys.argv[2] if len(sys.argv) > 2 else r"D:\project\whale-maid\tools\serial_capture.txt"
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    s = serial.Serial(PORT, BAUD, timeout=2)
    s.setDTR(False)
    s.setRTS(True)
    time.sleep(0.1)
    s.setRTS(False)
    time.sleep(0.3)
    s.reset_input_buffer()
    out = b""
    t0 = time.time()
    while time.time() - t0 < seconds:
        data = s.read(2048)
        if data:
            out += data
    s.close()

    text = out.decode("utf-8", errors="replace")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(text)

    lines = text.splitlines()
    banners = sum(1 for l in lines if BANNER in l and ("report" in l or "Project" in l or "version" in l.lower()))
    greens = [l for l in lines if any(k in l for k in GREEN_KEYS)]
    reds = [l for l in lines if any(k in l for k in RED_KEYS)]

    print(f"=== capture {seconds:.0f}s, {len(lines)} lines -> {out_path}")
    print("--- GREEN markers (first 15):")
    print("\n".join(greens[:15]) or "(none)")
    print(f"--- boot banners: {banners} (>=3 视为 boot loop)")
    print("--- RED markers:")
    print("\n".join(reds[:10]) or "(none)")
    verdict = "PASS" if greens and not reds and banners < 3 else "FAIL"
    print(f"=== VERDICT: {verdict}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
