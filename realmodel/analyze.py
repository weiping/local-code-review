"""Summarise real-model reports: python3 realmodel/analyze.py realmodel/results/run-*.json
For each run: tokens, findings, how many run_shell calls there were and how many of them actually ran code
(python/pytest outside a heredoc body), as opposed to only writing a script to a file."""
import json, re, sys

RUNS_CODE = re.compile(r"\b(python3?|pytest)\b")


def runs_code(cmd):
    lines, out, end = cmd.splitlines(), [], None
    for line in lines:
        if end is not None:  # inside a heredoc body: data, not a command
            if line.strip() == end:
                end = None
            continue
        out.append(line)
        m = re.search(r"<<-?\s*['\"]?(\w+)['\"]?", line)
        if m:
            end = m.group(1)
            line = line[:m.start()]
            out[-1] = line
    return bool(RUNS_CODE.search("\n".join(out)))


for path in sys.argv[1:]:
    d = json.load(open(path))
    calls = [tc["function"] for m in d["messages"] for tc in (m.get("tool_calls") or [])]
    shells = [json.loads(c["arguments"]).get("command", "") for c in calls if c["name"] == "run_shell"]
    ran = sum(runs_code(c) for c in shells)
    print(f"{path}: tokens={d.get('tokens')} run_shell={len(shells)} ran_code={ran} "
          f"edits={sum(c['name'] in ('edit_file', 'create_file', 'delete_file') for c in calls)}")
    for f in d.get("findings", []):
        print(f"  {f.get('severity', '?'):6} {f.get('file', '?')}:{f.get('line', '?')} "
              f"confirmed={f.get('confirmed')} {str(f.get('explanation', ''))[:110]}")
