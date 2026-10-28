#!/usr/bin/env python3
"""指标汇总：分层准确率 / 引用真实率 / 压缩比与保真度 / 规模斜率外推。

用法：
  python3 metrics.py --score armA=results/armA.score.json --score armB=results/armB.score.json \
                     --scale runs.jsonl --compression comp.json --out reports/feasibility.json
runs.jsonl 每行：{"mb":5,"seconds":3600,"tokens_out":120000,"chunks":40}
comp.json：{"orig_tokens":8500000,"summary_tokens":700000,"retained":41,"total":50}
"""
import argparse
import json
import math
import os


def load_scores(pairs):
    out = {}
    for p in pairs:
        name, path = p.split("=", 1)
        try:
            out[name] = json.load(open(path, encoding="utf-8"))
        except OSError:
            out[name] = None
    return out


def lin_fit(xs, ys):
    n = len(xs)
    if n < 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    b = sxy / sxx if sxx else 0
    a = my - b * mx
    syy = sum((y - my) ** 2 for y in ys)
    r2 = (sxy ** 2 / (sxx * syy)) if (sxx and syy) else 0.0
    return {"slope": b, "intercept": a, "r2": round(r2, 3)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--score", action="append", default=[])
    ap.add_argument("--scale", default="")
    ap.add_argument("--compression", default="")
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    rep = {"scores": load_scores(a.score)}

    # 1) 裸答 vs 工具图增益
    acc = {k: (v or {}).get("accuracy", {}) for k, v in rep["scores"].items()}
    rep["accuracy_by_arm"] = acc
    if "armA" in acc and "armB" in acc:
        gain = {}
        for tier in acc["armA"]:
            if tier in acc["armB"]:
                gain[tier] = round((acc["armB"][tier] - acc["armA"][tier]) * 100, 1)
        rep["tool_gain_pp"] = gain

    # 2) 压缩比与保真度
    if a.compression and os.path.exists(a.compression):
        c = json.load(open(a.compression, encoding="utf-8"))
        ratio = c["orig_tokens"] / max(1, c["summary_tokens"])
        rep["compression"] = {"ratio": round(ratio, 2),
                              "retention": round(c["retained"] / max(1, c["total"]), 3)}

    # 3) 规模斜率与外推
    if a.scale and os.path.exists(a.scale):
        rows = [json.loads(l) for l in open(a.scale, encoding="utf-8") if l.strip()]
        xs = [r["mb"] for r in rows]
        for key in ("seconds", "tokens_out"):
            fit = lin_fit(xs, [r.get(key, 0) for r in rows])
            if fit:
                rep.setdefault("scale_fit", {})[key] = fit
        if "scale_fit" in rep and "seconds" in rep["scale_fit"]:
            f = rep["scale_fit"]["seconds"]
            rep["extrapolate_200mb_hours"] = round((f["intercept"] + f["slope"] * 200) / 3600, 1)

    txt = json.dumps(rep, ensure_ascii=False, indent=2)
    print(txt)
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        open(a.out, "w", encoding="utf-8").write(txt)


if __name__ == "__main__":
    main()
