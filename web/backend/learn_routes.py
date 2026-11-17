"""小鲸灵学园学习路由(双身份、自适应、判答、家长总览)。

设计对齐 docs/prd/xueyuan_prd_v1.md:
- 身份隔离:孩子端端点无鉴权直接用;家长端点全部要求 X-Parent-Token(civideo 模式:PIN 服务端校验+失败限流)。
- 自适应:70%~85% 心流区间,连对 2 升一档、连错 2 降一档并插入脚手架提示(不给答案),调整理由写入 adjust_log。
- 内容:config/curriculum/g4s2_math.json + knowledge_graph.json(裁剪自 cn-math-taxonomy)。
"""

import json
import random
import re
import time
from pathlib import Path

import httpx  # noqa: F401  (保持与 main 同一依赖面)
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

import store

router = APIRouter(prefix="/api")

CURRICULUM_DIR = Path(__file__).resolve().parent.parent.parent / "config" / "curriculum"
CURRICULUM = json.loads((CURRICULUM_DIR / "g4s2_math.json").read_text(encoding="utf-8"))
KG = json.loads((CURRICULUM_DIR / "knowledge_graph.json").read_text(encoding="utf-8"))
PROFILES = json.loads((Path(__file__).resolve().parent.parent.parent / "config" / "profiles.json")
                      .read_text(encoding="utf-8"))

TIERS = ["basic", "standard", "challenge"]
TIER_CN = {"basic": "基础", "standard": "标准", "challenge": "挑战"}
MATH_ROUNDS = 5          # 每局题数
FLOW_LOW, FLOW_HIGH = 0.70, 0.85
LEVELS = [(0, "新手航海员"), (200, "见习研究员"), (600, "运算工程师"), (1500, "学园博士"), (3000, "学园传说")]

# 内存会话(重启即失;进度/XP 每次作答即时落盘)
LEARN_SESSIONS = {}      # (child, session) -> {level, seen[], count, streak, results[], attempts{qid:n}, daily:bool}

_ALL_Q = {}
for _u in CURRICULUM["units"]:
    for _l in _u.get("levels", []):
        for _q in _l.get("questions", []):
            _ALL_Q[_q["id"]] = dict(_q, level=_l["id"], unit=_u["id"], topic=_l["topic"])


def _topic_name(topic_id):
    t = next((x for x in KG["topics"] if x["id"] == topic_id), None)
    return t["name"] if t else topic_id


def _prereq_hint(topic: str):
    """R7 先修链归因:优先 hard 边,返回最近的可复习先修点(含诊断问题,不给答案)。"""
    edges = [e for e in KG["edges"] if e["topicId"] == topic and e["strength"] == "hard"] \
        or [e for e in KG["edges"] if e["topicId"] == topic]
    if not edges:
        return None
    pid = edges[0]["prerequisiteId"]
    node = next((t for t in KG["topics"] if t["id"] == pid), None)
    if not node:
        return None
    dq = node.get("diagnostic_question", {})
    return {"id": pid, "name": node["name"], "chapter": node.get("chapter", ""),
            "question": dq.get("question", "")}


def _verify_answer(q, user_answer) -> bool:
    """数值判答:浮点容差;题目带 verify 表达式时双重核验(表达式只允许数字与四则符号)。"""
    try:
        ans = float(user_answer)
    except (TypeError, ValueError):
        return False
    if abs(ans - float(q["answer"])) < 1e-9:
        v = q.get("verify")
        if v:
            expr = re.sub(r"[0-9+\-*/(). ]", "", str(v))
            if expr:  # verify 含非法字符,不信任
                return True
            try:
                return abs(eval(str(v)) - float(q["answer"])) < 1e-9
            except Exception:
                return True
        return True
    return False


def _tier_shift(tier: str, up: bool):
    i = TIERS.index(tier)
    j = max(0, min(len(TIERS) - 1, i + (1 if up else -1)))
    return TIERS[j]


def _pick_question(tier: str, topic: str, seen):
    pool = [q for q in _ALL_Q.values() if q["topic"] == topic and q["tier"] == tier and q["id"] not in seen]
    if not pool:  # 该档位耗尽 → 相邻档位
        i = TIERS.index(tier)
        for d in (1, -1, 2, -2):
            j = i + d
            if 0 <= j < len(TIERS):
                pool = [q for q in _ALL_Q.values()
                        if q["topic"] == topic and q["tier"] == TIERS[j] and q["id"] not in seen]
                if pool:
                    break
    if not pool:  # 兜底:该话题任意未做过的题
        pool = [q for q in _ALL_Q.values() if q["topic"] == topic and q["id"] not in seen]
    if not pool:
        pool = [q for q in _ALL_Q.values() if q["id"] not in seen]
    return random.choice(pool) if pool else None


