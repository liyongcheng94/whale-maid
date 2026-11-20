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
    if "冉冉姐姐" not in yaml_text or "(开心)" not in yaml_text:
        problems.append("whalemaid.config.yaml 人设/表情协议与 config/ 未同步(标准模式·大肥鱼)")
    if "冉冉姐姐" not in (ROOT / "config" / "persona.md").read_text(encoding="utf-8"):
        problems.append("persona.md 缺冉冉姐姐人设")
    # 歌单机器合同(config/playlist.json;2026-11-17 唱歌升级)
    try:
        pl = json.loads((ROOT / "config" / "playlist.json").read_text(encoding="utf-8"))
    except Exception as e:
        return problems + [f"playlist.json 解析失败: {e!r}"]
    if list(pl["groups"].keys()) != ["birthday", "hachimi", "songs"]:
        problems.append("playlist.json 组顺序即路由优先级,须为 birthday/hachimi/songs")
    alias_seen = {}
    for gname, g in pl["groups"].items():
        if not (isinstance(g.get("keywords"), list) and g["keywords"]):
            problems.append(f"playlist 组 {gname} 缺 keywords")
        for s in g.get("songs", []):
            if not re.fullmatch(r"[a-z0-9_]+\.(m4a|mp3)", s.get("file", "")):
                problems.append(f"playlist {gname}/{s.get('file')} 文件名须 ASCII 小写下划线")
            for k in ("title", "alias", "source"):
                if not s.get(k):
                    problems.append(f"playlist {gname}/{s.get('file')} 缺 {k}")
            for a in s.get("alias", []):
                low = a.lower()
                if low in alias_seen and alias_seen[low] != gname:
                    problems.append(f"playlist alias「{a}」跨组冲突({alias_seen[low]} vs {gname})")
                alias_seen[low] = gname
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
    # 歌单音频对齐(assets_audio/music;缺失时 WARN 不 FAIL,与彩蛋音频同口径)
    music_dir = ROOT / "assets_audio" / "music"
    if not music_dir.exists():
        WARNS.append("[audio] assets_audio/music 不存在(未跑 scripts/music_fetch.py)")
        return problems
    pl = json.loads((ROOT / "config" / "playlist.json").read_text(encoding="utf-8"))
    registered = set()
    for g in pl["groups"].values():
        for s in g["songs"]:
            registered.add(s["file"])
            if not (music_dir / s["file"]).exists():
                problems.append(f"playlist 登记但磁盘缺失: {s['file']}(跑 scripts/music_fetch.py)")
    for f in music_dir.iterdir():
        if f.suffix in (".m4a", ".mp3") and f.name not in registered:
            WARNS.append(f"[audio] music 目录孤儿文件未登记歌单: {f.name}")
    return problems


@gate("web")
def gate_web():
    """学园三面冒烟:后端可编译 + 头像墙/孩子端/家长端/legacy 关键标记。"""
    problems = []
    try:
        py_compile.compile(str(ROOT / "web" / "backend" / "main.py"), doraise=True)
    except Exception as e:
        problems.append(f"web/backend/main.py 编译失败: {e!r}")
    checks = {
        "index.html": ["/api/profiles", "小鲸灵学园"],
        "kid.html": ["/api/learn/map", "/api/learn/next", "/api/learn/answer", "/api/learn/daily"],
        "parent.html": ["/api/parent/pin/", "/api/parent/overview", "家长控制室"],
        "legacy.html": ["/api/chat", "setEmo"],
    }
    for name, markers in checks.items():
        f = ROOT / "web" / "frontend" / name
        if not f.exists():
            problems.append(f"{name} 不存在")
            continue
        html = f.read_text(encoding="utf-8")
        for marker in markers:
            if marker not in html:
                problems.append(f"{name} 缺关键标记: {marker}")
    return problems


@gate("learn")


@gate("learn")
def gate_learn():
    """学园课程合同要点:四下单元/脚手架不泄露/图谱对齐(轻量版,test_learn_content 全面版在 CI)。"""
    problems = []
    try:
        math = json.loads((ROOT / "config" / "curriculum" / "g4s2_math.json").read_text(encoding="utf-8"))
    except Exception as e:
        return [f"g4s2_math.json 解析失败: {e!r}"]
    playable = [u for u in math["units"] if not u.get("planned")]
    if not playable:
        problems.append("没有可玩单元")
    for u in playable:
        for l in u.get("levels", []):
            for qq in l.get("questions", []):
                if not qq.get("scaffold"):
                    problems.append(f"{qq['id']} 缺脚手架")
                if qq.get("tier") not in ("basic", "standard", "challenge"):
                    problems.append(f"{qq['id']} 档位非法")
                if len(str(qq["answer"])) >= 2 and re.search(
                        rf'(?<!\d){re.escape(str(qq["answer"]))}(?!\d)', qq.get("scaffold", "")):
                    problems.append(f"{qq['id']} 脚手架泄露答案")
    kg = json.loads((ROOT / "config" / "curriculum" / "knowledge_graph.json").read_text(encoding="utf-8"))
    kg_ids = {t["id"] for t in kg["topics"]}
    for u in playable:
        for l in u.get("levels", []):
            if l.get("topic") not in kg_ids:
                problems.append(f"关卡 {l['id']} 的 topic 不在图谱")
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
    # Windows GBK 控制台打不出 ✓/✗,强制 utf-8 输出
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
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
