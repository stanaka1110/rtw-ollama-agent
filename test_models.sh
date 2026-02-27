#!/usr/bin/env bash
set -euo pipefail

MODELS=(
    "qwen2.5:7b"          # 7B：ベースライン
    "qwen2.5:14b"         # 14B：汎用
    "llama3.2:3b"         # 3B：軽量
    "lfm2.5-thinking"     # 1.2B：超軽量・推論特化
    "gemma3:4b"           # 4B：ノートPC向け汎用
    "phi4"                # 14B：STEM・論理推論
    "qwen3:30b-a3b"       # 30B(MoE)：高効率フラグシップ
    "deepseek-r1:14b"     # 14B：蒸留版・推論特化
)
TASKS=(
    # [CHAT]  Router → Chat path: ツール不使用で即答できるか
    "こんにちは"
    # [AGENT] 単一ツール: time ツール1回で完結
    "現在時刻を教えて"
    # [AGENT] マルチステップ: ファイル書き込み + シェル実行
    "1から5までの2乗を計算するPythonスクリプトを /data/test.py に書いて実行して"
)

# ── 出力先ディレクトリ：実行日時ごとに独立したフォルダを作成 ─────────────
RUN_DIR="test_results/$(date '+%Y%m%d_%H%M%S')"
mkdir -p "$RUN_DIR"
RESULTS_FILE="$RUN_DIR/model_test_results.txt"

echo "# モデルテスト結果 $(date '+%Y-%m-%d %H:%M')" > "$RESULTS_FILE"
echo "出力先: $RUN_DIR"

# テスト開始前の metrics.jsonl 行数を記録（今回分だけ抽出するため）
METRICS_LINES_BEFORE=$(docker exec langchain_app sh -c \
    'wc -l < /app/logs/metrics.jsonl 2>/dev/null || echo 0')

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

    TASK_IDX=0
    for TASK in "${TASKS[@]}"; do
        echo ""
        echo "  --- タスク: $TASK ---"
        echo "" >> "$RESULTS_FILE"
        echo "### タスク: $TASK" >> "$RESULTS_FILE"

        LOG_FILE="$RUN_DIR/${MODEL//[:.]/_}_task${TASK_IDX}.stderr.log"

        START=$(date +%s)
        OUTPUT=$(docker exec -e OLLAMA_MODEL="$MODEL" langchain_app python main.py "$TASK" 2>"$LOG_FILE" || echo "[ERROR]")
        ELAPSED=$(( $(date +%s) - START ))
        TASK_IDX=$(( TASK_IDX + 1 ))

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

# ── 今回のテスト分だけ metrics.jsonl から抽出してスナップショット保存 ──────
METRICS_SNAPSHOT="$RUN_DIR/metrics_snapshot.jsonl"
docker exec langchain_app sh -c \
    "tail -n +$(( METRICS_LINES_BEFORE + 1 )) /app/logs/metrics.jsonl 2>/dev/null || true" \
    > "$METRICS_SNAPSHOT"

# ── メトリクス集計（今回分のスナップショットを対象に表示）─────────────────
if [ -s "$METRICS_SNAPSHOT" ]; then
    METRICS_SUMMARY=$(python3 - "$METRICS_SNAPSHOT" <<'PYEOF'
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
)

    echo ""
    echo "========================================"
    echo " メトリクスサマリー ($METRICS_SNAPSHOT)"
    echo "========================================"
    echo "$METRICS_SUMMARY"

    echo "" >> "$RESULTS_FILE"
    echo "## メトリクスサマリー" >> "$RESULTS_FILE"
    echo "$METRICS_SUMMARY" >> "$RESULTS_FILE"
fi

echo ""
echo "保存先フォルダ: $RUN_DIR"
echo "  - model_test_results.txt  ... テキスト結果"
echo "  - metrics_snapshot.jsonl  ... 今回分の生メトリクス"
echo "  - *_task*.stderr.log      ... モデル/タスクごとのstderrログ"