def _question_payload(q, tier):
    return {"qid": q["id"], "prompt": q["prompt"], "tier": tier,
            "tier_cn": TIER_CN[tier], "level": q["level"], "topic": q["topic"]}


def _level_meta():
    out = []
    for u in CURRICULUM["units"]:
        out.append({"id": u["id"], "name": u["name"], "order": u["order"],
                    "planned": bool(u.get("planned")),
                    "levels": [{"id": l["id"], "name": l["name"], "count": len(l.get("questions", []))}
                               for l in u.get("levels", [])]})
    return out


# ---------------- 孩子端(无鉴权,直接用) ----------------

@router.get("/profiles")
async def profiles():
    return {"children": [{"id": c["id"], "name": c["name"], "age": c["age"],
                          "avatar": c["avatar"], "locked": c.get("locked", False),
                          "lock_note": c.get("lock_note", "")} for c in PROFILES["children"]]}


@router.get("/learn/map")
async def learn_map(child: str = Query(...)):
    learn = store.load_learn(child)
    meta = _level_meta()
    for u in meta:
        for l in u["levels"]:
            st = learn.get("levels", {}).get(l["id"], {})
            l["best"] = st.get("best")
            l["done"] = bool(st.get("done"))
    return {"child": child, "units": meta, "xp": learn.get("xp", 0),
            "title": _title_for(learn.get("xp", 0)), "badges": _unit_badges(learn),
            "first_seen": learn.get("first_seen")}


UNIT_BADGES = {"u1": "四则运算骑士", "u3": "运算律学徒", "u4": "小数探索家"}


def _unit_badges(learn: dict):
    """R9 成长徽章:单元内全部关卡 done 即解锁(只增不消耗)。"""
    badges = learn.setdefault("badges", [])
    for u in CURRICULUM["units"]:
        levels = u.get("levels", [])
        if not levels or any(not learn.get("levels", {}).get(l["id"], {}).get("done") for l in levels):
            continue
        badge = UNIT_BADGES.get(u["id"])
        if badge and badge not in badges:
            badges.append(badge)
    return badges


def _title_for(xp: int):
    name = LEVELS[0][1]
    for threshold, lv in LEVELS:
        if xp >= threshold:
            name = lv
    return name


@router.get("/learn/next")
async def learn_next(child: str = Query(...), level: str = Query(...), session: str = Query(...)):
    """自适应出题:按孩子-话题的档位状态选题;session 内存会话计数。"""
    learn = store.load_learn(child)
    lv = next((l for u in CURRICULUM["units"] for l in u.get("levels", []) if l["id"] == level), None)
    if lv is None:
        raise HTTPException(404, f"unknown level {level}")
    if lv["topic"] not in [t["id"] for t in KG["topics"]]:
        raise HTTPException(500, f"level topic not in knowledge graph: {lv['topic']}")
    topic_state = learn.setdefault("topic_state", {}).setdefault(lv["topic"], {"tier": "standard"})
    tier = topic_state.get("tier", "standard")
    key = (child, session)
    sess = LEARN_SESSIONS.setdefault(key, {"level": level, "seen": [], "count": 0,
                                           "streak": 0, "results": [], "attempts": {}, "daily": False})
    seen = set(sess["seen"])
    q = _pick_question(tier, lv["topic"], seen)
    if q is None:
        raise HTTPException(503, "题库已用完")
    sess["seen"].append(q["id"])
    return {"session": session, "child": child, "level": level, "count": sess["count"],
            "total": MATH_ROUNDS, "tier": tier, **_question_payload(q, tier)}


class AnswerIn(BaseModel):
    child: str
    session: str
    qid: str
    answer: str
    time_s: float = 0


