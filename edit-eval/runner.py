#!/usr/bin/env python3
"""Paired edit-format evaluator v2: fixed model, variable API protocol.

Axes: api (chat / responses / anthropic) x format (v4a / sr) x phase (text / tool).
Model fixed: kimi-code-cn/k3.1-pro through the magpie gateway, which translates
OpenAI Chat, OpenAI Responses and Anthropic Messages onto the same backend.

Same rules as v1: strict parsers (official apply_diff.py for V4A), scope check,
hidden tests in a sanitized subprocess, at most one retry, per-attempt JSONL.
"""
import argparse, copy, json, os, queue, shutil, subprocess, sys, tempfile, threading, time
import urllib.error, urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from util import run_tests
from executors import v4a, sr

MODEL = "kimi-code-cn/k3.1-pro"   # overridden by --model
BASE = "http://127.0.0.1:3425"    # magpie gateway: OpenAI Chat + OpenAI Responses + Anthropic Messages
CALL_TIMEOUT = 180
MAX_ATTEMPTS = 2

SEM = threading.Semaphore(5)          # one model -> one provider; be gentle
TEMP = {"v": 0}                        # kimi-code-cn accepts only 1; fall back once

FORMATS = {"v4a": v4a, "sr": sr}
PROTOCOL_TEXT = {
    "v4a": open(os.path.join(ROOT, "prompts/v4a.txt")).read(),
    "sr": open(os.path.join(ROOT, "prompts/sr.txt")).read(),
}
COMMON = open(os.path.join(ROOT, "prompts/common.txt")).read()
TOOL_NAME = {"v4a": "apply_patch", "sr": "search_replace"}
TOOL_PARAM = {"v4a": "patch", "sr": "edit"}
PARAMS = {"v4a": {"type": "object", "properties": {"patch": {"type": "string"}}, "required": ["patch"]},
          "sr": {"type": "object", "properties": {"edit": {"type": "string"}}, "required": ["edit"]}}

# ---------------- protocol adapters ----------------

def _http(path, headers, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", **headers})
    with SEM:
        last = None
        for attempt in range(3):
            t0 = time.time()
            try:
                with urllib.request.urlopen(req, timeout=CALL_TIMEOUT) as r:
                    return json.load(r), round((time.time() - t0) * 1000)
            except urllib.error.HTTPError as e:
                last = e
                payload = e.read()
                if e.code == 400 and b"temperature" in payload and TEMP["v"] != 1:
                    TEMP["v"] = 1
                    body["temperature"] = 1
                    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(),
                                                 headers={"Content-Type": "application/json", **headers})
                    continue
                if e.code in (429, 500, 502, 503):
                    time.sleep(3 + attempt * 3)
                    continue
                raise
            except Exception as e:
                last = e
                time.sleep(2)
        raise last

def api_chat(messages, fmt, phase):
    body = {"model": MODEL, "messages": messages, "temperature": TEMP["v"]}
    if phase == "tool":
        body["tools"] = [{"type": "function", "function": {"name": TOOL_NAME[fmt],
                          "description": PROTOCOL_TEXT[fmt], "parameters": PARAMS[fmt]}}]
    res, ms = _http("/v1/chat/completions", {"Authorization": "Bearer magpie"}, body)
    choice = res["choices"][0]
    msg = choice["message"]
    usage = res.get("usage") or {}
    if phase == "tool":
        calls = msg.get("tool_calls") or []
        if len(calls) != 1 or calls[0]["function"]["name"] != TOOL_NAME[fmt]:
            return None, "invalid_format", f"expected one {TOOL_NAME[fmt]} call, got {len(calls)} call(s)" + (
                " plus text" if msg.get("content") else ""), choice.get("finish_reason"), usage, msg
        try:
            args = json.loads(calls[0]["function"].get("arguments") or "")
        except Exception as e:
            return None, "invalid_format", f"bad arguments JSON: {e}", choice.get("finish_reason"), usage, msg
        if not isinstance(args, dict) or TOOL_PARAM[fmt] not in args:
            return None, "invalid_format", f"arguments missing '{TOOL_PARAM[fmt]}'", choice.get("finish_reason"), usage, msg
        return args[TOOL_PARAM[fmt]], None, None, choice.get("finish_reason"), usage, msg
    return msg.get("content") or "", None, None, choice.get("finish_reason"), usage, msg

