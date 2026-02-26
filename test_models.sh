#!/usr/bin/env bash
set -euo pipefail

MODELS=("qwen2.5:7b" "qwen2.5:14b" "mistral:7b" "llama3.2:3b")
TASKS=(
    "現在時刻を教えて"
    "1から5までの2乗を計算するPythonスクリプトを /data/test.py に書いて実行して"
)

RESULTS_FILE="model_test_results.txt"
echo "# モデルテスト結果 $(date '+%Y-%m-%d %H:%M')" > "$RESULTS_FILE"

for MODEL in "${MODELS[@]}"; do
    echo ""
    echo "========================================"
    echo " MODEL: $MODEL"
    echo "========================================"
    echo "" >> "$RESULTS_FILE"
    echo "## $MODEL" >> "$RESULTS_FILE"

    # モデルを事前にロードしてコールドスタートを避ける
    echo "  [warmup] $MODEL ..."
    docker exec ollama ollama run "$MODEL" "hi" > /dev/null 2>&1 || true

    for TASK in "${TASKS[@]}"; do
        echo ""
        echo "  --- タスク: $TASK ---"
        echo "" >> "$RESULTS_FILE"
        echo "### タスク: $TASK" >> "$RESULTS_FILE"

        START=$(date +%s)
        OUTPUT=$(docker exec -e OLLAMA_MODEL="$MODEL" langchain_app python main.py "$TASK" 2>/dev/null || echo "[ERROR]")
        ELAPSED=$(( $(date +%s) - START ))

        echo "  結果: $OUTPUT"
        echo "  所要時間: ${ELAPSED}秒"
        echo "- 結果: $OUTPUT" >> "$RESULTS_FILE"
        echo "- 所要時間: ${ELAPSED}秒" >> "$RESULTS_FILE"
    done
done

echo ""
echo "========================================"
echo "テスト完了。結果: $RESULTS_FILE"
echo "========================================"

# ── メトリクス集計 ──────────────────────────────────────────────────────────
# metrics.jsonl から最新レコードをモデル別に集計して表示する。
# python3 と jq が使用可能な場合のみ実行する。
METRICS_FILE="$(docker exec langchain_app sh -c 'cat /app/logs/metrics.jsonl 2>/dev/null' || true)"

if [ -n "$METRICS_FILE" ]; then
    echo ""
    echo "========================================"
    echo " メトリクスサマリー (metrics.jsonl)"
    echo "========================================"
    echo "$METRICS_FILE" | python3 - <<'PYEOF'
import sys, json, collections

records = []
for line in sys.stdin:
    line = line.strip()
    if line:
        try:
            records.append(json.loads(line))
        except Exception:
            pass

# Aggregate by model (latest N records)
stats = collections.defaultdict(lambda: {"tca": [], "arg_fit": [], "step_cr": [], "count": 0})
for r in records:
    m = r.get("model", "unknown")
    stats[m]["tca"].append(r.get("tca", 0))
    stats[m]["arg_fit"].append(r.get("arg_fit_rate", 0))
    stats[m]["step_cr"].append(r.get("step_completion_rate", 0))
    stats[m]["count"] += 1

avg = lambda lst: round(sum(lst) / len(lst), 3) if lst else 0.0

print(f"{'Model':<20} {'Runs':>5} {'TCA':>7} {'ArgFit':>8} {'StepCR':>8}")
print("-" * 52)
for model, d in sorted(stats.items()):
    print(f"{model:<20} {d['count']:>5} {avg(d['tca']):>7.3f} {avg(d['arg_fit']):>8.3f} {avg(d['step_cr']):>8.3f}")
print("=" * 52)
PYEOF
fi
