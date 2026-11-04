#!/bin/bash
# End-to-end demo: builds the sample repo, runs review.py under srt against the scripted fake model, checks results.
# Usage: bash run_demo.sh [srt|no-sandbox]
#   srt (default): needs srt on PATH; the --allow-domain cases reach pypi.org, so they need internet access.
#   no-sandbox: runs review.py --no-sandbox, for throwaway CI runners only; the srt limit checks are skipped there.
# The checks the fake model asks for are real commands that run in the sandbox; only the judgement is scripted.
# The CI workflow example has its own test: bash ci/run_ci_demo.sh (needs act).
set -u
here=$(cd "$(dirname "$0")" && pwd)
work=${WORK:-$(mktemp -d /tmp/ai-review-demo.XXXX)}
port=18700 pass=0 fail=0
sb=${1:-srt}
case $sb in srt) flags= ;; no-sandbox) flags=--no-sandbox ;; *) echo "usage: run_demo.sh [srt|no-sandbox]" >&2; exit 2 ;; esac
PY=${PY:-python3}; REVIEW="$PY $here/review.py $flags"
echo "review.py runs on: $($PY --version); mode $sb; srt $(srt --version 2>/dev/null || echo missing); $(uname -sm)"

server() { port=$((port + 1)); python3 "$here/fake_llm.py" "$port" "$1" "$work/requests.log" & srv=$!; sleep 0.4
           export LLM_BASE_URL="http://127.0.0.1:$port/v1"; }