def chat_feedback(messages, msg, fmt, note):
    messages = list(messages)
    calls = msg.get("tool_calls") or []
    messages.append({"role": "assistant", "content": msg.get("content") or "",
                     **({"tool_calls": calls} if calls else {})})
    for c in calls:
        messages.append({"role": "tool", "tool_call_id": c["id"], "content": note})
    if not calls:
        messages.append({"role": "user", "content": note})
    return messages

def api_responses(input_items, fmt, phase):
    body = {"model": MODEL, "input": input_items, "temperature": TEMP["v"]}
    if phase == "tool":
        body["tools"] = [{"type": "function", "name": TOOL_NAME[fmt],
                          "description": PROTOCOL_TEXT[fmt], "parameters": PARAMS[fmt]}]
    res, ms = _http("/v1/responses", {"Authorization": "Bearer magpie"}, body)
    usage_raw = res.get("usage") or {}
    usage = {"prompt_tokens": usage_raw.get("input_tokens", 0),
             "completion_tokens": usage_raw.get("output_tokens", 0)}
    out = res.get("output") or []
    status = res.get("status")
    finish = "length" if (status == "incomplete" and (res.get("incomplete_details") or {}).get("reason") == "max_output_tokens") else None
    calls = [o for o in out if o.get("type") == "function_call"]
    texts = [c.get("text", "") for o in out if o.get("type") == "message" for c in (o.get("content") or []) if c.get("type") == "output_text"]
    if phase == "tool":
        if len(calls) != 1 or calls[0].get("name") != TOOL_NAME[fmt]:
            return None, "invalid_format", f"expected one {TOOL_NAME[fmt]} call, got {len(calls)} call(s)" + (
                " plus text" if any(texts) else ""), finish, usage, {"output": out}
        try:
            args = json.loads(calls[0].get("arguments") or "")
        except Exception as e:
            return None, "invalid_format", f"bad arguments JSON: {e}", finish, usage, {"output": out}
        if not isinstance(args, dict) or TOOL_PARAM[fmt] not in args:
            return None, "invalid_format", f"arguments missing '{TOOL_PARAM[fmt]}'", finish, usage, {"output": out}
        return args[TOOL_PARAM[fmt]], None, None, finish, usage, {"output": out}
    return "".join(texts), None, None, finish, usage, {"output": out}

def responses_feedback(input_items, last, fmt, note):
    items = list(input_items)
    items.extend(last.get("output") or [])
    calls = [o for o in (last.get("output") or []) if o.get("type") == "function_call"]
    for c in calls:
        items.append({"type": "function_call_output", "call_id": c.get("call_id") or c.get("id"), "output": note})
    if not calls:
        items.append({"role": "user", "content": [{"type": "input_text", "text": note}]})
    return items

def api_anthropic(messages, fmt, phase):
    sys_msg = next((m["content"] for m in messages if m["role"] == "system"), "")
    chat_msgs = [m for m in messages if m["role"] != "system"]
    body = {"model": MODEL, "max_tokens": 4096, "messages": chat_msgs}
    if sys_msg:
        body["system"] = sys_msg
    if phase == "tool":
        body["tools"] = [{"name": TOOL_NAME[fmt], "description": PROTOCOL_TEXT[fmt],
                          "input_schema": PARAMS[fmt]}]
    res, ms = _http("/v1/messages", {"x-api-key": "magpie", "anthropic-version": "2023-06-01"}, body)
    usage_raw = res.get("usage") or {}
    usage = {"prompt_tokens": usage_raw.get("input_tokens", 0),
             "completion_tokens": usage_raw.get("output_tokens", 0)}
    blocks = res.get("content") or []
    stop = res.get("stop_reason")
    finish = "length" if stop == "max_tokens" else None
    calls = [b for b in blocks if b.get("type") == "tool_use"]
    texts = [b.get("text", "") for b in blocks if b.get("type") == "text"]
    if phase == "tool":
        if len(calls) != 1 or calls[0].get("name") != TOOL_NAME[fmt]:
            return None, "invalid_format", f"expected one {TOOL_NAME[fmt]} call, got {len(calls)} call(s)" + (
                " plus text" if any(texts) else ""), finish, usage, {"content": blocks}
        args = calls[0].get("input")
        if not isinstance(args, dict) or TOOL_PARAM[fmt] not in args:
            return None, "invalid_format", f"input missing '{TOOL_PARAM[fmt]}'", finish, usage, {"content": blocks}
        return args[TOOL_PARAM[fmt]], None, None, finish, usage, {"content": blocks}
    return "".join(texts), None, None, finish, usage, {"content": blocks}

