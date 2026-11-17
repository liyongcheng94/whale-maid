"""小鲸灵学园持久层:data/ 下 JSON 文件的读写与默认结构。

文件:
  data/learn_{child}.json   学习档案(xp/levels/topic_state/sessions/adjust_log/daily)
  data/parent_auth.json     家长 PIN(salt+sha256)与失败计数/锁定
所有写入为原子性要求极低的单文件 JSON(家庭局域网单进程),不做锁。
"""

import hashlib
import json
import os
import secrets
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
DATA = PROJECT / "data"


def load_json(path: Path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, data) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def learn_path(child_id: str) -> Path:
    safe = "".join(c for c in child_id if c.isalnum() or c in "-_")
    return DATA / f"learn_{safe}.json"


def default_learn(child_id: str) -> dict:
    return {"child": child_id, "xp": 0, "levels": {}, "topic_state": {},
            "sessions": [], "adjust_log": [], "daily_done": {}, "first_seen": time.strftime("%Y-%m-%d")}


def load_learn(child_id: str) -> dict:
    data = load_json(learn_path(child_id), None)
    if not isinstance(data, dict) or "xp" not in data:
        data = default_learn(child_id)
    return data


def save_learn(child_id: str, data: dict) -> None:
    save_json(learn_path(child_id), data)


def hash_pin(pin: str, salt: str) -> str:
    return hashlib.sha256((salt + ":" + pin).encode()).hexdigest()


def parent_auth() -> dict:
    data = load_json(DATA / "parent_auth.json", None)
    if not isinstance(data, dict) or "pin_hash" not in data:
        return {"set": False, "salt": secrets.token_hex(8), "pin_hash": None,
                "fails": 0, "locked_until": 0}
    data.setdefault("fails", 0)
    data.setdefault("locked_until", 0)
    return data


def save_parent_auth(data: dict) -> None:
    save_json(DATA / "parent_auth.json", data)


LOCK_SECONDS = 900       # 5 次失败锁 15 分钟(civideo 模式)
MAX_FAILS = 5
TOKEN_TTL = 8 * 3600     # 家长会话 token 8 小时
_parent_tokens = {}      # 内存 token -> 过期时间戳(重启即失效,设备分离下重新输一次即可)


def issue_token() -> str:
    tok = secrets.token_hex(16)
    _parent_tokens[tok] = time.time() + TOKEN_TTL
    return tok


def token_ok(tok: str) -> bool:
    exp = _parent_tokens.get(tok or "")
    if not exp or exp < time.time():
        _parent_tokens.pop(tok or "", None)
        return False
    return True


def fail_count_bump(auth: dict) -> dict:
    auth["fails"] = int(auth.get("fails", 0)) + 1
    if auth["fails"] >= MAX_FAILS:
        auth["locked_until"] = time.time() + LOCK_SECONDS
        auth["fails"] = 0
    save_parent_auth(auth)
    return auth


def os_env_city_default():  # 占位:learn 路由不依赖,保持模块独立
    return os.environ.get("WHALE_CITY", "上海")
