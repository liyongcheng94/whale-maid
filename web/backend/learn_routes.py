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
PROFILES_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "profiles.json"
PROFILES = json.loads(PROFILES_PATH.read_text(encoding="utf-8"))

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
    # R18 每关错题计数 + 单元完成度
    wrong_by_level = {}
    for s in learn.get("sessions", []):
        if not s.get("correct"):
            wrong_by_level[s.get("level")] = wrong_by_level.get(s.get("level"), 0) + 1
    for u in meta:
        for l in u["levels"]:
            st = learn.get("levels", {}).get(l["id"], {})
            l["best"] = st.get("best")
            l["done"] = bool(st.get("done"))
            l["wrong"] = wrong_by_level.get(l["id"], 0)
        done_levels = [l for l in u["levels"] if l["done"]]
        u["done_n"] = len(done_levels)
        u["total_n"] = len(u["levels"])
    # R25 解锁链(结构性):首个可玩单元直接解锁,后续单元需前一可玩单元全部通关
    prev_done = True
    for u in meta:
        if u["planned"]:
            u["unlocked"] = False
            continue
        u["unlocked"] = prev_done
        prev_done = u["total_n"] > 0 and u["done_n"] == u["total_n"]
    return {"child": child, "units": meta, "xp": learn.get("xp", 0),
            "title": _title_for(learn.get("xp", 0)), "badges": _unit_badges(learn),
            "first_seen": learn.get("first_seen")}


UNIT_BADGES = {"u1": "四则运算骑士", "u3": "运算律学徒", "u4": "小数探索家"}
MILESTONE_BADGES = {"streak7": "七日不辍", "wrongbook_clear": "错题清零大师", "answers100": "百题斩"}


def _milestone_badges(learn: dict):
    """R49-R51 里程碑徽章:连续 7 天/错题清零/累计百题(只增不消耗)。"""
    badges = learn.setdefault("badges", [])
    streak = _streak_days({s.get("ts", "")[:10] for s in learn.get("sessions", [])})
    if streak >= 7 and MILESTONE_BADGES["streak7"] not in badges:
        badges.append(MILESTONE_BADGES["streak7"])
    if len(learn.get("sessions", [])) >= 100 and MILESTONE_BADGES["answers100"] not in badges:
        badges.append(MILESTONE_BADGES["answers100"])
    return badges


def _wrongbook_qids(learn: dict):
    """历史做错的题(去重,按最后状态)。"""
    state = {}
    for s in learn.get("sessions", []):
        qid = s.get("qid")
        if qid:
            state[qid] = bool(s.get("correct"))
    return [qid for qid, ok in state.items() if not ok]


