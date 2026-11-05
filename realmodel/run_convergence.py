#!/usr/bin/env python3
"""Convergence benchmark: does a model call submit_review within --max-turns?

Scenes (same as the README's model-selection table):
  A  this repository's own workflow diff 94210ee..73d2f35 (--no-sandbox): a config-only
     diff with no code to run, the kind that makes reasoning models loop forever.
  B  fixtures/make_repo.sh's five planted bugs (srt sandbox, --context, --apply); the
     applied patch is verified on the host by realmodel/oracle.py.

Usage:
  python3 realmodel/run_convergence.py --models 'deepseek/deepseek-flash=AB' 'auto/glm-5.3=A'
  python3 realmodel/run_convergence.py --list            # the runs behind the README table

Each cell runs once (n=1). Results land in realmodel/results-convergence/runs/,
never over the committed baselines. Needs the magpie gateway on 127.0.0.1:3425.
"""
import argparse, json, os, shutil, subprocess, sys, tempfile, threading, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # the repository
OUTROOT = ROOT / "realmodel" / "results-convergence"
ORACLE = ROOT / "realmodel" / "oracle.py"
MAKE_REPO = ROOT / "fixtures" / "make_repo.sh"
REVIEW = ROOT / "review.py"
SCENE_A_BASE, SCENE_A_HEAD = "94210ee", "73d2f35"       # the PR diff the README table used
GW = "http://127.0.0.1:3425/v1"

BASELINE = {  # what realmodel/results-convergence/summary.json and retest-nudge.json hold
    "summary.json": "18-model benchmark, before the wrap-up nudge (2026-11-05)",
    "retest-nudge.json": "non-converging models rerun with the wrap-up nudge (2026-11-06)",
}


def run_scene(tag, model, scene, repo_cache, a_turns):
    work = Path(tempfile.mkdtemp(prefix=f"conv-{tag}-"))
    env = dict(os.environ, LLM_BASE_URL=GW, LLM_API_KEY="magpie")
    rep = work / "report.json"
    if scene == "A":
        repo = work / "repo"
        if not repo_cache.exists():                     # one clean clone of the pinned commits
            subprocess.run(["git", "clone", "-q", str(ROOT), str(repo_cache)], check=True)
            subprocess.run(["git", "-C", str(repo_cache), "checkout", "-q", SCENE_A_HEAD], check=True)
        shutil.copytree(repo_cache, repo)
        cmd = ["python3", "-I", str(REVIEW), "--no-sandbox", "--model", model,
               "--max-turns", str(a_turns), "--base", SCENE_A_BASE, "--head", SCENE_A_HEAD,
               "--output", str(rep)]
        cwd = repo
    else:
        repo = work / "repo"
        subprocess.run(["sh", str(MAKE_REPO), str(repo)], check=True, capture_output=True)
        cmd = ["python3", "-I", str(REVIEW), "--model", model, "--max-turns", str(a_turns),
               "--context", "tests/test_orders.py", "--apply", "--output", str(rep)]
        cwd = repo
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=1000)
        rc, log = p.returncode, (p.stdout or "") + "\n" + (p.stderr or "")
    except subprocess.TimeoutExpired:
        rc, log = 124, "TIMEOUT after 1000s"
    secs = round(time.time() - t0, 1)
    info = {"model": model, "scene": scene, "exit": rc, "seconds": secs, "converged": False,
            "turns": 0, "submit_review_calls": 0, "tool_calls": {}, "findings": None,
            "confirmed": 0, "patches": 0, "tokens": 0, "error": None,
            "nudge_fired": False, "verdict": None}
    if rep.exists():
        d = json.loads(rep.read_text())
        info["tokens"], info["error"] = d.get("tokens", 0), d.get("error")
        tc, submits, turns = {}, 0, 0
        for m in d.get("messages") or []:
            if m.get("role") == "assistant":
                turns += 1
            if m.get("role") == "user" and "turns left" in str(m.get("content", "")):
                info["nudge_fired"] = True
            for c in m.get("tool_calls") or []:
                n = (c.get("function") or {}).get("name") or "?"
                tc[n] = tc.get(n, 0) + 1
                submits += n == "submit_review"
        info.update(turns=turns, tool_calls=tc, submit_review_calls=submits)
        if d.get("findings") is not None:
            fs = d["findings"]
            info.update(converged=True, findings=len(fs),
                        confirmed=sum(1 for f in fs if f.get("confirmed")),
                        patches=len(d.get("patches") or []),
                        verdict="empty" if not fs else f"{len(fs)} findings ({info['confirmed']} confirmed)")
            if scene == "B":
                try:
                    op = subprocess.run(["python3", str(ORACLE)], cwd=repo, capture_output=True, text=True)
                    orc = json.loads(op.stdout.strip())
                    info["oracle"] = f"{sum(1 for v in orc.values() if v)}/{len(orc)}"
                except Exception as e:
                    info["oracle"] = f"err:{str(e)[:60]}"
    else:
        info["error"] = (log.strip().splitlines()[-1] if log.strip() else f"exit {rc}, no report")[:200]
    shutil.rmtree(work, ignore_errors=True)
    return info


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", nargs="*", default=[], metavar="MODEL[=SCENES]",
                    help='e.g. "deepseek/deepseek-flash=AB" "auto/glm-5.3=A" (no = means AB)')
    ap.add_argument("--max-turns", type=int, default=20)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--list", action="store_true", help="show the committed baselines and exit")
    a = ap.parse_args()
    if a.list:
        for f, what in BASELINE.items():
            print(f"{OUTROOT / f}  --  {what}")
        return
    if not a.models:
        ap.error("give --models, or --list")
    jobs = []
    for spec in a.models:
        model, _, scenes = spec.partition("=")
        jobs += [(model, s) for s in (scenes or "AB")]
    outdir = OUTROOT / "runs"
    outdir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    summary, lock, done = {}, threading.Lock(), [0]
    repo_cache = Path(tempfile.mkdtemp(prefix="conv-repoA-")) / "repo_a"

    def worker(model, scene):
        tag = model.split("/")[-1]
        try:
            r = run_scene(tag, model, scene, repo_cache, a.max_turns)
        except Exception as e:
            r = {"model": model, "scene": scene, "error": str(e)[:200], "converged": False}
        with lock:
            summary.setdefault(model, {})[scene] = r
            (outdir / f"run-{stamp}.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
            done[0] += 1
            v = r.get("verdict")
            print(f"[{done[0]}/{len(jobs)}] {model} {scene}: conv={r.get('converged')} exit={r.get('exit')} "
                  f"turns={r.get('turns')} nudge={r.get('nudge_fired')} "
                  f"verdict={v if v else str(r.get('error', ''))[:80]}"
                  + (f" oracle={r.get('oracle')}" if scene == 'B' else ""), flush=True)

    threads = [threading.Thread(target=worker, args=j) for j in jobs]
    for i in range(0, len(threads), a.workers):          # throttle: a.workers at a time
        chunk = threads[i:i + a.workers]
        for t in chunk:
            t.start()
        for t in chunk:
            t.join()


if __name__ == "__main__":
    main()
