# 実験: react_finish_tool_prompt

**日時**: 2026-03-06
**ステータス**: 計画中

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

> 実験後に `/record-experiment 20260306_react_finish_tool_prompt` で記入

## 考察

> 実験後に `/conclude-experiment 20260306_react_finish_tool_prompt` で記入