def _check_wrongbook_clear(learn: dict):
    """R50:曾经有错题、现在全做过对 → 错题清零大师。"""
    if _wrongbook_qids(learn):
        return
    badges = learn.setdefault("badges", [])
    if len(learn.get("sessions", [])) >= 10 and MILESTONE_BADGES["wrongbook_clear"] not in badges:
        badges.append(MILESTONE_BADGES["wrongbook_clear"])


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
async def learn_next(child: str = Query(...), level: str = Query(...), session: str = Query(...),
                     force_qid: str = Query(None)):
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
    # R30 错题本重做:force_qid 指定具体题目(错题本入口)
    if force_qid and force_qid in _ALL_Q and _ALL_Q[force_qid]["level"] == level:
        q = _ALL_Q[force_qid]
        if q["id"] not in seen:
            sess["seen"].append(q["id"])
    else:
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
        learn["skill_mastery"] = {t: {"tier": st.get("tier"), "right": st.get("right_streak", 0),
                                      "wrong": st.get("wrong_streak", 0)}
                                  for t, st in learn.get("topic_state", {}).items()}
        # 连对 2 → 升一档
        ts_right = topic_state.get("right_streak", 0) + 1
        topic_state["wrong_streak"] = 0
        if ts_right >= 3 and topic_state.get("tier") != TIERS[-1]:
            # R26 快速学习者通道:升档不清零连对计数,累计 3 次连对跳两档
            old = topic_state["tier"]
            topic_state["tier"] = _tier_shift(_tier_shift(old, up=True), up=True)
            topic_state["right_streak"] = 0
            out["tier_change"] = {"from": old, "to": topic_state["tier"],
                                  "reason": f"{_topic_name(q['topic'])} 连续答对 3 题,跳级加速"}
            learn.setdefault("adjust_log", []).append(
                {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "child": inp.child,
                 "topic": q["topic"], "from": old, "to": topic_state["tier"], "reason": "连续答对 3 题,跳级"})
        elif ts_right >= 2 and topic_state.get("tier") != TIERS[-1]:
            old = topic_state["tier"]
            topic_state["tier"] = _tier_shift(old, up=True)
            topic_state["right_streak"] = ts_right  # R26: 升档不清零,累计到 3 跳两档
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
        _check_wrongbook_clear(learn)
        _milestone_badges(learn)
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
    rng = random.Random(f"daily-{child}-{today}-xp{learn.get('xp', 0)}")
    pool = sorted(_ALL_Q.keys())
    picked = []
    if wrong_recent:
        picked.append(rng.choice(wrong_recent))
    picked += [q for q in rng.sample(pool, 4) if q not in picked][:4 - len(picked)]
    picked = picked[:4]  # R34: 3→4 题(1 错题复习 + 3 新题)
    return {"date": today, "done": bool(learn.get("daily_done", {}).get(today)),
            "review": bool(wrong_recent) and picked[0] in wrong_recent,
            "questions": [_question_payload(_ALL_Q[qid], _ALL_Q[qid]["tier"]) for qid in picked]}


# ---------------- 家长端(PIN + token) ----------------

class PinIn(BaseModel):
    pin: str


class CurrentIn(BaseModel):
    child: str
    level: str