stop() { kill "$srv" 2>/dev/null; wait "$srv" 2>/dev/null; }
fresh() { sh "$here/fixtures/make_repo.sh" "$work/repo" >/dev/null; cd "$work/repo"; }
tool_out() { python3 -c "import json,sys; d=json.load(open('$work/repo/.git/ai-review.json'))
print('\n'.join(m['content'] for m in d['messages'] if m['role'] in ('tool','user')))"; }
md5() { if command -v md5sum >/dev/null; then md5sum "$@"; else md5 -r "$@"; fi; }
tmpbase=$(python3 -c 'import os, tempfile; print(os.path.realpath(tempfile.gettempdir()))')
leftovers() { ls -d "$tmpbase"/ai-review-[a-z0-9_]* "$tmpbase"/ai-review-patch-* "$tmpbase"/ai-review-cfg-* 2>/dev/null | grep -v "^$work" ; }
check() { # name expected_exit actual_exit [extra condition result 0/1]
  local ok=0; [ "$2" = "$3" ] || ok=1; [ "${4:-0}" = 0 ] || ok=1
  [ -z "$(leftovers)" ] || { echo "   temp dirs left behind: $(leftovers | tr '\n' ' ')"; ok=1; rm -rf $(leftovers); }
  if [ $ok = 0 ]; then pass=$((pass+1)); r=PASS; else fail=$((fail+1)); r=FAIL; fi
  echo "$r  [$sb] $1 (exit $3, expected $2)"; }
rm -rf $(leftovers)

fresh; before=$(git status --porcelain; md5 app/orders.py)
server full; $REVIEW --model fake --context tests/test_orders.py > "$work/out.txt" 2>&1; rc=$?; stop
t=$(tool_out); c=0
for want in "injection rows: 3" "page 1 starts with: [20, 21, 22]" "revenue: 2400" "retry returned: None" \
            "RENAMED-PRESENT" "UNTRACKED-PRESENT" "294893" "path outside the repository" "found 0" \
            "file already exists" "Recorded edit_file for app/orders.py" "Recorded create_file for NOTES.md" \
            "STATE-KEPT" "NOTES-NOT-IN-SANDBOX" "severity must be one of"; do
  grep -qF -- "$want" <<<"$t" || { echo "   missing: $want"; c=1; }; done
# patches stay out of the sandbox: the revenue check after the edit still sees the original code
[ "$(grep -c 'revenue: 2400' <<<"$t")" -ge 2 ] && ! grep -q 'revenue: 1900' <<<"$t" || { echo "   patch reached the sandbox"; c=1; }
[ "$before" = "$(git status --porcelain; md5 app/orders.py)" ] || { echo "   working tree changed"; c=1; }
grep -q '"tool_choice": true' "$work/requests.log" && c=1
check "full review: 4 bugs reproduced, files kept between calls, patch kept out of the sandbox, refusals, worktree untouched" 1 $rc $c
grep -o 'HOME=[^ ]*' <<<"$t" | head -1 | sed 's/^/   sandbox sees /'

# read, write and environment limits: canaries in the real repo, the user's home and the system temp dir
if [ $sb = srt ]; then
fresh; hc=$(mktemp "$HOME/.ai-review-canary.XXXX"); tc=$(mktemp "$tmpbase/ai-review-canary.XXXX")
sc=$(mktemp /tmp/ai-review-canary.XXXX)   # on macOS /tmp is not the system temp dir ($TMPDIR)
export DEMO_REPO_FILE="$work/repo/app/orders.py" DEMO_HOME_CANARY="$hc" DEMO_TMP_CANARY="$tc" DEMO_SLASHTMP_CANARY="$sc"
server limits; LLM_API_KEY=demo-canary-key $REVIEW --model fake >/dev/null 2>&1; rc=$?; stop
t=$(tool_out); c=0
for p in "$DEMO_REPO_FILE" "$hc" "$tc" "$sc"; do
  grep -qF "READ-DENIED $p" <<<"$t" && grep -qF "WRITE-DENIED $p" <<<"$t" || { echo "   not denied: $p"; c=1; }
  [ ! -e "$p.w" ] || { echo "   written: $p.w"; c=1; rm -f "$p.w"; }; done
for want in "WRITE-DENIED /tmp" "WRITE-DENIED /tmp/claude" "TMPDIR-IS-HOME" "WRITE-OK-INSIDE" "SYSTEM-READABLE" "ENV-CLEAN"; do
  grep -qF -- "$want" <<<"$t" || { echo "   missing: $want"; c=1; }; done
[ ! -e /tmp/ai-review-demo-escape ] && [ ! -e /tmp/claude/ai-review-demo ] || { c=1; rm -f /tmp/ai-review-demo-escape /tmp/claude/ai-review-demo; }
grep -o 'ENV-NAMES.*' <<<"$t" | sed 's/^/   /'
rm -f "$hc" "$tc" "$sc"; unset DEMO_REPO_FILE DEMO_HOME_CANARY DEMO_TMP_CANARY DEMO_SLASHTMP_CANARY
check "limits: real repo, home, temp dirs unreadable and unwritable; /tmp/claude closed; TMPDIR=\$HOME; API key not in env" 0 $rc $c
else
  fresh; server limits; LLM_API_KEY=demo-canary-key $REVIEW --model fake > "$work/out.txt" 2>&1; rc=$?; stop
  t=$(tool_out); c=0; grep -q "WARNING: --no-sandbox" "$work/out.txt" || c=1; grep -q ENV-CLEAN <<<"$t" || c=1
  rm -f /tmp/ai-review-demo-escape /tmp/claude/ai-review-demo   # nothing stops these writes without srt
  check "--no-sandbox: loud warning printed; API key still kept out of the commands' env" 0 $rc $c
fi

fresh; server full; $REVIEW --model fake --context tests/test_orders.py --apply >/dev/null 2>&1; rc=$?; stop
c=0; grep -q '!= "refunded"' app/orders.py || c=1; [ -f NOTES.md ] || c=1
python3 -W error -c "import app.orders" 2>/dev/null || c=1
check "--apply writes the patch (fix + NOTES.md) to the worktree; host import has no SyntaxWarning" 1 $rc $c

fresh; server full; $REVIEW --model fake --no-inline-diff >/dev/null 2>&1; rc=$?; stop
c=0; tool_out | grep -q '```diff' && c=1
check "--no-inline-diff keeps the diff out of the first message" 1 $rc $c

fresh; server clean; $REVIEW --model fake >/dev/null 2>&1; rc=$?; stop
check "no findings" 0 $rc

fresh; server unconfirmed; $REVIEW --model fake >/dev/null 2>&1; rc=$?; stop
check "unconfirmed high does not block by default" 0 $rc
server unconfirmed; $REVIEW --model fake --block-unconfirmed >/dev/null 2>&1; rc=$?; stop
check "--block-unconfirmed makes it block" 1 $rc
server unconfirmed; $REVIEW --model fake --block-unconfirmed --block-at medium >/dev/null 2>&1; rc=$?; stop
check "--block-at medium with --block-unconfirmed still blocks a high finding" 1 $rc

fresh; server silent; $REVIEW --model fake >/dev/null 2>&1; rc=$?; stop
c=0; python3 -c "import json; d=json.load(open('.git/ai-review.json')); assert d['error'] and d['tokens'] >= 0" 2>/dev/null || c=1
check "model never calls submit_review (report keeps the error and token count)" 2 $rc $c

fresh; LLM_BASE_URL=http://127.0.0.1:9/v1 $REVIEW --model fake >/dev/null 2>&1; rc=$?
check "model server unreachable" 2 $rc

fresh; server clean; $REVIEW --model fake --max-diff-kb 1 >/dev/null 2>&1; rc=$?; stop
check "diff over --max-diff-kb" 2 $rc

fresh; $REVIEW >/dev/null 2>&1; rc=$?
check "missing --model" 2 $rc

fresh; git stash -q -u; git commit -q --allow-empty -m empty; $REVIEW --model fake --head HEAD --apply >/dev/null 2>&1; rc=$?
check "--apply with --head is refused" 2 $rc

fresh; cd app; server full; $REVIEW --model fake --context ../tests/test_orders.py >/dev/null 2>&1; rc=$?; stop
cd ..; c=0; [ -f .git/ai-review.json ] || c=1
check "run from a subdirectory" 1 $rc $c

fresh; server network; $REVIEW --model fake >/dev/null 2>&1; rc=$?; stop
net=$(tool_out | grep -o 'NET-[A-Z]*' | head -1); echo "   network probe: $net"
want=NET-BLOCKED; [ $sb = no-sandbox ] && want=NET-OPEN   # without srt nothing stops the network
c=0; [ "$net" = $want ] || c=1
check "network probe gives $want" 0 $rc $c

fresh; server timeout; start=$(date +%s)
$REVIEW --model fake --shell-timeout 3 >/dev/null 2>&1; rc=$?; stop; sleep 1
c=0; tool_out | grep -q "timed out after 3s" || c=1; pgrep -f "sleep 30[12]" >/dev/null && { c=1; echo "   sleep left running"; pkill -f "sleep 30[12]"; }
check "run_shell timeout kills the command and its children ($(( $(date +%s) - start ))s)" 0 $rc $c

fresh; server delete; $REVIEW --model fake --apply > "$work/out.txt" 2>&1; rc=$?; stop
t=$(tool_out); c=0
grep -q "deleted app/report.py" "$work/out.txt" && [ ! -e app/report.py ] || { echo "   delete not applied"; c=1; }
grep -qF "no such file: no/such.py" <<<"$t" && grep -q REPORT-STILL-IN-SANDBOX <<<"$t" || c=1
[ -f data/catalog.txt ] && [ ! -e scratch.txt ] || { echo "   sandbox rm leaked or scratch file applied"; c=1; }
check "delete_file: --apply deletes in the worktree; rm in the sandbox does not" 0 $rc $c

if [ $sb = srt ]; then
fresh; server allow; $REVIEW --model fake --allow-domain pypi.org --allow-domain files.pythonhosted.org \
  > "$work/out.txt" 2>&1; rc=$?; stop
t=$(tool_out); c=0
for want in "https://pypi.org/simple/six/ 200" "https://example.com/ BLOCKED" "DIRECT-BLOCKED" "PIP-OK" "PIP-KEPT"; do
  grep -qF -- "$want" <<<"$t" || { echo "   missing: $want"; c=1; }; done
check "--allow-domain: pypi reachable, pip install works and lasts, example.com and direct sockets blocked" 0 $rc $c

fresh; server private; $REVIEW --model fake --allow-domain 10.0.0.1.nip.io --allow-domain pypi.org > "$work/out.txt" 2>&1; rc=$?; stop
t=$(tool_out); c=0; grep -o '[A-Z]*-STATUS [0-9]*\|PRIVATE-BLOCKED' <<<"$t" | sed 's/^/   /'
grep -q "PUBLIC-STATUS 200" <<<"$t" || c=1; grep -q "PRIVATE-STATUS 2" <<<"$t" && c=1
check "--allow-domain: an allowed name that resolves to a private address is refused" 0 $rc $c
else
  fresh; $REVIEW --model fake --allow-domain pypi.org >/dev/null 2>&1; rc=$?
  check "--no-sandbox refuses --allow-domain (no allowlist without srt)" 2 $rc
fi

fresh; $REVIEW --model fake --allow-domain 'PyPI.org;rm' >/dev/null 2>&1; rc=$?
check "--allow-domain rejects a malformed host" 2 $rc

fresh; server timeout; $REVIEW --model fake --shell-timeout 60 >/dev/null 2>&1 & rp=$!
sleep 8; kill -TERM $rp; wait $rp; rc=$?; stop; sleep 1
c=0; pgrep -f "sleep 30[12]" >/dev/null && { echo "   sandboxed command left running"; c=1; pkill -f "sleep 30[12]"; }
check "SIGTERM (timeout or CI cancel): exit 2, temp dirs removed, sandboxed command stopped" 2 $rc $c

if [ $sb = srt ] && [ "$(uname)" = Darwin ]; then
  # newer macOS ships a BSD /usr/bin/timeout; older macOS has none unless coreutils is installed
  tools=$(mktemp -d "$work/tools.XXXX")   # /usr/bin without timeout, plus node, srt, python3 and git from PATH
  for f in /usr/bin/*; do [ "${f##*/}" = timeout ] || ln -s "$f" "$tools/"; done
  for b in node srt python3 git; do ln -sf "$(command -v $b)" "$tools/$b"; done
  if [ -x /usr/bin/timeout ]; then
    fresh; server timeout; start=$(date +%s)
    PATH="/usr/bin:/bin:/usr/sbin:/sbin:$tools" $REVIEW --model fake --shell-timeout 3 >/dev/null 2>&1; rc=$?; stop; sleep 1
    c=0; tool_out | grep -q "timed out after 3s" || c=1
    pgrep -f "sleep 30[12]" >/dev/null && { c=1; echo "   sleep left running"; pkill -f "sleep 30[12]"; }
    check "macOS /usr/bin/timeout (BSD) also stops the command and its children ($(( $(date +%s) - start ))s)" 0 $rc $c
  fi
  fresh; server timeout; start=$(date +%s)
  PATH="$tools:/bin:/usr/sbin:/sbin" $REVIEW --model fake --shell-timeout 3 >/dev/null 2>&1; rc=$?; stop; sleep 1
  c=0; tool_out | grep -q "timed out after 3s (process group killed)" || c=1
  pgrep -f "sleep 30[12]" >/dev/null && { c=1; echo "   sleep left running"; pkill -f "sleep 30[12]"; }
  check "no timeout(1) on PATH: the fallback kills the process group at limit + 15s ($(( $(date +%s) - start ))s)" 0 $rc $c
