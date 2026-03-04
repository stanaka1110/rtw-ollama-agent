#!/usr/bin/env bash
set -euo pipefail

MODELS=("qwen2.5:7b" "qwen2.5:14b")

TASKS=(
    "salesテーブルに商品名・数量・単価のデータを10件INSERTして、Pythonでsqlite3モジュールを使ってDBに接続し、合計売上・最高売上・最低売上・平均売上を計算して整形したレポートを/data/sales_report.txtに保存して"
    "Webで「Python asyncio tutorial」を検索して上位の結果ページを取得し、asyncioの主要な概念を5点に絞って日本語でまとめたノートを/data/asyncio_notes.txtに保存して"
    "バブルソートを実装したPythonモジュール/data/bubble_sort.pyと、それをテストする/data/test_bubble_sort.pyを作成して、pytestで実行して結果を報告して"
)

RUN_DIR="test_results/compare_$(date '+%Y%m%d_%H%M%S')"
mkdir -p "$RUN_DIR"
RESULTS_FILE="$RUN_DIR/results.txt"

echo "# 7b vs 14b 難易度比較 $(date '+%Y-%m-%d %H:%M')" | tee "$RESULTS_FILE"
echo "" | tee -a "$RESULTS_FILE"

METRICS_LINES_BEFORE=$(docker exec langchain_app sh -c \
    'wc -l < /app/logs/metrics.jsonl 2>/dev/null || echo 0')

for MODEL in "${MODELS[@]}"; do
    echo "" | tee -a "$RESULTS_FILE"
    echo "========================================" | tee -a "$RESULTS_FILE"
    echo " MODEL: $MODEL" | tee -a "$RESULTS_FILE"
    echo "========================================" | tee -a "$RESULTS_FILE"

    echo "  [warmup] $MODEL ..."
    docker exec ollama ollama run "$MODEL" "hi" > /dev/null 2>&1 || true

    TASK_IDX=0
    for TASK in "${TASKS[@]}"; do
        echo "" | tee -a "$RESULTS_FILE"
        echo "  --- タスク$((TASK_IDX+1)): ${TASK:0:40}... ---" | tee -a "$RESULTS_FILE"

        LOG_FILE="$RUN_DIR/${MODEL//[:.]/_}_task${TASK_IDX}.log"

        START=$(date +%s)
        OUTPUT=$(docker exec -e OLLAMA_MODEL="$MODEL" langchain_app python main.py "$TASK" 2>"$LOG_FILE" || echo "[ERROR]")
        ELAPSED=$(( $(date +%s) - START ))

        echo "  結果: $OUTPUT" | tee -a "$RESULTS_FILE"
        echo "  所要時間: ${ELAPSED}秒" | tee -a "$RESULTS_FILE"

        TASK_IDX=$(( TASK_IDX + 1 ))

        # 次タスクのためにデータをリセット
        docker exec langchain_app sh -c 'rm -rf /data/* 2>/dev/null || true'
    done
done

echo "" | tee -a "$RESULTS_FILE"
echo "========================================" | tee -a "$RESULTS_FILE"
echo "テスト完了" | tee -a "$RESULTS_FILE"
echo "========================================" | tee -a "$RESULTS_FILE"

# metrics 集計
METRICS_SNAPSHOT="$RUN_DIR/metrics_snapshot.jsonl"
docker exec langchain_app sh -c \
    "tail -n +$(( METRICS_LINES_BEFORE + 1 )) /app/logs/metrics.jsonl 2>/dev/null || true" \
    > "$METRICS_SNAPSHOT"

if [ -s "$METRICS_SNAPSHOT" ]; then
    SUMMARY=$(python3 - "$METRICS_SNAPSHOT" <<'PYEOF'
import sys, json, collections

records = []
with open(sys.argv[1], encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line:
            try:
                records.append(json.loads(line))
            except Exception:
                pass

stats = collections.defaultdict(lambda: {
    "tca": [], "name_acc": [], "arg_fit": [], "step_cr": [],
    "replans": [], "turns": [], "count": 0
})
for r in records:
    m = r.get("model", "unknown")
    stats[m]["tca"].append(r.get("tca", 0))
    stats[m]["name_acc"].append(r.get("tool_name_accuracy", 1))
    stats[m]["arg_fit"].append(r.get("arg_fit_rate", 1))
    stats[m]["step_cr"].append(r.get("step_completion_rate", 0))
    stats[m]["replans"].append(sum(1 for t in r.get("turns", []) if not t.get("tool_called")))
    stats[m]["turns"].append(r.get("total_turns", 0))
    stats[m]["count"] += 1

avg = lambda lst: round(sum(lst) / len(lst), 3) if lst else 0.0

print(f"\n{'Model':<20} {'Runs':>4} {'StepCR':>7} {'TCA':>6} {'NameAcc':>8} {'ArgFit':>7} {'AvgTurns':>9}")
print("-" * 65)
for model, d in sorted(stats.items()):
    print(f"{model:<20} {d['count']:>4} {avg(d['step_cr']):>7.3f} {avg(d['tca']):>6.3f} "
          f"{avg(d['name_acc']):>8.3f} {avg(d['arg_fit']):>7.3f} {avg(d['turns']):>9.1f}")
print("=" * 65)
PYEOF
)
    echo "$SUMMARY" | tee -a "$RESULTS_FILE"
fi

echo ""
echo "保存先: $RUN_DIR"
