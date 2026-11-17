"""whale-maid 一键验证闸门聚合器(deepseek-harness run-gates 思想轻量版)。

原则:CI 与本地跑同一套定义——`python scripts/verify.py`,退出码 0=全绿。
闸门(每项 FAIL 即退出非零;WARN 只提示):
  docs    文档引用卫生:md 里引用的 docs/scripts/config 文件真实存在
  patch   固件 patch 合同:四件套+构建链注册标记齐全
  config  人设/彩蛋机器合同:池非空、emo 对齐、三处人设同步(复用 tests 口径)
  audio   彩蛋音频产物:mp3 覆盖全部池(未生成环境 WARN)
  web     web demo 冒烟:后端可编译、前端关键标记齐全
  tests   pytest(web/backend,环境无 pytest 时 WARN)

Python 3.9 兼容,零第三方依赖。
"""

import json
import py_compile
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FAILURES = []
WARNS = []


def gate(name):
    def deco(fn):
        def run():
            try:
                problems = fn() or []
            except Exception as e:  # 闸门自身异常也算 FAIL
                problems = [f"闸门异常: {e!r}"]
            if problems:
                FAILURES.extend(f"[{name}] {p}" for p in problems)
                print(f"[FAIL] {name}: {len(problems)} 项")
                for p in problems:
                    print(f"       - {p}")
            else:
                print(f"[PASS] {name}")
        setattr(run, "_is_gate", True)
        run.__name__ = fn.__name__
        run._gate_name = name
        return run
    return deco


def md_files():
    return [ROOT / "README.md"] + sorted((ROOT / "docs").glob("*.md"))


@gate("docs")
def gate_docs():
    """md 文件里引用的仓库内文件必须存在(已知外部引用白名单豁免)。"""
    problems = []
    exists_whitelist = ("任务书", "xiaozhi-esp32", "xiaozhi-esp32-server", "http", "model.pt")
    for md in md_files():
        text = md.read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(r"`((?:docs|scripts|config|firmware|web)/[\w\-./]+\.(?:md|py|json|yaml|sh|txt))`", text):
            rel = m.group(1)
            if any(w in rel for w in exists_whitelist):
                continue
            if not (ROOT / rel).exists():
                problems.append(f"{md.relative_to(ROOT)} 引用不存在的 {rel}")
        for m in re.finditer(r"\b(docs/[\w\-.]+\.(?:md|json))\b", text):
            rel = m.group(1)
            if any(w in rel for w in exists_whitelist):
                continue
            if not (ROOT / rel).exists():
                problems.append(f"{md.relative_to(ROOT)} 裸引用不存在的 {rel}")
    return problems


@gate("patch")
def gate_patch():
    """whale-maid 板 patch 合同(docs/02 §三 四件套+三处注册)。"""
    problems = []
    patches = sorted((ROOT / "firmware" / "patches").glob("*.patch"))
    if not patches:
        return ["firmware/patches/ 下没有任何 patch"]
    text = patches[0].read_text(encoding="utf-8", errors="ignore")
    for marker in ("main/boards/whale-maid/config.json", "main/boards/whale-maid/config.h",
                   "main/boards/whale-maid/whale_maid_board.cc", "BOARD_TYPE_WHALE_MAID",
                   'set(BOARD_DIR "whale-maid")', 'BOARD_TYPE_WHALE_MAID', "GPIO_NUM_21"):
        if marker not in text:
            problems.append(f"patch 缺关键标记: {marker}")
    if "bread-compact-wifi/config.h" in text and "diff --git a/main/boards/bread-compact-wifi" in text:
        problems.append("patch 试图修改 bread-compact-wifi 板文件(OTA 变砖红线)")
    return problems


