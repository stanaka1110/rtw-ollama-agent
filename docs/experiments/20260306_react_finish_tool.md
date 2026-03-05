# 実験: react_finish_tool

**日時**: 2026-03-06
**ステータス**: 計画中

---

## 目的

react モードの TCA 低下（実験⑪: 0.472）の原因である「thinking テキストで早期終了」パターンを
`finish_tool` 終了戦略で排除し、Judge スコアを改善する。

現状: モデルが "まず〜します" というテキストを出力した瞬間にループが終了してしまい、
実際のツール実行に至らない（SQLite タスクが tool call 0回で 0/5）。

## 仮説

`REACT_TERMINATION=finish_tool` にすることで:
- テキスト応答 → 終了ではなく、フィードバック注入してループ継続
- モデルは `finish()` を明示的に呼ぶまで作業を続けざるを得ない
- 結果: TCA 改善 / Judge スコア 7/15 → 10/15 以上を期待

副作用リスク:
- ループが終わらずタイムアウトになる可能性（finish() を呼ばずフィードバックループに入る）
- プロンプトに `finish()` の説明がないため呼び方を知らない可能性

## 設定変更

| 項目 | 変更前 | 変更後 |
|------|--------|--------|
| `REACT_TERMINATION` | `text` | `finish_tool` |
| `AGENT_MODE` | `react` | `react` (変更なし) |
| `PROMPT_VARIANT` | `zh` | `zh` (変更なし) |
| モデル | `qwen2.5:14b` | `qwen2.5:14b` (変更なし) |

## 実験コマンド

```bash
REACT_TERMINATION=finish_tool \
  ./scripts/bench.sh --tier medium --models qwen2.5:14b --prompt zh --mode react
```

比較用（前回ベースライン、実験⑪相当）:
```bash
./scripts/bench.sh --tier medium --models qwen2.5:14b --prompt zh --mode react
```

---

## 結果

> 実験後に `/record-experiment 20260306_react_finish_tool` で記入

## 考察

> 実験後に `/conclude-experiment 20260306_react_finish_tool` で記入
