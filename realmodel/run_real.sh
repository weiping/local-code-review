#!/bin/bash
# Real-model runs on the demo repo: bash realmodel/run_real.sh MODEL [RUNS]
# Needs srt and an OpenAI-compatible server at $LLM_BASE_URL (review.py defaults to Magpie on 127.0.0.1:3425).
# OUT=dir picks the results directory; PAUSE=seconds waits between runs (for rate-limited endpoints).
set -u
here=$(cd "$(dirname "$0")/.." && pwd)
model=${1:?model} runs=${2:-3}
out=${OUT:-$here/realmodel/results}; mkdir -p "$out"
to=$(command -v timeout || command -v gtimeout)  # without either, runs have no overall limit
for i in $(seq 1 "$runs"); do
  [ "$i" -gt 1 ] && sleep "${PAUSE:-0}"
  repo=$(mktemp -d /tmp/ai-review-real.XXXX)
  sh "$here/fixtures/make_repo.sh" "$repo" >/dev/null && cd "$repo"
  start=$(date +%s)
  ${to:+$to 1500} python3 "$here/review.py" --model "$model" --context tests/test_orders.py --apply ${REVIEW_ARGS:-} \
    > "$out/run-$i.txt" 2>&1; rc=$?
  secs=$(( $(date +%s) - start ))
  cp .git/ai-review.json "$out/run-$i.json" 2>/dev/null
  tokens=$(python3 -c 'import json; print(json.load(open(".git/ai-review.json")).get("tokens", 0))' 2>/dev/null || echo null)
  oracle=$(python3 -W ignore "$here/realmodel/oracle.py" 2>/dev/null || echo '{}')
  echo "{\"run\": $i, \"exit\": $rc, \"seconds\": $secs, \"tokens\": $tokens, \"oracle_after_apply\": $oracle}" | tee -a "$out/summary.jsonl"
  cd /; rm -rf "$repo"
done
