実験結果を実験ドキュメントに記録します。

## 手順

1. `$ARGUMENTS` で指定されたファイル名を使用する。
   - 拡張子なしでも可（例: `20260306_react_tca` → `docs/experiments/20260306_react_tca.md`）
   - 未指定の場合は `docs/experiments/` 配下で最新のファイルを使用する

2. 対象の実験ドキュメントを Read ツールで読む

3. 最新の bench 結果を収集する：
   - `test_results/` 配下で最新のディレクトリの `results.txt` を読む
   - 対応する `metrics_snapshot.jsonl` を読む

4. `/judge` スキルの手順に従い、各タスクの Judge スコアを評価する

5. 実験ドキュメントの `## 結果` セクションを以下の形式で **追記（上書きしない）** する：

```
## 結果

**実行日時**: YYYY-MM-DD HH:MM
**結果ディレクトリ**: test_results/<dir>

### メトリクス

| モデル | TCA | StepCR | ErrRate | Replans | AvgTurns | AvgSec |
|--------|-----|--------|---------|---------|----------|--------|
| <model> | x.xxx | x.xxx | x.xxx | x.x | x.x | xxx |

### タスク別結果

| タスク | 結果 | 所要時間 | Judge |
|--------|------|---------|-------|
| タスク1: <概要> | ✅/❌ | XXXs | N/5 |
| タスク2: <概要> | ✅/❌ | XXXs | N/5 |
| タスク3: <概要> | ✅/❌ | XXXs | N/5 |

**Judge 合計**: N/15（平均 N.N/5）
```

6. **ステータスを更新**する：ファイル先頭の `ステータス: 計画中` → `ステータス: 結果記録済み`

7. Judge レポートを `test_results/<dir>/judge_report.md` に保存する

8. 以下を実行する：
   ```
   git add docs/experiments/<filename>.md test_results/<dir>/judge_report.md
   git commit -m "experiment: record results for <name>"
   git push
   ```

9. 完了後に考察コマンドを案内する：
   ```
   /conclude-experiment <filename>
   ```
