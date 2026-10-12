#!/usr/bin/env python3
"""产品雷达评分/校验/合并工具（仅标准库）。

用法:
  score.py validate FILE.json
  score.py rank FILE.json
  score.py merge BASE.json NEW.json -o OUT.json
"""
import argparse, json, math, re, sys, time

DIMS = [("demand", 18), ("trend", 13), ("pay", 18), ("gap", 13), ("acq", 13), ("dev", 10), ("moat", 5), ("fit", 10)]
SIG = {"SEO/需求", "热点/趋势", "新兴产品", "用户痛点", "商业化", "竞争格局"}
VETO = {"依赖单一平台 API 且无替代", "重度合规", "需冷启动双边网络", "消费级低付费且无广告模式"}
STATUS = {"inbox", "watch", "validating", "building", "archived"}
FACT = {"事实", "部分验证", "推测"}
REQ = ["id", "name", "pos", "s", "sig", "veto", "status", "fact"]


def score(o):
    return math.floor(sum(w * o["s"].get(k, 0) / 10 for k, w in DIMS) + 0.5)


def tier(o):
    if o.get("veto"):
        return "veto"
    s = score(o)
    return "go" if s >= 75 else "watch" if s >= 60 else "low"


def load(p):
    with open(p, encoding="utf-8") as f:
        d = json.load(f)
    if not isinstance(d, list):
        sys.exit(f"{p}: 顶层必须是数组")
    return d


def check(o, i):
    e, w = [], []
    tag = f"#{i} {o.get('name', '?')}"
    for k in REQ:
        if k not in o:
            e.append(f"{tag}: 缺少字段 {k}")
    if e:
        return e, w
    for k, _ in DIMS:
        v = o["s"].get(k)
        if not isinstance(v, int) or not 0 <= v <= 10:
            e.append(f"{tag}: s.{k} 必须是 0-10 整数")
    for x in o["sig"]:
        if x not in SIG:
            e.append(f"{tag}: 非法 sig「{x}」")
    for x in o["veto"]:
        if x not in VETO:
            e.append(f"{tag}: 非法 veto「{x}」")
    if o["status"] not in STATUS:
        e.append(f"{tag}: 非法 status「{o['status']}」")
    if o["fact"] not in FACT:
        e.append(f"{tag}: 非法 fact「{o['fact']}」")
    links = [l for l in (o.get("links") or "").splitlines() if l.strip().startswith("http")]
    if o["fact"] in ("事实", "部分验证") and not links:
        e.append(f"{tag}: fact={o['fact']} 但没有证据链接")
    # 闸门
    n = len(set(o["sig"]))
    s = score(o)
    if n < 3 and o["status"] in ("validating", "building"):
        e.append(f"{tag}: 信号类型 {n}<3，不能进入 {o['status']}")
    if n < 3 and s >= 75:
        w.append(f"{tag}: 总分 {s}≥75 但信号类型 {n}<3，须降级并补证据")
    if o["veto"] and o["status"] in ("validating", "building"):
        e.append(f"{tag}: 命中一票否决项，状态最高到 watch")
    for k, _ in DIMS:
        if o["s"].get(k, 0) >= 7 and not links:
            w.append(f"{tag}: {k}≥7 但没有任何证据链接")
    if "【事实】" not in (o.get("notes") or "") and o["fact"] != "推测":
        w.append(f"{tag}: notes 缺少【事实】段落")
    if o["s"].get("fit", 0) >= 7 and "【创始人匹配】" not in (o.get("notes") or ""):
        w.append(f"{tag}: fit≥7 但 notes 缺少【创始人匹配】说明")
    if not o.get("market"):
        w.append(f"{tag}: 缺少 market 字段（市场规模粗估）")
    return e, w


def cmd_validate(a):
    d = load(a.file)
    ids = [o.get("id") for o in d]
    errs, warns = [], []
    for k in {x for x in ids if ids.count(x) > 1}:
        errs.append(f"重复 id: {k}")
    for i, o in enumerate(d, 1):
        e, w = check(o, i)
        errs += e
        warns += w
    for m in warns:
        print("WARN ", m)
    for m in errs:
        print("ERROR", m)
    print(f"\n{len(d)} 条, {len(errs)} 错误, {len(warns)} 警告")
    sys.exit(1 if errs else 0)


def cmd_rank(a):
    d = load(a.file)
    names = {"go": "立即验证", "watch": "观察池", "low": "低分", "veto": "否决"}
    print(f"{'总分':>4}  {'分级':<6} {'信号':<5} {'证据':<6} {'匹配':<4} 名称")
    for o in sorted(d, key=score, reverse=True):
        flag = ""
        if len(set(o["sig"])) < 3:
            flag = "  ⚠信号<3"
        fit = o["s"].get("fit", 0)
        print(f"{score(o):>4}  {names[tier(o)]:<6} {len(set(o['sig']))}/6   {o['fact']:<6} {fit:<4} {o['name']}{flag}")


def norm(s):
    return re.sub(r"\W+", "", s.lower())


def cmd_merge(a):
    base = load(a.base) if __import__("os").path.exists(a.base) else []
    new = load(a.new)
    by_id = {o["id"]: o for o in base}
    by_name = {norm(o["name"]): o for o in base}
    added = updated = 0
    stamp = time.strftime("%Y-%m-%d")
    for n in new:
        old = by_id.get(n["id"]) or by_name.get(norm(n["name"]))
        if old is None:
            base.append(n)
            by_id[n["id"]] = n
            by_name[norm(n["name"])] = n
            added += 1
            continue
        # 更新证据与评分；保留用户已调整的状态；备注追加而非覆盖
        for k in ("s", "sig", "veto", "fact", "market", "pricing", "timing", "acquisition", "wedge", "exp", "links", "pos", "ind", "validation_result", "calibration_note", "last_validated"):
            if k in n:
                old[k] = n[k]
        if n.get("notes") and n["notes"] not in (old.get("notes") or ""):
            old["notes"] = (old.get("notes") or "") + f"\n\n— {stamp} 更新 —\n" + n["notes"]
        old["ts"] = n.get("ts", int(time.time() * 1000))
        updated += 1
    with open(a.o, "w", encoding="utf-8") as f:
        json.dump(base, f, ensure_ascii=False, indent=1)
    print(f"合并完成: 新增 {added}, 更新 {updated}, 共 {len(base)} 条 -> {a.o}")


p = argparse.ArgumentParser()
sp = p.add_subparsers(dest="c", required=True)
for name, fn in (("validate", cmd_validate), ("rank", cmd_rank)):
    q = sp.add_parser(name)
    q.add_argument("file")
    q.set_defaults(f=fn)
q = sp.add_parser("merge")
q.add_argument("base")
q.add_argument("new")
q.add_argument("-o", required=True)
q.set_defaults(f=cmd_merge)
a = p.parse_args()
a.f(a)