fi

nosrt=$(mktemp -d "$work/nosrt.XXXX"); for b in python3 git bash sh; do ln -s "$(command -v $b)" "$nosrt/$b"; done
if [ $sb = no-sandbox ]; then
  fresh; server full; PATH="$nosrt:/usr/bin:/bin" $REVIEW --model fake >/dev/null 2>&1; rc=$?; stop
  check "--no-sandbox works without srt installed" 1 $rc
else
fresh; server clean; PATH="$nosrt:/usr/bin:/bin" $REVIEW --model fake > "$work/out.txt" 2>&1; rc=$?; stop
c=0; grep -q "srt not found" "$work/out.txt" || c=1
check "srt not on PATH: exit 2 with an install hint" 2 $rc $c
printf '#!/bin/sh\necho "fake srt: sandbox unavailable" >&2\nexit 1\n' > "$nosrt/srt"; chmod +x "$nosrt/srt"
fresh; server clean; PATH="$nosrt:$PATH" $REVIEW --model fake > "$work/out.txt" 2>&1; rc=$?; stop
c=0; grep -q "srt could not start a sandbox" "$work/out.txt" && grep -q "fake srt: sandbox unavailable" "$work/out.txt" || c=1
check "srt cannot start a sandbox: exit 2, srt's error printed" 2 $rc $c
fi