def anthropic_feedback(messages, last, fmt, note):
    messages = list(messages)
    blocks = last.get("content") or []
    calls = [b for b in blocks if b.get("type") == "tool_use"]
    messages.append({"role": "assistant", "content": blocks})
    if calls:
        messages.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": c["id"], "content": note} for c in calls]})
    else:
        messages.append({"role": "user", "content": note})
    return messages

APIS = {"chat": (api_chat, chat_feedback), "responses": (api_responses, responses_feedback),
        "anthropic": (api_anthropic, anthropic_feedback)}

def initial_state(fmt, phase, task):
    system = COMMON if phase == "tool" else COMMON + "\n" + PROTOCOL_TEXT[fmt]
    listing = "\n\n".join(f"===== {rel}\n{content}" for rel, content in task["files"].items())
    user = f"文件内容：\n\n{listing}\n\n任务：{task['instruction']}"
    return system, user

# ---------------- eval loop ----------------

def run_cell(task, api, fmt, phase, rep, out_fh, lock):
    call, fb = APIS[api]
    results = []
    ws = tempfile.mkdtemp(prefix="edit-eval-")
    try:
        initial = dict(task["files"])
        work = dict(initial)
        test_file = os.path.join(ROOT, "tasks", task["id"], "tests", f"test_{task['id']}.py")
        system, user = initial_state(fmt, phase, task)
        if api == "responses":
            state = [{"role": "system" if phase != "tool" else "developer", "content": system},
                     {"role": "user", "content": [{"type": "input_text", "text": user}]}]
        else:
            state = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        for attempt in range(MAX_ATTEMPTS):
            rec = {"task": task["id"], "category": task["category"], "api": api, "model": MODEL,
                   "format": fmt, "phase": phase, "rep": rep, "attempt": attempt,
                   "transport_ok": False, "finish_reason": None, "parse_ok": False, "apply_ok": False,
                   "scope_ok": False, "tests_pass": False, "failure_stage": None,
                   "in_tok": 0, "out_tok": 0, "latency_ms": 0}
            try:
                text, stage, note, finish, usage, last = call(state, fmt, phase)
                rec["transport_ok"] = True
                rec["latency_ms"] = "n/a"
                rec["in_tok"] = usage.get("prompt_tokens", 0)
                rec["out_tok"] = usage.get("completion_tokens", 0)
            except Exception as e:
                rec["failure_stage"] = "api_error"
                rec["error"] = str(e)[:200]
                results.append(rec)
                break
            rec["finish_reason"] = finish
            if finish == "length":
                rec["failure_stage"] = "output_truncated"
                results.append(rec)
                continue
            if stage:
                rec["failure_stage"] = stage
                rec["error"] = note
                results.append(rec)
                state = fb(state, last, fmt, note + "\n请按协议重新输出。")
                continue
            snapshot = copy.deepcopy(work)
            try:
                FORMATS[fmt].apply(text, work)
                rec["parse_ok"] = True
                rec["apply_ok"] = True
            except Exception as e:
                rec["failure_stage"] = getattr(e, "stage", "invalid_format")
                rec["parse_ok"] = True  # reached the executor: text parsed into an operation
                rec["error"] = str(e)[:300]
                work.clear(); work.update(snapshot)
                results.append(rec)
                state = fb(state, last, fmt, f"编辑没有打上：{e}\n修正后重新输出。")
                continue
            changed = {p for p in set(work) | set(initial) if work.get(p) != initial.get(p)}
            forbidden = changed - set(task["allowed"])
            if forbidden:
                rec["failure_stage"] = "forbidden_file_change"
                rec["error"] = "changed: " + ",".join(sorted(forbidden))
                results.append(rec)
                state = fb(state, last, fmt, f"你改了不允许修改的文件：{sorted(forbidden)}。只允许改：{task['allowed']}。")
                continue
            rec["scope_ok"] = True
            wdir = tempfile.mkdtemp(prefix="edit-eval-test-")
            try:
                for rel, content in work.items():
                    p = os.path.join(wdir, rel)
                    if os.path.dirname(rel):
                        os.makedirs(os.path.dirname(p), exist_ok=True)
                    open(p, "w").write(content)
                try:
                    ok, out = run_tests(wdir, test_file, task.get("timeout_seconds", 30))
                except subprocess.TimeoutExpired:
                    ok, out = False, "timeout"
                    rec["failure_stage"] = "timeout"
                rec["tests_pass"] = ok
                if ok:
                    results.append(rec)
                    break
                if rec["failure_stage"] is None:
                    rec["failure_stage"] = "test_failure"
                rec["error"] = out[-300:]
                results.append(rec)
                state = fb(state, last, fmt, f"测试失败：\n{out[-800:]}\n修正后重新输出。")
            finally:
                shutil.rmtree(wdir, ignore_errors=True)
    finally:
        shutil.rmtree(ws, ignore_errors=True)
    with lock:
        for r in results:
            out_fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        out_fh.flush()
    return results

