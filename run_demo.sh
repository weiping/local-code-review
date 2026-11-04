#!/bin/bash
# End-to-end demo: builds the sample repo, runs review.py against the scripted fake model, checks results.
# Usage: ./run_demo.sh [backend ...]   (default: unsafe-local bwrap; also docker, podman)
# docker/podman also run one --allow-domain case that reaches pypi.org, so they need internet access.
# unsafe-local runs the scripted commands directly on this machine; they only read the demo repo,
# print $HOME and try one TCP connect to example.com:80, to show what that backend does NOT isolate.
# The CI workflow example has its own test: bash ci/run_ci_demo.sh [docker|bwrap] (needs act).
set -u
here=$(cd "$(dirname "$0")" && pwd)
work=${WORK:-$(mktemp -d /tmp/ai-review-demo.XXXX)}
backends=${*:-unsafe-local bwrap}
port=18700 pass=0 fail=0 results=()
PY=${PY:-python3}; REVIEW="$PY $here/review.py"; echo "review.py runs on: $($PY --version)"

server() { port=$((port + 1)); python3 "$here/fake_llm.py" "$port" "$1" "$work/requests.log" & srv=$!; sleep 0.4
           export LLM_BASE_URL="http://127.0.0.1:$port/v1"; }
stop() { kill "$srv" 2>/dev/null; wait "$srv" 2>/dev/null; }
fresh() { sh "$here/fixtures/make_repo.sh" "$work/repo" >/dev/null; cd "$work/repo"; }
tool_out() { python3 -c "import json,sys; d=json.load(open('$work/repo/.git/ai-review.json'))
print('\n'.join(m['content'] for m in d['messages'] if m['role'] in ('tool','user')))"; }
check() { # name expected_exit actual_exit [extra condition result 0/1]
  local ok=0; [ "$2" = "$3" ] || ok=1; [ "${4:-0}" = 0 ] || ok=1
  if [ $ok = 0 ]; then pass=$((pass+1)); r=PASS; else fail=$((fail+1)); r=FAIL; fi
  results+=("$r  [$sb] $1 (exit $3, expected $2)"); echo "$r  [$sb] $1 (exit $3, expected $2)"; }

for sb in $backends; do
  echo "== backend: $sb"
  fresh; before=$(git status --porcelain; md5sum app/orders.py)
  server full; $REVIEW --model fake --sandbox $sb --context tests/test_orders.py > "$work/out.txt" 2>&1; rc=$?; stop
  t=$(tool_out); c=0
  for want in "injection rows: 3" "page 1 starts with: [20, 21, 22]" "revenue: 2400" "retry returned: None" \
              "RENAMED-PRESENT" "UNTRACKED-PRESENT" "294893" "path outside the repository" "found 0" \
              "file already exists" "Recorded edit_file for app/orders.py" "Recorded create_file for NOTES.md" \
              "STATE-KEPT" "NOTES-NOT-IN-SANDBOX" "severity must be one of"; do
    grep -qF -- "$want" <<<"$t" || { echo "   missing: $want"; c=1; }; done
  # patches stay out of the sandbox: the revenue check after the edit still sees the original code
  [ "$(grep -c 'revenue: 2400' <<<"$t")" -ge 2 ] && ! grep -q 'revenue: 1900' <<<"$t" || { echo "   patch reached the sandbox"; c=1; }
  [ "$before" = "$(git status --porcelain; md5sum app/orders.py)" ] || { echo "   working tree changed"; c=1; }
  grep -q '"tool_choice": true' "$work/requests.log" && c=1
  check "full review: 4 bugs reproduced, /tmp kept, patch kept out of the sandbox, refusals, worktree untouched" 1 $rc $c
  grep -o 'HOME=[^ ]*' <<<"$t" | head -1 | sed 's/^/   sandbox sees /'

  fresh; server full; $REVIEW --model fake --sandbox $sb --context tests/test_orders.py --apply >/dev/null 2>&1; rc=$?; stop
  c=0; grep -q '!= "refunded"' app/orders.py || c=1; [ -f NOTES.md ] || c=1
  python3 -W error -c "import app.orders" 2>/dev/null || c=1
  check "--apply writes the patch (fix + NOTES.md) to the worktree; host import has no SyntaxWarning" 1 $rc $c

  fresh; server full; $REVIEW --model fake --sandbox $sb --no-inline-diff >/dev/null 2>&1; rc=$?; stop
  c=0; tool_out | grep -q '```diff' && c=1
  check "--no-inline-diff keeps the diff out of the first message" 1 $rc $c

  fresh; server clean; $REVIEW --model fake --sandbox $sb >/dev/null 2>&1; rc=$?; stop
  check "no findings" 0 $rc

  fresh; server unconfirmed; $REVIEW --model fake --sandbox $sb >/dev/null 2>&1; rc=$?; stop
  check "unconfirmed high does not block by default" 0 $rc
  server unconfirmed; $REVIEW --model fake --sandbox $sb --block-unconfirmed >/dev/null 2>&1; rc=$?; stop
  check "--block-unconfirmed makes it block" 1 $rc

  fresh; server silent; $REVIEW --model fake --sandbox $sb >/dev/null 2>&1; rc=$?; stop
  c=0; python3 -c "import json; d=json.load(open('.git/ai-review.json')); assert d['error'] and d['tokens'] >= 0" 2>/dev/null || c=1
  check "model never calls submit_review (report keeps the error and token count)" 2 $rc $c

  fresh; LLM_BASE_URL=http://127.0.0.1:9/v1 $REVIEW --model fake --sandbox $sb >/dev/null 2>&1; rc=$?
  check "model server unreachable" 2 $rc

  fresh; server clean; $REVIEW --model fake --sandbox $sb --max-diff-kb 1 >/dev/null 2>&1; rc=$?; stop
  check "diff over --max-diff-kb" 2 $rc

  fresh; $REVIEW --sandbox $sb >/dev/null 2>&1; rc=$?
  check "missing --model" 2 $rc

  fresh; cd app; server full; $REVIEW --model fake --sandbox $sb --context ../tests/test_orders.py >/dev/null 2>&1; rc=$?; stop
  cd ..; c=0; [ -f .git/ai-review.json ] || c=1
  check "run from a subdirectory" 1 $rc $c

  fresh; server network; $REVIEW --model fake --sandbox $sb >/dev/null 2>&1; rc=$?; stop
  net=$(tool_out | grep -o 'NET-[A-Z]*' | head -1); echo "   network probe: $net"
  want=NET-BLOCKED; [ $sb = unsafe-local ] && want=NET-OPEN
  c=0; [ "$net" = "$want" ] || c=1
  check "network probe gives $want" 0 $rc $c

  fresh; server timeout; start=$(date +%s)
  $REVIEW --model fake --sandbox $sb --shell-timeout 3 >/dev/null 2>&1; rc=$?; stop; sleep 1
  c=0; tool_out | grep -q "timed out after 3s" || c=1; pgrep -f "sleep 30[12]" >/dev/null && { c=1; pkill -f "sleep 30[12]"; }
  check "run_shell timeout kills the whole process group ($(( $(date +%s) - start ))s)" 0 $rc $c

  fresh; server delete; $REVIEW --model fake --sandbox $sb --apply > "$work/out.txt" 2>&1; rc=$?; stop
  t=$(tool_out); c=0
  grep -q "deleted app/report.py" "$work/out.txt" && [ ! -e app/report.py ] || { echo "   delete not applied"; c=1; }
  grep -qF "no such file: no/such.py" <<<"$t" && grep -q REPORT-STILL-IN-SANDBOX <<<"$t" || c=1
  [ -f data/catalog.txt ] && [ ! -e scratch.txt ] || { echo "   sandbox rm leaked or scratch file applied"; c=1; }
  check "delete_file: --apply deletes in the worktree; rm in the sandbox does not" 0 $rc $c

  if [ $sb = docker ] || [ $sb = podman ]; then
    fresh; server allow; $REVIEW --model fake --sandbox $sb --allow-domain pypi.org --allow-domain files.pythonhosted.org \
      > "$work/out.txt" 2>&1; rc=$?; stop
    left() { [ -n "$($sb ps -aq --filter name=ai-review-)" ] || ls -d /tmp/ai-review-proxy-* "${TMPDIR:-/tmp}"/ai-review-proxy-* \
             >/dev/null 2>&1 && { echo "   container or proxy socket left behind" >&2; echo 1; } || echo 0; }
    if [ "$(uname)" = Darwin ]; then  # Docker Desktop cannot pass the host's unix socket into the container
      c=$(left); grep -q "cannot reach the allowlist proxy" "$work/out.txt" || c=1
      check "--allow-domain on macOS: refused with a clear error, nothing left behind" 2 $rc $c
    else
      t=$(tool_out); c=$(left)
      for want in "https://pypi.org/simple/six/ 200" "https://example.com/ BLOCKED" "DIRECT-BLOCKED" "PIP-OK" "PIP-KEPT"; do
        grep -qF -- "$want" <<<"$t" || { echo "   missing: $want"; c=1; }; done
      check "--allow-domain: pypi reachable, pip install works and lasts, example.com and direct sockets blocked" 0 $rc $c
    fi

    fresh; server timeout; $REVIEW --model fake --sandbox $sb --shell-timeout 60 >/dev/null 2>&1 & rp=$!
    sleep 10; kill -TERM $rp; wait $rp; rc=$?; stop
    c=0; [ -z "$($sb ps -aq --filter name=ai-review-)" ] || { echo "   container left behind"; c=1; }
    check "SIGTERM (timeout or CI cancel) still removes the container" 2 $rc $c

    fresh; $sb build -q -t ai-review-deps -f "$here/fixtures/Dockerfile.deps" "$here/fixtures" >/dev/null 2>&1
    server deps; $REVIEW --model fake --sandbox $sb --image ai-review-deps >/dev/null 2>&1; rc=$?; stop
    t=$(tool_out); c=0; grep -q "IMAGE-DEPS-OK 1.17.0" <<<"$t" && grep -q NET-BLOCKED <<<"$t" || c=1
    check "--image with fixtures/Dockerfile.deps: dependency importable with the network off" 0 $rc $c
  else
    fresh; server clean; $REVIEW --model fake --sandbox $sb --allow-domain pypi.org >/dev/null 2>&1; rc=$?; stop
    check "--allow-domain is refused on $sb (no allowlist there)" 2 $rc
  fi
done

sb=${backends%% *}; case " $backends " in *" bwrap "*) sb=bwrap;; esac
echo "== pre-push hook (backend $sb)"
fresh; git stash -q -u; git init -q --bare "$work/remote.git"; git remote add origin "$work/remote.git"
git push -q origin main; git stash pop -q; git add -A; git commit -qm "the change"
cp "$here/fixtures/pre-push" .git/hooks/pre-push && chmod +x .git/hooks/pre-push
export AI_REVIEW_SCRIPT="$here/review.py" AI_REVIEW_MODEL=fake AI_REVIEW_SANDBOX=$sb
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

if ! command -v docker >/dev/null; then
  sb=none; fresh; server clean; $REVIEW --model fake --sandbox docker >/dev/null 2>&1; rc=$?; stop
  check "docker backend selected but docker not installed" 2 $rc
fi

echo; echo "passed $pass, failed $fail (work dir: $work)"
echo "CI workflow example: bash ci/run_ci_demo.sh [docker|bwrap]   (needs act)"
[ $fail = 0 ]