@router.post("/learn/answer")
async def learn_answer(inp: AnswerIn):
    q = _ALL_Q.get(inp.qid)
    if q is None:
        raise HTTPException(404, "unknown question")
    key = (inp.child, inp.session)
    sess = LEARN_SESSIONS.get(key)
    if sess is None:
        # 隐式会话:每日挑战等不经 /learn/next 预热的入口(每题独立计数)
        sess = {"level": q["level"], "seen": [inp.qid], "count": 0, "streak": 0,
                "results": [], "attempts": {}, "daily": True}
        LEARN_SESSIONS[key] = sess
    limit = 3 if sess.get("daily") else MATH_ROUNDS
    learn = store.load_learn(inp.child)
    topic_state = learn.setdefault("topic_state", {}).setdefault(q["topic"], {"tier": "standard"})
    correct = _verify_answer(q, inp.answer)
    attempts = sess["attempts"]
    attempts[inp.qid] = attempts.get(inp.qid, 0) + 1

    out = {"correct": correct, "scaffold": None if correct else q.get("scaffold"),
           "tier_change": None, "xp_gain": 0, "count": sess["count"],
           "total": MATH_ROUNDS, "done": False, "summary": None}

    if correct:
        sess["count"] += 1
        sess["streak"] += 1
        out["count"] = sess["count"]
        gain = 10 + (5 if sess["streak"] >= 3 else 0)
        if sess.get("daily"):
            gain *= 2
        out["xp_gain"] = gain
        learn["xp"] = learn.get("xp", 0) + gain
        learn.setdefault("sessions", []).append(
            {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "level": q["level"], "qid": q["id"],
             "topic": q["topic"], "correct": True, "time_s": round(inp.time_s, 1)})
        # 连对 2 → 升一档
        ts_right = topic_state.get("right_streak", 0) + 1
        topic_state["wrong_streak"] = 0
        if ts_right >= 2 and topic_state.get("tier") != TIERS[-1]:
            old = topic_state["tier"]
            topic_state["tier"] = _tier_shift(old, up=True)
            topic_state["right_streak"] = 0
            out["tier_change"] = {"from": old, "to": topic_state["tier"],
                                  "reason": f"{_topic_name(q['topic'])} 连续答对,难度上调一档"}
            learn.setdefault("adjust_log", []).append(
                {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "child": inp.child,
                 "topic": q["topic"], "from": old, "to": topic_state["tier"], "reason": "连续答对 2 题"})
        else:
            topic_state["right_streak"] = ts_right
        # 关卡完成判定
        if sess["count"] >= limit:
            out["done"] = True
            lv_state = learn.setdefault("levels", {}).setdefault(q["level"], {})
            first_done = not lv_state.get("done")
            lv_state["done"] = True
            lv_state["best"] = max(lv_state.get("best", 0), sess["streak"])
            # R8: 每日挑战完成 +20;关卡首通 +30;重复通关 +5(只增不消耗)
            if sess.get("daily"):
                learn.setdefault("daily_done", {})[time.strftime("%Y-%m-%d")] = True
                out["xp_bonus"] = 20
            else:
                out["xp_bonus"] = 30 if first_done else 5
            learn["xp"] = learn.get("xp", 0) + out["xp_bonus"]
            out["badges"] = _unit_badges(learn)
            out["summary"] = {"streak": sess["streak"], "results": sess["results"][-limit:],
                              "title": _title_for(learn.get("xp", 0))}
        store.save_learn(inp.child, learn)
        return out

    # 答错:第一次给脚手架重试同题;第二次(或累计连错 2)过题并记录
    topic_state["right_streak"] = 0
    wrong_streak = topic_state.get("wrong_streak", 0) + 1
    topic_state["wrong_streak"] = wrong_streak
    learn.setdefault("sessions", []).append(
        {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "level": q["level"], "qid": q["id"],
         "topic": q["topic"], "correct": False, "time_s": round(inp.time_s, 1)})
    tier_change = None
    if wrong_streak >= 2 and topic_state.get("tier") != TIERS[0]:
        old = topic_state["tier"]
        topic_state["tier"] = _tier_shift(old, up=False)
        topic_state["wrong_streak"] = 0
        out["tier_change"] = {"from": old, "to": topic_state["tier"],
                              "reason": f"{_topic_name(q['topic'])} 连续答错,难度下调一档并插入脚手架"}
        learn.setdefault("adjust_log", []).append(
            {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "child": inp.child,
             "topic": q["topic"], "from": old, "to": topic_state["tier"], "reason": "连续答错 2 题,插入脚手架"})
    if attempts[inp.qid] >= 3:
        # R6:三次都错 → 过题换下一题;R7:沿先修链归因,推荐先修点
        sess["count"] += 1
        sess["streak"] = 0
        sess["results"].append({"qid": q["id"], "correct": False})
        out["count"] = sess["count"]
        out["retry"] = False
        prereq = _prereq_hint(q["topic"])
        if prereq:
            out["prereq"] = prereq
            learn.setdefault("adjust_log", []).append(
                {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "child": inp.child,
                 "topic": q["topic"], "reason": f"建议先复习先修点:{prereq['name']}", "prereq": prereq["id"]})
        if sess["count"] >= limit:
            out["done"] = True
            if sess.get("daily"):
                learn.setdefault("daily_done", {})[time.strftime("%Y-%m-%d")] = True
                out["xp_bonus"] = 20
            learn["xp"] = learn.get("xp", 0) + out.get("xp_bonus", 0)
            out["badges"] = _unit_badges(learn)
            out["summary"] = {"streak": sess["streak"], "results": sess["results"][-limit:]}
        else:
            nq = _pick_question(topic_state["tier"], q["topic"], set(sess["seen"]))
            if nq:
                sess["seen"].append(nq["id"])
                out["next"] = _question_payload(nq, topic_state["tier"])
        store.save_learn(inp.child, learn)
        return out
    if attempts[inp.qid] == 2:
        # R6 第二次错:更具体的中间步提示(仍不给答案),同题再试一次
        out["retry"] = True
        out["step_hint"] = q.get("step_hint") or "把题目里的数字圈出来,一步一步写在草稿纸上,再回头对照上面的提示。"
        store.save_learn(inp.child, learn)
        return out

    out["retry"] = True  # 第一次错:同题再试一次,带着脚手架
    store.save_learn(inp.child, learn)
    return out