def load_tasks():
    tasks = []
    tdir = os.path.join(ROOT, "tasks")
    for name in sorted(os.listdir(tdir)):
        tj = os.path.join(tdir, name, "task.json")
        if not os.path.isfile(tj):
            continue
        meta = json.load(open(tj))
        files = {rel: open(os.path.join(tdir, name, "workspace", rel)).read()
                 for rel in meta["visible_files"]}
        tasks.append({**meta, "allowed": meta["allowed_write_files"], "files": files})
    return tasks

def main():
    global MODEL
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--apis", nargs="*", default=list(APIS))
    ap.add_argument("--phases", nargs="*", default=["text", "tool"])
    ap.add_argument("--tasks", nargs="*", default=None)
    ap.add_argument("--model", default=MODEL, help="magpie model id, e.g. kimi-code-cn/k3.1-pro")
    ap.add_argument("--out", default=os.path.join(ROOT, "results", "runs", "run.jsonl"),
                    help="never the committed baseline: results/results.jsonl")
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    MODEL = a.model
    if not os.path.isdir(os.path.join(ROOT, "tasks")):   # tasks are generated, not committed
        subprocess.run([sys.executable, os.path.join(ROOT, "make_tasks.py")], check=True)
    tasks = load_tasks()
    if a.tasks:
        tasks = [t for t in tasks if t["id"] in a.tasks]
    jobs = [(t, api, fmt, phase, rep) for t in tasks for api in a.apis
            for fmt in ("v4a", "sr") for phase in a.phases for rep in range(a.reps)]
    q = queue.Queue()
    for j in jobs:
        q.put(j)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    out_fh = open(a.out, "a")
    lock = threading.Lock()
    done = [0]
    total = len(jobs)

    def worker():
        while True:
            try:
                t, api, fmt, phase, rep = q.get_nowait()
            except queue.Empty:
                return
            try:
                rs = run_cell(t, api, fmt, phase, rep, out_fh, lock)
                last = rs[-1]
                mark = "PASS" if last["tests_pass"] else "fail:" + str(last["failure_stage"])
            except Exception as e:
                mark = "CRASH:" + str(e)[:100]
            with lock:
                done[0] += 1
                print(f"[{done[0]}/{total}] {t['id']} {api} {fmt} {phase} #{rep} -> {mark}", flush=True)

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(a.workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    out_fh.close()
    print("done")

if __name__ == "__main__":
    main()
