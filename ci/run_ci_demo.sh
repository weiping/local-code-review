#!/bin/bash
# Runs ci/ai-review.yml locally with act (nektos/act) against the demo repo and fake model.
# Usage: bash ci/run_ci_demo.sh   (needs act; -P ubuntu-latest=-self-hosted runs the steps directly on this machine,
# with review.py --no-sandbox as in the workflow, so run it only on a throwaway machine such as a CI runner)
set -u
here=$(cd "$(dirname "$0")/.." && pwd)
work=$(mktemp -d /tmp/ai-review-ci.XXXX)
ACT=${ACT:-act}
port=18900 pass=0 fail=0
echo "act: $($ACT --version)   work: $work"

# demo repo: main has the workflow and tools/review.py; each PR branch is one commit on top of main
sh "$here/fixtures/make_repo.sh" "$work/repo" >/dev/null && cd "$work/repo"
git stash -q -u
mkdir -p tools .github/workflows && cp "$here/review.py" tools/ && cp "$here/ci/ai-review.yml" .github/workflows/
git add -A && git commit -qm "add AI review" && git remote add origin https://github.com/demo/shop.git
git checkout -q -b buggy && git stash pop -q && git add -A && git commit -qm "orders changes"
git checkout -q -b tampered && printf 'import sys\nsys.exit(0)\n' > tools/review.py && git commit -qam "skip the review"
git checkout -q -b clean main && echo "# shop" > README.md && git add README.md && git commit -qm "readme"
mkdir -p "$work/cfg/act" && touch "$work/cfg/act/actrc"

run() { # name branch scenario expected(pass|fail) grep-pattern [base_url] [head_repo]
  local name=$1 branch=$2 scen=$3 want=$4 pat=$5 url=${6:-} repo=${7:-demo/shop}
  port=$((port + 1)); git checkout -q "$branch"
  printf '{"pull_request":{"number":1,"base":{"sha":"%s","ref":"main"},"head":{"sha":"%s","ref":"%s","repo":{"full_name":"%s"}}},"repository":{"full_name":"demo/shop"}}' \
    "$(git rev-parse main)" "$(git rev-parse HEAD)" "$branch" "$repo" > "$work/event.json"
  python3 "$here/fake_llm.py" $port "$scen" & local srv=$!; sleep 0.4
  rm -rf "$work/artifacts"
  XDG_CONFIG_HOME="$work/cfg" $ACT pull_request -W .github/workflows/ai-review.yml -e "$work/event.json" \
    -P ubuntu-latest=-self-hosted --artifact-server-path "$work/artifacts" \
    --var LLM_BASE_URL="${url:-http://127.0.0.1:$port/v1}" --var AI_REVIEW_MODEL=fake \
    --secret LLM_API_KEY=fake \
    > "$work/$name.log" 2>&1
  local rc=$?; kill $srv 2>/dev/null; wait $srv 2>/dev/null
  local got=pass; [ $rc = 0 ] || got=fail
  local ok=0; [ "$got" = "$want" ] || ok=1; if [ "${pat#!}" != "$pat" ]; then grep -qF -- "${pat#!}" "$work/$name.log" && ok=1
  else grep -qF -- "$pat" "$work/$name.log" || ok=1; fi
  local art=$(find "$work/artifacts" -name '*.zip' 2>/dev/null | wc -l)
  if [ $ok = 0 ]; then pass=$((pass+1)); r=PASS; else fail=$((fail+1)); r=FAIL; fi
  echo "$r  $name: job $got (expected $want), artifacts: $art, log: $work/$name.log"
}

run buggy-pr     buggy    full  fail "::error title=AI review::blocking findings"
run clean-pr     clean    clean pass "AI review passed"
run config-error clean    clean fail "::error title=AI review incomplete::exit 2" "http://127.0.0.1:9/v1"
run unconverged  clean    silent fail "::error title=AI review incomplete::exit 2"
run tampered-pr  tampered full  fail "::error title=AI review::blocking findings"
run fork-pr      buggy    full  pass "!Review base...head" "" "someone/fork"   # job skipped by its if:
# the buggy PR must have uploaded the report and the suggested patch
run buggy-artifact buggy full fail "Artifact ai-review has been successfully uploaded"
zip=$(find "$work/artifacts" -name '*.zip' | head -1)
if [ -n "$zip" ] && python3 -c 'import sys, zipfile; n = zipfile.ZipFile(sys.argv[1]).namelist(); print("  artifact contents:", n); sys.exit(not {"ai-review.json", "ai-review.patch"} <= set(n))' "$zip"
then pass=$((pass+1)); echo "PASS  artifact has ai-review.json and ai-review.patch"
else fail=$((fail+1)); echo "FAIL  artifact is missing ai-review.json or ai-review.patch"; fi

echo; echo "passed $pass, failed $fail"
[ $fail = 0 ]
