#!/usr/bin/env python3
"""A scripted stand-in for an OpenAI-compatible chat completions server.

It ignores what the reviewer says and returns the tool calls of one scenario, turn by turn.
The checks it asks for are real commands that run in the chosen sandbox; only the judgement is fake.
Usage: python3 fake_llm.py PORT SCENARIO [REQUEST_LOG]
"""
import json, os, shlex, socketserver, sys
from http.server import BaseHTTPRequestHandler, HTTPServer

CHECK = r"""python3 - <<'PY'
import json
from app.orders import connect, find_orders, page, revenue, retry
conn = connect()
conn.executemany("INSERT INTO orders VALUES (?, ?, ?)", [(1, "paid", 1000), (2, "refunded", 500), (3, "paid", 900)])
print("injection rows:", len(find_orders(conn, "paid' OR '1'='1")), "(expected 0)")
print("page 1 starts with:", page(list(range(23)), 1)[:3], "(expected [0, 1, 2])")
orders = json.loads('[{"status": "paid", "amount": 1000}, {"status": "refunded", "amount": 500}, {"status": "paid", "amount": 900}]')
print("revenue:", revenue(orders), "(expected 1900)")
def down():
    raise RuntimeError("service down")
try:
    print("retry returned:", retry(down), "(expected an exception)")
except RuntimeError:
    print("retry raised RuntimeError")
PY"""
REVENUE = r"""python3 -c 'import json; from app.orders import revenue; print("revenue:", revenue(json.loads("[{\"status\": \"paid\", \"amount\": 1000}, {\"status\": \"refunded\", \"amount\": 500}, {\"status\": \"paid\", \"amount\": 900}]")))'"""
INSPECT = ("echo HOME=$HOME; echo PWD=$PWD; ls app; wc -c < data/catalog.txt; "
           "test -f app/helpers.py && echo RENAMED-PRESENT; test -f app/report.py && echo UNTRACKED-PRESENT; "
           "grep -c '^diff --git' change.diff")
NET = ("python3 -c \"import socket; socket.create_connection(('example.com', 80), timeout=5); print('NET-OPEN')\" "
       "2>/dev/null || echo NET-BLOCKED")
STATE = "echo STATE-KEPT > ${TMPDIR:-/tmp}/state.txt"
SANDBOX_CODE = "test -f NOTES.md && echo NOTES-IN-SANDBOX || echo NOTES-NOT-IN-SANDBOX"
ALLOW = r"""python3 - <<'PY'
import socket, urllib.request
for url in ("https://pypi.org/simple/six/", "https://example.com/"):
    try:
        print(url, urllib.request.urlopen(url, timeout=20).status)
    except Exception as e:
        print(url, "BLOCKED", type(e).__name__, e)
try:
    socket.create_connection(("pypi.org", 443), timeout=5)
    print("DIRECT-OPEN")
except Exception:
    print("DIRECT-BLOCKED")
PY"""
PIP = ("python3 -m pip install --target \"$HOME/pylib\" --no-cache-dir -q six 2>&1 | tail -2; "
       "PYTHONPATH=\"$HOME/pylib\" python3 -c 'import six; print(\"PIP-OK\")'")
PIP_KEPT = "PYTHONPATH=\"$HOME/pylib\" python3 -c 'import six; print(\"PIP-KEPT\")'"
# Paths outside the sandbox that run_demo.sh puts canary files in; the sandbox must not read or write them.
OUTSIDE = [os.environ.get(k, "/nonexistent") for k in ("DEMO_REPO_FILE", "DEMO_HOME_CANARY", "DEMO_TMP_CANARY", "DEMO_SLASHTMP_CANARY")]
q = shlex.quote
LIMITS = "; ".join(
    [f"cat {q(p)} >/dev/null 2>&1 && echo READ-OPEN {q(p)} || echo READ-DENIED {q(p)}" for p in OUTSIDE] +
    [f"touch {q(p + '.w')} 2>/dev/null && echo WRITE-OPEN {q(p)} || echo WRITE-DENIED {q(p)}" for p in OUTSIDE] +
    ["touch /tmp/ai-review-demo-escape 2>/dev/null && echo WRITE-OPEN /tmp || echo WRITE-DENIED /tmp",
     "mkdir -p /tmp/claude 2>/dev/null; touch /tmp/claude/ai-review-demo 2>/dev/null && echo WRITE-OPEN /tmp/claude"
     " || echo WRITE-DENIED /tmp/claude",
     "[ \"$TMPDIR\" = \"$HOME\" ] && echo TMPDIR-IS-HOME || echo TMPDIR-ELSEWHERE $TMPDIR",
     "touch \"$HOME/h\" ./w && echo WRITE-OK-INSIDE",
     "cat /etc/hosts >/dev/null && echo SYSTEM-READABLE",
     "env | grep -q demo-canary-key && echo ENV-LEAKED || echo ENV-CLEAN",
     "echo ENV-NAMES $(env | cut -d= -f1 | grep -v -i proxy | sort | tr '\\n' ' ')"])
PRIVATE = ("curl -s -m 10 -o /dev/null -w 'PRIVATE-STATUS %{http_code}\\n' http://10.0.0.1.nip.io/ || echo PRIVATE-BLOCKED; "
           "curl -s -m 20 -o /dev/null -w 'PUBLIC-STATUS %{http_code}\\n' https://pypi.org/simple/six/")