@gate("config")
def gate_config():
    """人设/彩蛋机器合同(与 web/backend/tests/test_eggs.py 同口径)。"""
    problems = []
    try:
        eggs = json.loads((ROOT / "config" / "eggs_birthday.json").read_text(encoding="utf-8"))
    except Exception as e:
        return [f"eggs_birthday.json 解析失败: {e!r}"]
    valid_emo = {"normal", "happy", "shy", "pouty", "sad", "sleepy"}
    for pool, lines in eggs["triggers"].items():
        if not (isinstance(lines, list) and lines and all(isinstance(x, str) and x.strip() for x in lines)):
            problems.append(f"触发池 {pool} 为空或含空台词")
        if not re.fullmatch(r"[a-z_]+", pool):
            problems.append(f"池名 {pool} 不符合固件符号规范(小写+下划线)")
    if set(eggs["emo"]) != set(eggs["triggers"]):
        problems.append("emo 映射与触发池不对齐")
    if any(v not in valid_emo for v in eggs["emo"].values()):
        problems.append("emo 值超出前端六态")
    for trigger in eggs["keyword_map"]:
        if trigger not in eggs["triggers"]:
            problems.append(f"keyword_map 指向不存在的池 {trigger}")
    prompt = (ROOT / "config" / "server_prompt.txt").read_text(encoding="utf-8")
    for tag in ("开心", "害羞", "傲娇", "难过", "困"):
        if f"({tag})" not in prompt:
            problems.append(f"server_prompt.txt 缺表情标记 ({tag})")
    yaml_text = (ROOT / "firmware" / "server" / "whalemaid.config.yaml").read_text(encoding="utf-8")
    if "鱼片" not in yaml_text or "(开心)" not in yaml_text:
        problems.append("whalemaid.config.yaml 人设/表情协议与 config/ 未同步(标准模式·大肥鱼)")
    if "冉冉姐姐" not in (ROOT / "config" / "persona.md").read_text(encoding="utf-8"):
        problems.append("persona.md 缺冉冉姐姐人设")
    return problems


@gate("audio")
def gate_audio():
    """彩蛋 mp3 产物覆盖全部池(未生成的环境降级 WARN)。"""
    mp3_dir = ROOT / "assets_audio" / "mp3"
    if not mp3_dir.exists():
        WARNS.append("[audio] assets_audio/mp3 不存在(未跑 make_egg_audio.py)")
        return []
    eggs = json.loads((ROOT / "config" / "eggs_birthday.json").read_text(encoding="utf-8"))
    problems = []
    for pool, lines in eggs["triggers"].items():
        for i in range(1, len(lines) + 1):
            if not (mp3_dir / f"{pool}_{i}.mp3").exists():
                problems.append(f"缺音频 {pool}_{i}.mp3(跑 scripts/make_egg_audio.py)")
    return problems


@gate("web")
def gate_web():
    """web demo 冒烟:后端可编译 + 前端关键标记。"""
    problems = []
    try:
        py_compile.compile(str(ROOT / "web" / "backend" / "main.py"), doraise=True)
    except Exception as e:
        problems.append(f"web/backend/main.py 编译失败: {e!r}")
    html = (ROOT / "web" / "frontend" / "index.html").read_text(encoding="utf-8")
    for marker in ("/api/chat", "/api/eggs", "setEmo", "whaleSvg", "data-pool=\"touch_head\"", "data-pool=\"touch_belly\""):
        if marker not in html:
            problems.append(f"index.html 缺关键标记: {marker}")
    return problems


@gate("tests")
def gate_tests():
    """pytest(web/backend);环境无 pytest 时 WARN 不阻塞。"""
    import importlib.util
    import subprocess
    if importlib.util.find_spec("pytest") is None:
        WARNS.append("[tests] 当前 Python 无 pytest,跳过(装 requirements-dev.txt)")
        return []
    r = subprocess.run([sys.executable, "-m", "pytest"], cwd=str(ROOT / "web" / "backend"),
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        tail = (r.stdout or r.stderr).strip().splitlines()[-5:]
        return ["pytest 失败: " + " | ".join(tail)]
    return []


def main():
    gates = [v for k, v in sorted(globals().items()) if k.startswith("gate_") and callable(v) and getattr(v, "_is_gate", False)]
    print(f"whale-maid verify · {len(gates)} gates · root={ROOT}")
    print("-" * 60)
    for g in gates:
        g()
    print("-" * 60)
    for w in WARNS:
        print(w)
    if FAILURES:
        print(f"结果: {len(FAILURES)} 项失败")
        return 1
    print("结果: 全绿 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
