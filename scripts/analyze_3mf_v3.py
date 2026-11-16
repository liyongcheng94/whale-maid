#!/usr/bin/env python3
"""小鲸灵 3MF 解剖 v3 —— 流式正则，修边界重复匹配；按连通分量统计体积。

关键修正：tail 只保留「最后一个 '>' 之后」的字节（不完整元素前缀），
保证任何完整元素只被匹配一次 —— 消除 v2 的重复计数污染。

输出：bbox / 顶点数 / 三角形数 / 总有符号体积 / 分量体积 Top5 /
碎片分量统计 / 顶点几何重复率（判断边界边是否为"复制顶点伪孔"）。
"""
import sys, re, json, time, zipfile
from array import array
from collections import defaultdict

VX_RE = re.compile(rb'<vertex\s+x="([^"]+)"\s+y="([^"]+)"\s+z="([^"]+)"')
TRI_RE = re.compile(rb'<triangle\s+v1="(\d+)"\s+v2="(\d+)"\s+v3="(\d+)"')

def main():
    path = sys.argv[1]
    t0 = time.time()
    z = zipfile.ZipFile(path)
    names = [n for n in z.namelist() if n.endswith('.model')]

    nv = 0; ntri = 0
    mn = [1e30]*3; mx = [-1e30]*3
    V = array('f'); tris = array('i')
    colors = 0

    for name in names:
        with z.open(name) as f:
            tail = b''
            while True:
                chunk = f.read(8 << 20)
                if not chunk:
                    break
                buf = tail + chunk
                colors += buf.count(b'<m:color ')
                # 顶点与三角形：完整元素必然以 '>' 结尾，
                # tail 只含最后一个 '>' 之后的残缺前缀 → 无重复、无遗漏
                for m in VX_RE.finditer(buf):
                    x, y, zz = float(m.group(1)), float(m.group(2)), float(m.group(3))
                    V.append(x); V.append(y); V.append(zz)
                    if x < mn[0]: mn[0] = x
                    if x > mx[0]: mx[0] = x
                    if y < mn[1]: mn[1] = y
                    if y > mx[1]: mx[1] = y
                    if zz < mn[2]: mn[2] = zz
                    if zz > mx[2]: mx[2] = zz
                for m in TRI_RE.finditer(buf):
                    tris.append(int(m.group(1))); tris.append(int(m.group(2))); tris.append(int(m.group(3)))
                cut = buf.rfind(b'>') + 1
                tail = buf[cut:] if cut < len(buf) else b''
    nv = len(V)//3; ntri = len(tris)//3

    # union-find + 每分量有符号体积
    parent = array('i', range(nv))
    comp_vol = defaultdict(float)   # root -> Σdet
    comp_tris = defaultdict(int)
    def find(x):
        r = x
        while parent[r] != r:
            r = parent[r]
        while parent[x] != r:
            parent[x], x = r, parent[x]
        return r
    total6 = 0.0
    for i in range(0, len(tris), 3):
        a, b, c = tris[i], tris[i+1], tris[i+2]
        ax, ay, az = V[3*a], V[3*a+1], V[3*a+2]
        bx, by, bz = V[3*b], V[3*b+1], V[3*b+2]
        cx, cy, cz = V[3*c], V[3*c+1], V[3*c+2]
        det = ax*(by*cz-bz*cy) - ay*(bx*cz-bz*cx) + az*(bx*cy-by*cx)
        total6 += det
        ra, rb, rc = find(a), find(b), find(c)
        # 合并到最小根
        rmin = min(ra, rb, rc)
        for r in (ra, rb, rc):
            if r != rmin: parent[r] = rmin
        root = rmin
        comp_vol[root] += det
        comp_tris[root] += 1

    # 路径压缩后重算根归属（大分量可能被合并到更小的根）
    remap = defaultdict(float); remap_t = defaultdict(int)
    for r, v in comp_vol.items():
        remap[find(r)] += v; remap_t[find(r)] += comp_tris[r]
    comps = sorted(remap.items(), key=lambda kv: -abs(kv[1]))
    ncomp = len(remap)

    # 最大分量的 bbox（主体在哪、占多大范围）
    top_root = comps[0][0] if comps else None
    # 哨兵：min 边初始 +inf，max 边初始 -inf（v3.1 修复：全 +1e30 导致 max 永不更新输出 1e+30）
    tb = [1e30, -1e30, 1e30, -1e30, 1e30, -1e30]
    top_tris = 0
    for i in range(0, len(tris), 3):
        a = tris[i]
        if find(a) == top_root:
            top_tris += 1
            for k, idx in enumerate((a, tris[i+1], tris[i+2])):
                x, y, zz = V[3*idx], V[3*idx+1], V[3*idx+2]
                if x < tb[0]: tb[0] = x
                if x > tb[1]: tb[1] = x
                if y < tb[2]: tb[2] = y
                if y > tb[3]: tb[3] = y
                if zz < tb[4]: tb[4] = zz
                if zz > tb[5]: tb[5] = zz

    # 顶点几何重复率（四舍五入到 0.0001mm 判断"复制顶点伪孔"）
    seen = set(); dup = 0
    step = max(1, nv // 300000)  # 抽样最多 30 万点
    sampled = 0
    for i in range(0, nv, step):
        key = (round(V[3*i], 4), round(V[3*i+1], 4), round(V[3*i+2], 4))
        sampled += 1
        if key in seen: dup += 1
        else: seen.add(key)

    report = {
        "file": path,
        "units": "millimeter",
        "bbox_mm": {"x": round(mx[0]-mn[0], 2), "y": round(mx[1]-mn[1], 2), "z": round(mx[2]-mn[2], 2)},
        "vertices": nv,
        "triangles": ntri,
        "total_signed_volume_cm3": round(abs(total6)/6/1000, 1),
        "winding": "outward" if total6 > 0 else "inward(mixed components likely)",
        "connected_components": ncomp,
        "component_top5_cm3": [
            {"root": r, "signed_cm3": round(v/6/1000, 1), "tris": remap_t[r]}
            for r, v in comps[:5]
        ],
        "debris_components_lt1cm3": sum(1 for _, v in comps if abs(v)/6/1000 < 1.0),
        "main_component": {
            "tris": top_tris,
            "bbox_mm": {"x": round(tb[1]-tb[0], 2), "y": round(tb[3]-tb[2], 2), "z": round(tb[5]-tb[4], 2)},
            "signed_cm3": round(comps[0][1]/6/1000, 1) if comps else 0,
        },
        "vertex_duplicate_ratio_sampled": f"{dup}/{sampled} = {dup/max(1,sampled):.1%}",
        "color_entries": colors,
        "elapsed_s": round(time.time()-t0, 1),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
