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