DUP = "def a(x):\n    y = x + 1\n    return y\n\n\ndef b(x):\n    y = x + 1\n    return y\n"
F = lambda file, line, sev, ok, why, ev: {"file": file, "line": line, "severity": sev, "confirmed": ok,
                                          "explanation": why, "evidence": ev}
GOOD = [F("app/orders.py", 12, "high", True, "status is formatted into the SQL string (injection)", "injection rows: 3"),
        F("app/orders.py", 16, "medium", True, "page 1 starts at index 20, off by one page", "page 1 starts with: [20, 21, 22]"),
        F("app/orders.py", 21, "high", True, "'is not' compares identity, refunded orders are counted", "revenue: 2400"),
        F("app/orders.py", 29, "medium", True, "retry swallows the last exception and returns None", "retry returned: None"),
        F("app/orders.py", 35, "low", False, "export_paid no longer closes the connection; a leak, not shown by a short check", "code reading")]
S = {
    "full": [
        [("run_shell", {"command": INSPECT}), ("run_shell", {"command": STATE})],
        [("run_shell", {"command": CHECK}), ("run_shell", {"command": "cat ${TMPDIR:-/tmp}/state.txt"})],
        [("edit_file", {"path": "../../etc/passwd", "old_str": "root", "new_str": "x"}),
         ("edit_file", {"path": "app/orders.py", "old_str": "no such text", "new_str": "x"})],
        [("edit_file", {"path": "app/orders.py", "old_str": 'is not "refunded"', "new_str": '!= "refunded"'}),
         ("create_file", {"path": "app/orders.py", "content": "x"}),
         ("create_file", {"path": "NOTES.md", "content": "Reviewed by the demo reviewer.\n"})],
        [("run_shell", {"command": REVENUE}), ("run_shell", {"command": SANDBOX_CODE})],
        [("submit_review", {"findings": [dict(GOOD[0], severity="critical")]})],
        [("submit_review", {"findings": GOOD})],
    ],
    "ambiguous": [[("create_file", {"path": "app/dup.py", "content": DUP})],
                  [("edit_file", {"path": "app/dup.py", "old_str": "    y = x + 1", "new_str": "    y = x + 2"})],
                  [("edit_file", {"path": "app/dup.py", "old_str": "def b(x):\n    y = x + 1",
                                  "new_str": "def b(x):\n    y = x + 2"})],
                  [("edit_file", {"path": "app/dup.py", "old_str": "    yy = x + 1", "new_str": "x"})],
                  [("submit_review", {"findings": []})]],
    "clean": [[("submit_review", {"findings": []})]],
    "unconfirmed": [[("submit_review", {"findings": [GOOD[4] | {"severity": "high"}]})]],
    "silent": [],
    # A model that never stops running checks: it only submits when told to wrap up.
    "late-submit": [[("run_shell", {"command": "echo still checking"})] for _ in range(40)],
    "network": [[("run_shell", {"command": NET})], [("submit_review", {"findings": []})]],
    "timeout": [[("run_shell", {"command": "sleep 301 & sleep 302; echo not-reached"})],
                [("submit_review", {"findings": []})]],
    "delete": [[("delete_file", {"path": "app/report.py"}), ("delete_file", {"path": "no/such.py"}),
                ("create_file", {"path": "scratch.txt", "content": "tmp\n"}), ("delete_file", {"path": "scratch.txt"})],
               [("run_shell", {"command": "rm data/catalog.txt && echo removed-in-sandbox; test -f app/report.py && echo REPORT-STILL-IN-SANDBOX"})],
               [("submit_review", {"findings": []})]],
    "limits": [[("run_shell", {"command": LIMITS})], [("submit_review", {"findings": []})]],
    "private": [[("run_shell", {"command": PRIVATE})], [("submit_review", {"findings": []})]],
    "allow": [[("run_shell", {"command": ALLOW})], [("run_shell", {"command": PIP})],
              [("run_shell", {"command": PIP_KEPT})],
              [("submit_review", {"findings": []})]],
}
name, turn = sys.argv[2], {"n": 0}
log = open(sys.argv[3], "a") if len(sys.argv) > 3 else None


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if log:
            log.write(json.dumps({"tools": len(body.get("tools", [])), "tool_choice": "tool_choice" in body,
                                  "messages": len(body["messages"])}) + "\n")
            log.flush()
        script, i = S[name], turn["n"]
        turn["n"] += 1
        if name == "late-submit":
            asked = any(m.get("role") == "user" and "turns left" in str(m.get("content", "")) for m in body["messages"])
            if asked:
                script, i = [[("submit_review", {"findings": []})]], 0
        calls = [{"id": f"call_{i}_{k}", "type": "function",
                  "function": {"name": tool, "arguments": json.dumps(args)}}
                 for k, (tool, args) in enumerate(script[i] if i < len(script) else [])]
        msg = {"role": "assistant", "content": None if calls else "I think the change looks fine."}
        if calls:
            msg["tool_calls"] = calls
        out = json.dumps({"choices": [{"message": msg}], "usage": {"total_tokens": 100}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *args):
        pass


class Server(HTTPServer):
    def server_bind(self):  # skip HTTPServer's getfqdn(): a slow reverse lookup of 127.0.0.1 delays listen() for ~35s
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = "127.0.0.1", self.server_address[1]


Server(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