@router.get("/learn/daily")
async def learn_daily(child: str = Query(...)):
    """每日挑战:按日期+child 种子选 3 题(可复现,修复 QuizCraft 可无限刷 2x 的缺陷)。
    R5:近期错题优先掺入 1 题——复习曲线优先于纯随机。"""
    today = time.strftime("%Y-%m-%d")
    learn = store.load_learn(child)
    wrong_recent, seen_wrong = [], set()
    for s in reversed(learn.get("sessions", [])):
        if not s.get("correct") and s.get("qid") not in seen_wrong:
            seen_wrong.add(s.get("qid"))
            wrong_recent.append(s["qid"])
        if len(wrong_recent) >= 3:
            break
    rng = random.Random(f"daily-{child}-{today}")
    pool = sorted(_ALL_Q.keys())
    picked = []
    if wrong_recent:
        picked.append(rng.choice(wrong_recent))
    picked += [q for q in rng.sample(pool, 3) if q not in picked][:3 - len(picked)]
    picked = picked[:3]
    return {"date": today, "done": bool(learn.get("daily_done", {}).get(today)),
            "review": bool(wrong_recent) and picked[0] in wrong_recent,
            "questions": [_question_payload(_ALL_Q[qid], _ALL_Q[qid]["tier"]) for qid in picked]}


# ---------------- 家长端(PIN + token) ----------------

class PinIn(BaseModel):
    pin: str


@router.get("/parent/status")
async def parent_status():
    auth = store.parent_auth()
    return {"set": bool(auth.get("pin_hash")), "locked_until": auth.get("locked_until", 0)}


@router.post("/parent/pin/setup")
async def parent_pin_setup(inp: PinIn):
    auth = store.parent_auth()
    if auth.get("pin_hash"):
        raise HTTPException(409, "PIN 已设置,请用验证接口")
    if not re.fullmatch(r"\d{4,6}", inp.pin):
        raise HTTPException(400, "PIN 需为 4~6 位数字")
    auth["pin_hash"] = store.hash_pin(inp.pin, auth["salt"])
    auth["fails"] = 0
    auth["locked_until"] = 0
    store.save_parent_auth(auth)
    return {"ok": True, "token": store.issue_token()}


@router.post("/parent/pin/verify")
async def parent_pin_verify(inp: PinIn):
    auth = store.parent_auth()
    now = time.time()
    if not auth.get("pin_hash"):
        raise HTTPException(409, "PIN 未设置,先走 setup")
    if auth.get("locked_until", 0) > now:
        raise HTTPException(429, f"尝试次数过多,{int((auth['locked_until']-now)//60)+1} 分钟后再试")
    if store.hash_pin(inp.pin, auth.get("salt", "")) != auth["pin_hash"]:
        store.fail_count_bump(auth)
        left = store.MAX_FAILS - auth["fails"]
        raise HTTPException(401, f"PIN 不对,还剩 {left} 次机会")
    auth["fails"] = 0
    store.save_parent_auth(auth)
    return {"ok": True, "token": store.issue_token()}


def _require_parent(token: str):
    if not store.token_ok(token):
        raise HTTPException(401, "家长会话无效或过期")


@router.get("/parent/check")
async def parent_check(token: str = Query("")):
    _require_parent(token)
    return {"ok": True}


