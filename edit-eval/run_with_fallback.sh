#!/bin/bash
# Run the edit-format evaluation with a provider fallback: if the primary model is out of
# quota, the same run continues on another provider's model of the same family.
#
# Usage: bash edit-eval/run_with_fallback.sh [primary-model] [fallback-model] [reps]
set -u
here=$(cd "$(dirname "$0")" && pwd)
cd "$here"

primary=${1:-kimi-code-cn/k3.1-pro}
fallback=${2:-moonshot-cn/kimi-k3.1-pro}
reps=${3:-3}
out="$here/results/runs/run-$(date +%Y%m%d-%H%M%S).jsonl"

probe() {
  curl -s -m 30 -X POST http://127.0.0.1:3425/v1/chat/completions \
    -H "Content-Type: application/json" -H "Authorization: Bearer magpie" \
    -d "{\"model\":\"$1\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"max_tokens\":5}"
}

if probe "$primary" | grep -q '"error"'; then
  echo "[fallback] $primary unavailable, using $fallback"
  model=$fallback
else
  echo "[primary] $primary available"
  model=$primary
fi

python3 "$here/runner.py" --model "$model" --reps "$reps" --out "$out"
echo "results: $out"
