# -*- coding: utf-8 -*-
"""模拟服务端 difflib 歌名匹配,验证「歌手-歌名」文件名方案。"""
import difflib
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CURRENT = ["生日快乐歌", "哈基米曼波", "孤勇者", "挖呀挖", "稻香", "晴天",
           "知我（抒情版）", "知我（抒情版）2", "听妈妈的话", "孤勇者思凤版"]
PROPOSED = ["生日快乐歌", "哈基米曼波", "祖娅纳惜-孤勇者", "挖呀挖", "周杰伦-稻香",
            "周杰伦-晴天", "知我（抒情版）", "知我（抒情版）2", "周杰伦-听妈妈的话", "思凤-孤勇者"]


def find_best(potential, names):
    best, highest = None, 0
    for n in names:
        r = difflib.SequenceMatcher(None, potential, n).ratio()
        if r > highest and r > 0.4:
            highest, best = r, n
    return best, round(highest, 2)


for query in ["周杰伦", "周杰伦的歌", "晴天", "孤勇者", "哈基米", "唱首歌", "生日快乐", "知我", "稻香", "听妈妈的话"]:
    a = find_best(query, CURRENT)
    b = find_best(query, PROPOSED)
    print(f"「{query}」  现状→ {a[0] or '随机兜底'}({a[1]})   方案→ {b[0] or '随机兜底'}({b[1]})")