@router.post("/learn/current")
async def learn_current(inp: CurrentIn):
    """R40 孩子端当前任务上报:副屏与家长总览消费(只存 level 与时间戳,不存内容)。"""
    learn = store.load_learn(inp.child)
    lv = next((l for u in CURRICULUM["units"] for l in u.get("levels", []) if l["id"] == inp.level), None)
    learn["current"] = {"level": inp.level,
                        "name": lv["name"] if lv else inp.level,
                        "unit": next((u["name"] for u in CURRICULUM["units"] if u["id"] == inp.level.split("-")[0]), ""),
                        "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
    store.save_learn(inp.child, learn)
    return {"ok": True}


@router.get("/learn/achievements")
async def achievements(child: str = Query(...)):
    """R48 成就墙:单元徽章+里程碑徽章+连续天数+累计题数+每日连击。"""
    learn = store.load_learn(child)
    streak = _streak_days({s.get("ts", "")[:10] for s in learn.get("sessions", [])})
    # R53 每日连击:连续完成每日挑战的天数
    daily_streak = 0
    import datetime
    d = datetime.date.today()
    while learn.get("daily_done", {}).get(d.isoformat()):
        daily_streak += 1
        d = datetime.date.fromordinal(d.toordinal() - 1)
    wrong_left = len(_wrongbook_qids(learn))
    return {"child": child, "badges": learn.get("badges", []),
            "streak_days": streak, "daily_streak": daily_streak,
            "total_answers": len(learn.get("sessions", [])),
            "wrong_left": wrong_left}


@router.get("/learn/tree")
async def learn_tree(child: str = Query(...)):
    """R46 技能树:四下知识图谱节点 → 孩子的掌握状态(探索中/已掌握/未解锁)。
    掌握判定:该话题近 7 天 ≥5 题且正确率 ≥80% → mastered;有过作答 → learning;否则 locked。"""
    learn = store.load_learn(child)
    acc = _topic_accuracy([s for s in learn.get("sessions", []) if _within_days(s.get("ts", ""), 7)])
    all_time = _topic_accuracy(learn.get("sessions", []))
    skills = []
    for t in KG["topics"]:
        if t.get("grade", 0) > 4:
            continue  # 只呈现小学阶段(≤4 年级)节点
        n7, a7 = acc.get(t["id"], (0, 0))
        nall, aall = all_time.get(t["id"], (0, 0))
        tier = learn.get("topic_state", {}).get(t["id"], {}).get("tier")
        if n7 >= 5 and a7 >= 0.8:
            status = "mastered"
        elif nall > 0:
            status = "learning"
        else:
            status = "locked"
        skills.append({"id": t["id"], "name": t["name"], "chapter": t.get("chapter", ""),
                       "domain": t.get("domain", ""), "grade": t.get("grade"),
                       "status": status, "tier": tier,
                       "week_count": n7, "week_accuracy": round(a7, 2) if n7 else None})
    order = {"mastered": 0, "learning": 1, "locked": 2}
    skills.sort(key=lambda s: (order[s["status"]], s["id"]))
    return {"child": child, "skills": skills,
            "mastered_count": sum(1 for s in skills if s["status"] == "mastered")}


WORDS = json.loads((CURRICULUM_DIR.parent / "words.json").read_text(encoding="utf-8"))["words"]


@router.get("/learn/words/daily")
async def words_daily(child: str = Query(...)):
    """R61 英语角:按日期+child 种子选 3 词(可复现);音频三件套 word_{w}_en/zh/sent 预生成。"""
    today = time.strftime("%Y-%m-%d")
    rng = random.Random(f"words-{child}-{today}")
    picked = rng.sample(WORDS, 3)
    return {"date": today, "words": picked}


@router.get("/learn/wrongbook")
async def wrongbook(child: str = Query(...)):
    """R29 错题本:近期做错的题去重列表(按最后错误时间倒序,最多 20 题)。"""
    learn = store.load_learn(child)
    wrongs, seen = [], set()
    for s in reversed(learn.get("sessions", [])):
        qid = s.get("qid")
        if s.get("correct") is False and qid not in seen and qid in _ALL_Q:
            seen.add(qid)
            q = _ALL_Q[qid]
            wrongs.append({"qid": qid, "prompt": q["prompt"], "tier": q["tier"], "level": q["level"],
                           "scaffold": q.get("scaffold"), "ts": s.get("ts", "")[:10]})
        if len(wrongs) >= 20:
            break
    return {"child": child, "items": list(reversed(wrongs))}


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


class PrereqIn(BaseModel):
    child: str
    prereq_id: str
    answer: str


@router.post("/learn/prereq-answer")
async def prereq_answer(inp: PrereqIn):
    """R27 先修诊断闭环:孩子回答先修点的诊断问题 → 判答 → 引导语(不直接给答案)。"""
    node = next((t for t in KG["topics"] if t["id"] == inp.prereq_id), None)
    if not node:
        raise HTTPException(404, "unknown prereq")
    dq = node.get("diagnostic_question", {})
    correct = str(inp.answer).strip() == str(dq.get("answer", "")).strip() or         str(dq.get("answer", "")).strip() in str(inp.answer).strip()
    learn = store.load_learn(inp.child)
    if correct:
        learn.setdefault("xp", 0)
        learn["xp"] += 5
        store.save_learn(inp.child, learn)
    msg = ("先修点通过!回去看,那道题现在有思路了吗?" if correct
           else "还差一点——把「" + node["name"] + "」的课本例子再看一遍,回来再试。")
    return {"correct": correct, "message": msg, "prereq": inp.prereq_id}


def _require_parent(token: str):
    if not store.token_ok(token):
        raise HTTPException(401, "家长会话无效或过期")


@router.get("/parent/playlist")
async def parent_playlist(token: str = Query("")):
    """R36 伴听:曲库列表下发到家长设备(音频在家长设备浏览器出声,与孩子端会话互不抢占)。"""
    _require_parent(token)
    songs = []
    for gname, s in _all_songs():
        songs.append({"group": gname, "file": s["file"], "title": s["title"],
                      "cover": _cover_for(s["file"])})
    return {"songs": songs}


@router.get("/parent/sub")
async def parent_sub(child: str = Query(...), token: str = Query("")):
    """R38/R39 副屏摘要:只读、低密度——在做什么/今天做了多少/正确率/是否需要介入。"""
    _require_parent(token)
    learn = store.load_learn(child)
    prof = next((c for c in PROFILES["children"] if c["id"] == child), {})
    today = time.strftime("%Y-%m-%d")
    todays = [s for s in learn.get("sessions", []) if str(s.get("ts", "")).startswith(today)]
    acc = _topic_accuracy(todays)
    cur = learn.get("current", {})
    need_help = any(v >= 2 for v in [0])  # 占位:由连错会话判定
    help_flag = sum(1 for s in todays[-3:] if not s.get("correct")) >= 3
    streak = _streak_days({s.get("ts", "")[:10] for s in learn.get("sessions", [])})
    return {"child": child, "name": prof.get("name", child), "streak_days": streak,
            "current": cur, "today_answers": len(todays),
            "today_accuracy": (round(sum(1 for s in todays if s.get("correct")) / len(todays), 2) if todays else None),
            "need_help": help_flag,
            "xp": learn.get("xp", 0), "title": _title_for(learn.get("xp", 0)),
            "badges": learn.get("badges", []),
            "current_progress": learn.get("levels", {}).get((cur or {}).get("level", ""), {})}


@router.get("/parent/check")
async def parent_check(token: str = Query("")):
    _require_parent(token)
    return {"ok": True}


@router.get("/parent/report")
async def parent_report(child: str = Query(...), token: str = Query(""), days: int = Query(7)):
    """R41 学习报告 JSON 导出(家长下载留档):概要+逐题记录+调整理由。"""
    _require_parent(token)
    learn = store.load_learn(child)
    prof = next((c for c in PROFILES["children"] if c["id"] == child), {})
    sessions = [s for s in learn.get("sessions", []) if _within_days(s.get("ts", ""), days)]
    acc = _topic_accuracy(sessions)
    report = {
        "child": child, "name": prof.get("name", child), "days": days,
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "xp": learn.get("xp", 0), "title": _title_for(learn.get("xp", 0)),
        "badges": learn.get("badges", []),
        "streak_days": _streak_days({s.get("ts", "")[:10] for s in sessions}),
        "minutes": round(sum(s.get("time_s", 0) for s in sessions) / 60, 1),
        "answers": len(sessions),
        "accuracy": round(sum(1 for s in sessions if s.get("correct")) / len(sessions), 2) if sessions else None,
        "by_topic": {_topic_name(t): {"count": n, "accuracy": round(a, 2)} for t, (n, a) in acc.items()},
        "adjust_log": learn.get("adjust_log", [])[-20:],
        "by_week": _by_week(sessions),
        "records": sessions[-200:],
        "schema": 2,
    }
    return JSONResponse(report, headers={"Content-Disposition": f"attachment; filename=report_{child}_{days}d.json"})


class RenameIn(BaseModel):
    child_id: str
    name: str


@router.put("/parent/profile")
async def rename_profile(inp: RenameIn, token: str = Query("")):
    """R44 家长重命名孩子档案(档案文件为入库配置,改名后随提交固化)。"""
    _require_parent(token)
    name = inp.name.strip()[:12]
    if not 1 <= len(name):
        raise HTTPException(400, "名字不能为空")
    prof_path = PROFILES_PATH
    prof = json.loads(prof_path.read_text(encoding="utf-8"))
    target = next((c for c in prof["children"] if c["id"] == inp.child_id), None)
    if not target:
        raise HTTPException(404, "unknown child")
    target["name"] = name
    prof_path.write_text(json.dumps(prof, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "name": name}


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
        # R16 上周分钟数(8~14 天前),供周对比
        prev = [s for s in sessions if 7 < _days_ago(s.get("ts", "")) <= 14]
        prev_minutes = round(sum(s.get("time_s", 0) for s in prev) / 60, 1)
        # R17 最近一次学习距今天数
        last_days = min((_days_ago(s.get("ts", "")) for s in sessions), default=999)
        streak = _streak_days({s.get("ts", "")[:10] for s in sessions})
        acc = _topic_accuracy(week)
        strong = [_topic_name(t) for t, (n, a) in acc.items() if n >= 5 and a >= 0.8]
        support = [_topic_name(t) for t, (n, a) in acc.items() if n >= 3 and a < 0.6]
        pending = [f"「{_topic_name(t)}」连续答错,建议陪练" for t, (n, a) in acc.items() if n >= 2 and a < 0.4]
        # R17 未学提醒:最近一次学习超过 2 天 → 温和提醒家长发起陪伴
        if last_days >= 2:
            pending.insert(0, f"最近 {last_days} 天没有学习记录,要不要陪{c.get('name', '孩子')}开一关?")
        cards.append({
            "child": c["id"], "name": c["name"], "age": c["age"], "locked": c.get("locked", False),
            "xp": learn.get("xp", 0), "title": _title_for(learn.get("xp", 0)),
            "week_minutes": minutes, "prev_week_minutes": prev_minutes,
            "week_accuracy": round(sum(1 for s in week if s.get("correct")) / len(week), 2) if week else None,
            "last_days_ago": last_days if last_days < 999 else None,
            "streak_days": streak, "week_answers": len(week),
            "activity_7d": _activity_7d(sessions),
            "strong": strong, "support": support, "pending": pending,
            "summary": _descriptive(c["name"], minutes, prev_minutes, streak, strong, support, pending),
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


def _by_week(sessions):
    """R70 报告 v2:按 ISO 周聚合作答数与正确率。"""
    import datetime
    out = {}
    for s in sessions:
        try:
            d = datetime.date.fromisoformat(str(s.get("ts", ""))[:10])
            key = f"{d.isocalendar().year}-W{d.isocalendar().week:02d}"
        except Exception:
            continue
        n, c = out.get(key, (0, 0))
        out[key] = (n + 1, c + (1 if s.get("correct") else 0))
    return {k: {"count": n, "accuracy": round(c / n, 2)} for k, (n, c) in sorted(out.items())}


def _topic_accuracy(sessions):
    acc = {}
    for s in sessions:
        t = s.get("topic")
        if not t:
            continue
        n, c = acc.get(t, (0, 0))
        acc[t] = (n + 1, c + (1 if s.get("correct") else 0))
    return {t: (n, c / n) for t, (n, c) in acc.items()}


def _days_ago(ts: str):
    try:
        t = time.mktime(time.strptime(ts[:10], "%Y-%m-%d"))
        return max(0, int((time.time() - t) // 86400))
    except Exception:
        return 999


def _descriptive(name, minutes, prev_minutes, streak, strong, support, pending):
    """家长端用描述性语言,而非评分标签(PRD §0.3)。R16 周对比 / R17 未学提醒。"""
    parts = []
    if prev_minutes > 0 and minutes > 0:
        delta = minutes - prev_minutes
        arrow = "比上周多" if delta >= 0 else "比上周少"
        parts.append(f"这周学了约 {minutes:g} 分钟,{arrow} {abs(delta):g} 分钟")
    elif minutes >= 15:
        parts.append(f"这周学了约 {minutes:g} 分钟")
    elif minutes > 0:
        parts.append(f"这周只学了 {minutes:g} 分钟,节奏还比较松")
    if streak >= 2:
        parts.append(f"已经连续 {streak} 天有登录")
    if strong:
        parts.append("在「" + "」「".join(strong[:2]) + "」上稳住了")
    if support:
        parts.append("「" + "」「".join(support[:2]) + "」可以下周陪练一下")
    if pending:
        parts.append("有一两个知识点需要陪练")
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
