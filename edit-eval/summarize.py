#!/usr/bin/env python3
"""Summarize results.jsonl: per (endpoint x format x phase) rates + paired table."""
import json, os, sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.abspath(__file__))

def load(path):
    rows = [json.loads(l) for l in open(path) if l.strip()]
    # group attempts into runs
    runs = defaultdict(list)
    for r in rows:
        runs[(r["task"], r["endpoint"], r["format"], r["phase"], r["rep"])].append(r)
    for v in runs.values():
        v.sort(key=lambda r: r["attempt"])
    return rows, runs

def summarize(path):
    rows, runs = load(path)
    groups = defaultdict(list)  # (endpoint, format, phase) -> list of run-attempt-lists
    for k, v in runs.items():
        groups[(k[1], k[2], k[3])].append(v)

    print(f"runs: {len(runs)}  attempts: {len(rows)}\n")
    hdr = f"{'endpoint':14s} {'fmt':4s} {'phase':4s} {'n':>3s} {'first':>6s} {'final':>6s} {'parse_ok':>8s} {'apply_ok':>8s} {'scope':>6s} {'in_tok':>7s} {'out_tok':>7s} {'lat_s':>6s}  failures"
    print(hdr)
    print("-" * len(hdr))
    for (ep, fmt, phase), cells in sorted(groups.items()):
        n = len(cells)
        first_pass = sum(1 for c in cells if c[0]["tests_pass"])
        final_pass = sum(1 for c in cells if c[-1]["tests_pass"])
        att0 = [c[0] for c in cells]
        parse_ok = sum(1 for r in att0 if r["parse_ok"])
        apply_ok = sum(1 for r in att0 if r["apply_ok"])
        scope_ok = sum(1 for r in att0 if r["scope_ok"])
        in_tok = sum(r["in_tok"] for c in cells for r in c) / max(n, 1)
        out_tok = sum(r["out_tok"] for c in cells for r in c) / max(n, 1)
        lat = sum(r["latency_ms"] for c in cells for r in c) / max(n, 1) / 1000
        fails = Counter(r["failure_stage"] for c in cells for r in c if not r["tests_pass"] and r["failure_stage"])
        fs = ", ".join(f"{k}x{v}" for k, v in fails.most_common())
        print(f"{ep:14s} {fmt:4s} {phase:4s} {n:3d} {first_pass/n:6.0%} {final_pass/n:6.0%} "
              f"{parse_ok/n:8.0%} {apply_ok/n:8.0%} {scope_ok/n:6.0%} {in_tok:7.0f} {out_tok:7.0f} {lat:6.1f}  {fs}")

    # paired per task x rep x endpoint x phase
    print("\n== paired (same task, same rep): final result ==")
    pairs = defaultdict(Counter)
    for (task, ep, fmt, phase, rep), cells in runs.items():
        pairs[(ep, phase)][(task, rep, fmt)] = cells[-1]["tests_pass"]
    for (ep, phase), m in sorted(pairs.items()):
        both = only_v = only_s = neither = 0
        by_key = defaultdict(dict)
        for (task, rep, fmt), passed in m.items():
            by_key[(task, rep)][fmt] = passed
        for k, v in by_key.items():
            a, b = v.get("v4a"), v.get("sr")
            if a and b: both += 1
            elif a: only_v += 1
            elif b: only_s += 1
            else: neither += 1
        print(f"{ep:14s} {phase:4s}  both={both}  only_v4a={only_v}  only_sr={only_s}  neither={neither}")

if __name__ == "__main__":
    summarize(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "results", "results.jsonl"))