@router.get("/parent/overview")
async def parent_overview(token: str = Query("")):
    """控制室总览:每孩子卡片(本周节奏/连续天数/强项待支持/待处理事项)+调整理由 feed。"""
    _require_parent(token)
    cards = []
    for c in PROFILES["children"]:
        learn = store.load_learn(c["id"])
        sessions = learn.get("sessions", [])
        week = [s for s in sessions if _within_days(s.get("ts", ""), 7)]
        minutes = round(sum(s.get("time_s", 0) for s in week) / 60, 1)
        streak = _streak_days({s.get("ts", "")[:10] for s in sessions})
        acc = _topic_accuracy(week)
        strong = [_topic_name(t) for t, (n, a) in acc.items() if n >= 5 and a >= 0.8]
        support = [_topic_name(t) for t, (n, a) in acc.items() if n >= 3 and a < 0.6]
        pending = [f"「{_topic_name(t)}」连续答错,建议陪练" for t, (n, a) in acc.items() if n >= 2 and a < 0.4]
        cards.append({
            "child": c["id"], "name": c["name"], "age": c["age"], "locked": c.get("locked", False),
            "xp": learn.get("xp", 0), "title": _title_for(learn.get("xp", 0)),
            "week_minutes": minutes, "streak_days": streak,
            "week_answers": len(week),
            "activity_7d": _activity_7d(sessions),
            "strong": strong, "support": support, "pending": pending,
            "summary": _descriptive(c["name"], minutes, streak, strong, support),
        })
    feed = sorted(learn_all_adjust(), key=lambda e: e.get("ts", ""), reverse=True)[:10]
    return {"cards": cards, "adjust_feed": feed}


def learn_all_adjust():
    """汇总所有孩子的 adjust_log(家长 feed 用)。"""
    out = []
    for c in PROFILES["children"]:
        for e in store.load_learn(c["id"]).get("adjust_log", []):
            e = dict(e, name=c["name"])
            out.append(e)
    return out


def _within_days(ts: str, days: int) -> bool:
    try:
        t = time.mktime(time.strptime(ts[:10], "%Y-%m-%d"))
        return time.time() - t <= days * 86400 + 43200
    except Exception:
        return False


def _activity_7d(sessions):
    per_day = {}
    for s in sessions:
        d = str(s.get("ts", ""))[:10]
        if d:
            per_day[d] = per_day.get(d, 0) + 1
    out = []
    for i in range(6, -1, -1):
        d = time.strftime("%Y-%m-%d", time.localtime(time.time() - i * 86400))
        out.append({"date": d[5:], "count": per_day.get(d, 0)})
    return out


def _streak_days(days_set):
    streak = 0
    day = time.localtime()
    import datetime
    d = datetime.date(day.tm_year, day.tm_mon, day.tm_mday)
    today_str = d.isoformat()
    if today_str not in days_set:
        d = d.fromordinal(d.toordinal() - 1)  # 昨天有也算连续
    while d.isoformat() in days_set:
        streak += 1
        d = datetime.date.fromordinal(d.toordinal() - 1)
    return streak


def _topic_accuracy(sessions):
    acc = {}
    for s in sessions:
        t = s.get("topic")
        if not t:
            continue
        n, c = acc.get(t, (0, 0))
        acc[t] = (n + 1, c + (1 if s.get("correct") else 0))
    return {t: (n, c / n) for t, (n, c) in acc.items()}


def _descriptive(name, minutes, streak, strong, support):
    """家长端用描述性语言,而非评分标签(PRD §0.3)。"""
    parts = []
    if minutes >= 15:
        parts.append(f"这周学了约 {minutes:g} 分钟")
    elif minutes > 0:
        parts.append(f"这周只学了 {minutes:g} 分钟,节奏还比较松")
    if streak >= 2:
        parts.append(f"已经连续 {streak} 天有登录")
    if strong:
        parts.append("在「" + "」「".join(strong[:2]) + "」上稳住了")
    if support:
        parts.append("「" + "」「".join(support[:2]) + "」可以下周陪练一下")
    if not parts:
        return f"{name}还没有开始学习记录,可以先从第一关逛起。"
    return f"{name}:{';'.join(parts)}。"


@router.get("/parent/preview/{child}")
async def parent_preview(child: str, token: str = Query("")):
    """家长只读预览孩子视图(数据层,不含交互)。"""
    _require_parent(token)
    learn = store.load_learn(child)
    meta = _level_meta()
    done_levels = {k for k, v in learn.get("levels", {}).items() if v.get("done")}
    for u in meta:
        for l in u["levels"]:
            l["done"] = l["id"] in done_levels
    return {"child": child, "xp": learn.get("xp", 0), "title": _title_for(learn.get("xp", 0)),
            "units": meta, "adjust_log": learn.get("adjust_log", [])[-5:]}
