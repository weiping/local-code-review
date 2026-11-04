#!/bin/bash
# Real-model runs on the demo repo: bash realmodel/run_real.sh MODEL SANDBOX RUNS
# Needs an OpenAI-compatible server at $LLM_BASE_URL (default: Ollama on localhost:11434).
set -u
here=$(cd "$(dirname "$0")/.." && pwd)
model=${1:?model} sb=${2:-bwrap} runs=${3:-3}
out=${OUT:-$here/realmodel/results}; mkdir -p "$out"
to=$(command -v timeout || command -v gtimeout)  # older macOS has neither; then runs have no overall limit
for i in $(seq 1 "$runs"); do
  repo=$(mktemp -d /tmp/ai-review-real.XXXX)
  sh "$here/fixtures/make_repo.sh" "$repo" >/dev/null && cd "$repo"
  start=$(date +%s)
  ${to:+$to 1500} python3 "$here/review.py" --model "$model" --sandbox "$sb" --context tests/test_orders.py --apply \
    > "$out/run-$i.txt" 2>&1; rc=$?
  secs=$(( $(date +%s) - start ))
  cp .git/ai-review.json "$out/run-$i.json" 2>/dev/null
  oracle=$(python3 -W ignore "$here/realmodel/oracle.py" 2>/dev/null || echo '{}')
  echo "{\"run\": $i, \"exit\": $rc, \"seconds\": $secs, \"oracle_after_apply\": $oracle}" | tee -a "$out/summary.jsonl"
  cd /; rm -rf "$repo"
done
