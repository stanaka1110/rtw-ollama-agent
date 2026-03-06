# 実験: react_finish_tool_prompt

**日時**: 2026-03-06
**ステータス**: 結果記録済み

---

## 目的

実験⑬（react_finish_tool）で判明した根本問題を解消する。
`react_zh` プロンプトバリアントに `finish()` ツールの説明（存在・呼び方・タイミング）を追記し、
finish_tool 終了戦略でのタイムアウト（タスク1・2ともに EXEC_TIMEOUT=1200s）を解消して
Judge スコアを改善する。

## 仮説

モデルが `finish()` ツールの存在と呼び方を事前に知っていれば、タスク完了時に適切に
`finish()` を呼んでループを終了できる。

期待結果:
- Judge スコア: 2/15（実験⑬）→ 7/15（実験⑪ text 戦略）以上
- タイムアウト発生タスク数: 2/3 → 0/3
- TCA: 0.333（実験⑬）→ 0.5 以上（finish() もツール呼び出しにカウントされるため）

根拠:
- 実験⑬ではフィードバック注入自体は正常動作した（テキスト→continue が機能）
- 唯一の欠陥は「モデルが finish() の存在を知らない」こと
- プロンプトに一文追加するだけで解消できる最小コストの改善

## 設定変更

| 項目 | 変更前 | 変更後 |
|------|--------|--------|
| `REACT_TERMINATION` | `text` | `finish_tool` |
| `app/core/prompts.py` react_zh バリアント | finish ツールの説明なし | 「すべてのタスクが完了したら finish() を呼ぶ」旨を追記 |

### プロンプト追記内容（案）

`react_zh` バリアントのシステムプロンプトに以下を追加:

```
当所有任务完成后，必须调用 finish() 工具来结束会话。
在调用 finish() 之前，请确认所有要求的文件和操作都已完成。
```

（日本語訳: すべてのタスクが完了したら、finish() ツールを呼び出してセッションを終了してください。finish() を呼ぶ前に、要求されたすべてのファイルと操作が完了していることを確認してください。）

## 実験コマンド

```bash
REACT_TERMINATION=finish_tool \
  ./scripts/bench.sh --tier medium --models qwen2.5:14b --prompt zh --mode react
```

比較ベースライン（実験⑪ text 戦略）:
```bash
./scripts/bench.sh --tier medium --models qwen2.5:14b --prompt zh --mode react
```

---

## 結果

**実行日時**: 2026-03-06 15:46
**結果ディレクトリ**: test_results/bench_20260306_154638

### メトリクス

| モデル | TCA | StepCR | ErrRate | Replans | AvgTurns | AvgSec |
|--------|-----|--------|---------|---------|----------|--------|
| qwen2.5:14b | 0.833 | N/A | 0.200 | 0.0 | 5.7 | 1214 |

### タスク別結果

| タスク | 結果 | 所要時間 | Judge |
|--------|------|---------|-------|
| タスク1: SQLite INSERT → sales_report.txt | ❌ (timeout) | 1252s | 1/5 |
| タスク2: Web 検索 → asyncio_notes.txt | ❌ (timeout) | 1267s | 1/5 |
| タスク3: primes.py + review.txt | ❌ (timeout) | 1254s | 3/5 |

**Judge 合計**: 5/15（平均 1.7/5）

### 動作詳細

**タスク1**:
- Turn1: INSERT 10件 ✅
- Turn2-4: Python スクリプトの SyntaxError（unterminated string literal）を修正できず ❌
- Turn5: 複数 SQL 文を一括実行しようとして失敗 ❌
- Turn6 開始時に EXEC_TIMEOUT → sales_report.txt 未作成

**タスク2**:
- Turn1: web_search ✅
- Turn2: fetch_page ✅
- Turn3: `remember()` で概念を記録（write_file を呼ばず）
- Turn4(471.8s): テキスト応答 → EXEC_TIMEOUT(1200s) 到達で終了
- asyncio_notes.txt 未作成（write_file が呼ばれなかった）

**タスク3**:
- Turn1: primes.py 作成 ✅
- Turn2: 実行・確認 ✅
- Turn3: ファイル読み込み ✅
- Turn4: review.txt 作成 ✅（内容は3行の簡易レビュー）
- Turn5: review.txt 読み直し（確認）
- Turn6: テキスト応答 → フィードバック注入（finish_tool 動作）
- Turn7: review.txt 再読み（確認ループ）
- Turn8: テキスト応答 → フィードバック注入
- Turn9: EXEC_TIMEOUT → finish() 未呼び出しのまま終了

## 考察

> 実験後に `/conclude-experiment 20260306_react_finish_tool_prompt` で記入
