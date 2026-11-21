#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""小鲸灵音乐获取工具——以 go-music-dl (guohuiyuan/go-music-dl) 为主音乐来源。

一键搜索/下载/入库/登记歌单。用法：

  # 启动 music-dl web 服务（首次需浏览器访问 /music/setup 初始化管理员）
  music-dl.exe web -p 8099 --no-browser

  # 搜索（跨平台聚合，列出候选并缓存供 --get 引用）
  python scripts/music_fetch.py --search "孤勇者" --sources bilibili,qq

  # 按序号下载入库（自动 ASCII 重命名 + 更新 config/playlist.json）
  python scripts/music_fetch.py --get 1 --group songs

  # 直接按关键词下载第一个命中
  python scripts/music_fetch.py --find "生日快乐歌 儿歌" --group birthday

  # 查看当前歌单
  python scripts/music_fetch.py --list

实测源可用性（2026-11-17）：bilibili 搜索+下载稳定；qq/kugou/kuwo 可搜但
下载音质协商失败；netease/migu/soda 风控 403。默认 sources=bilibili。
"""
import argparse
import json
import os
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MUSIC_DIR = os.path.join(REPO, "assets_audio", "music")
PLAYLIST_PATH = os.path.join(REPO, "config", "playlist.json")
LAST_SEARCH = os.path.join(os.environ.get("TEMP", "/tmp"), "wm_last_search.json")
BASE = os.environ.get("MUSIC_DL_URL", "http://127.0.0.1:8099/music")
GROUPS = ("birthday", "hachimi", "songs")
NAME_KEYS = ("id", "source", "name", "artist", "album", "cover", "extra")


def http_json(path, payload=None):
    headers = {"X-Requested-With": "XMLHttpRequest"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode()
    req = urllib.request.Request(BASE + path, data=data, headers=headers)
    return json.loads(urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore"))


def search(keyword, sources="bilibili", min_dur=25, max_dur=420):
    url = "%s/search?q=%s&sources=%s&page=1" % (BASE, urllib.parse.quote(keyword), urllib.parse.quote(sources))
    html = urllib.request.urlopen(url, timeout=60).read().decode("utf-8", "ignore")
    cards = re.findall(r'<li class="song-card"([^>]*)>', html)
    out = []
    for c in cards:
        a = dict(re.findall(r'data-([a-z-]+)="([^"]*)"', c))
        try:
            dur = int(a.get("duration") or 0)
        except ValueError:
            dur = 0
        if not min_dur <= dur <= max_dur:  # 过滤试听片段与超长合集
            continue
        out.append({"id": a.get("id", ""), "source": a.get("source", sources.split(",")[0]),
                    "name": a.get("name", ""), "artist": a.get("artist", ""),
                    "album": a.get("album", ""), "cover": a.get("cover", ""),
                    "extra": a.get("extra", ""), "duration": dur})
    return out


def enqueue(songs):
    body = {"request_id": "wm-%d" % int(time.time() * 1000),
            "songs": [{k: s.get(k, "") for k in NAME_KEYS} | {"embed": False} for s in songs]}
    return http_json("/api/downloads/queue", body)


def wait_record(name_substr, timeout=120):
    """轮询下载记录直到目标曲目 success/failed。"""
    for _ in range(timeout // 4):
        time.sleep(4)
        recs = http_json("/api/downloads/records?page=1").get("records", [])
        for r in recs:
            if name_substr in (r.get("Name") or ""):
                if r.get("Status") in ("success", "failed"):
                    return r
    return None


def slugify(name):
    s = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return (s or "track")[:40]


def next_seq(group, ext=".m4a"):
    n = 0
    if os.path.isdir(MUSIC_DIR):
        for f in os.listdir(MUSIC_DIR):
            m = re.match(r"%s_(\d+)_" % group, f)
            if m:
                n = max(n, int(m.group(1)))
    return n + 1


def import_to_repo(group, song, dl_dir=None):
    """把 music-dl 下载产物复制入库（ASCII 命名），返回 (filename, relpath)。"""
    # R143:默认目录=tools/music-dl/data/downloads(music-dl 工作数据目录,start_musicdl.bat 的 cwd);
    # 旧默认值用 lstrip("./") 剥相对前缀拼出 scripts\AppData\... 坏路径,已废弃。
    dl_dir = dl_dir or os.environ.get(
        "MUSIC_DL_DATA", os.path.join(REPO, "tools", "music-dl", "data", "downloads"))
    seq = next_seq(group)
    fname = "%s_%02d_%s.m4a" % (group, seq, slugify(song["name"]))
    src = None
    for f in os.listdir(dl_dir):
        if song["name"][:12] in f:
            src = os.path.join(dl_dir, f)
            break
    if not src:
        raise FileNotFoundError("下载目录中未找到 %s 的产物" % song["name"])
    dst = os.path.join(MUSIC_DIR, fname)
    os.makedirs(MUSIC_DIR, exist_ok=True)
    shutil.copyfile(src, dst)
    return fname, dst


def register_playlist(group, fname, song):
    pl = json.load(open(PLAYLIST_PATH, encoding="utf-8"))
    g = pl["groups"].setdefault(group, {"keywords": [], "songs": []})
    title = song["name"]
    entry = {"file": fname, "title": title[:40], "alias": [w for w in [song["name"][:12]] if w], "source": song["source"]}
    if song.get("artist"):
        entry["artist"] = song["artist"]
    g["songs"].append(entry)
    json.dump(pl, open(PLAYLIST_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return entry


def fw_sync():
    """固件侧同步:playlist 全部曲目转 mp3(24k mono,xiaozhi 固件口径)拷到目标目录。
    无 ffmpeg 时原样拷贝并警告(固件 play_music 不支持 m4a,须自行转码)。"""
    import subprocess
    pl = json.load(open(PLAYLIST_PATH, encoding="utf-8"))
    dst_root = os.environ.get("WM_FW_MUSIC", "")
    if not dst_root or not os.path.isdir(dst_root):
        sys.exit("请设置目标目录: WM_FW_MUSIC=<xiaozhi-server>/music python scripts/music_fetch.py --fw-sync")
    has_ffmpeg = shutil.which("ffmpeg") is not None
    for g in pl["groups"].values():
        for s in g["songs"]:
            src = os.path.join(MUSIC_DIR, s["file"])
            base = os.path.splitext(s["file"])[0]
            if has_ffmpeg:
                dst = os.path.join(dst_root, base + ".mp3")
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-ar", "24000", "-ac", "1", dst], check=True)
                print("mp3 转码:", base + ".mp3")
            else:
                dst = os.path.join(dst_root, s["file"])
                shutil.copyfile(src, dst)
                print("WARN 无 ffmpeg,原样拷贝(固件不识别 m4a):", s["file"])
    print("固件音乐目录同步完成:", dst_root)


def main():
    ap = argparse.ArgumentParser(description="小鲸灵音乐获取（go-music-dl 主源）")
    ap.add_argument("--search", help="搜索关键词（结果缓存供 --get 引用）")
    ap.add_argument("--sources", default="bilibili")
    ap.add_argument("--get", type=int, help="下载上次搜索结果的第 N 条")
    ap.add_argument("--find", help="直接搜索并下载第一条命中")
    ap.add_argument("--group", default="songs", choices=GROUPS, help="入库分组")
    ap.add_argument("--list", action="store_true", help="查看当前歌单")
    ap.add_argument("--fw-sync", action="store_true", help="歌单转 mp3 同步到固件 music 目录(WM_FW_MUSIC)")
    args = ap.parse_args()

    if args.fw_sync:
        fw_sync()
        return

    if args.list:
        pl = json.load(open(PLAYLIST_PATH, encoding="utf-8"))
        for gname, g in pl["groups"].items():
            print("[%s] keywords=%s" % (gname, ",".join(g.get("keywords", []))))
            for s in g.get("songs", []):
                print("   %s  %s" % (s["file"], s["title"]))
        return

    if args.search:
        res = search(args.search, args.sources)
        json.dump(res, open(LAST_SEARCH, "w", encoding="utf-8"), ensure_ascii=False)
        print("共 %d 条（25s~420s），保存到缓存：" % len(res))
        for i, s in enumerate(res, 1):
            print("  %d. [%s %ss] %s | %s" % (i, s["source"], s["duration"], s["name"][:48], s["artist"][:16]))
        return

    song = None
    if args.get:
        cache = json.load(open(LAST_SEARCH, encoding="utf-8"))
        song = cache[args.get - 1]
    elif args.find:
        song = None
        for attempt in range(3):  # R143:搜索偶发空结果,重试 3 次(在线点歌链路容错)
            res = search(args.find, args.sources)
            if res:
                song = res[0]
                break
            print("搜索无结果,重试 %d/3..." % (attempt + 1))
        if not song:
            sys.exit("没有可用结果")
    else:
        ap.print_help()
        return

    print("下载: %s (%s/%s)" % (song["name"][:48], song["source"], song["id"]))
    print("queue:", enqueue([song]))
    rec = wait_record(song["name"][:12])
    if not rec or rec.get("Status") != "success":
        sys.exit("下载失败: %s" % ((rec or {}).get("Error") or "超时"))
    fname, _ = import_to_repo(args.group, song)
    entry = register_playlist(args.group, fname, song)
    print("入库: %s -> playlist.json[%s]" % (fname, args.group))
    print("登记:", json.dumps(entry, ensure_ascii=False))


if __name__ == "__main__":
    main()