echo "== pre-push hook"
fresh; git stash -q -u; git init -q --bare "$work/remote.git"; git remote add origin "$work/remote.git"
git push -q origin main; git stash pop -q; git add -A; git commit -qm "the change"
cp "$here/fixtures/pre-push" .git/hooks/pre-push && chmod +x .git/hooks/pre-push
if [ $sb = srt ]; then cp "$here/review.py" review.py   # the hook runs review.py from the repository root, as in the blog
else printf 'import os, sys\nos.execv(sys.executable, [sys.executable, "-I", %s, "--no-sandbox", *sys.argv[1:]])\n' \
       "\"$here/review.py\"" > review.py; fi
export AI_REVIEW_MODEL=fake
server full; git push -q origin main >/dev/null 2>&1; rc=$?; stop
c=0; [ "$(git rev-parse origin/main)" != "$(git rev-parse HEAD)" ] || c=1
check "pre-push: blocking findings in the pushed commit stop the push" 1 $rc $c
LLM_BASE_URL=http://127.0.0.1:9/v1 git push -q origin main >/dev/null 2>&1; rc=$?
c=0; [ "$(git rev-parse origin/main)" != "$(git rev-parse HEAD)" ] || c=1
check "pre-push: an incomplete review (model server down) also stops the push" 1 $rc $c
server clean; git push -q origin main >/dev/null 2>&1; rc=$?; stop
check "pre-push: a clean review lets the push through" 0 $rc
echo "# notes" > NOTES.md; git add NOTES.md; git commit -qm notes
AI_REVIEW_ON_INCOMPLETE=warn LLM_BASE_URL=http://127.0.0.1:9/v1 git push -q origin main >/dev/null 2>&1; rc=$?
c=0; [ "$(git rev-parse origin/main)" = "$(git rev-parse HEAD)" ] || c=1
check "pre-push: AI_REVIEW_ON_INCOMPLETE=warn lets an incomplete review through" 0 $rc $c

echo; echo "passed $pass, failed $fail (work dir: $work)"
[ $fail = 0 ]
