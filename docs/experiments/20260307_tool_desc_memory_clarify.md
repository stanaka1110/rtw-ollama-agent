# 実験: tool_desc_memory_clarify

**日時**: 2026-03-07
**ステータス**: 計画中

---

## 目的

英語・中国語両プロンプトで `remember()` がファイル保存の代替として使われる問題を解消する。
`_TOOL_LIST` / `_TOOL_LIST_ZH` の memory ツール説明に
「write_file の代替として使うな」という制約を追記する。

## 仮説

ツール説明に明示的な使い分け基準を追加することで：
- Task2: asyncio_notes.txt が `write_file` で保存される
- Task3: review.txt が `remember()` 経由ではなく `write_file` で直接保存される
- Judge スコア: 5/15（英語ベースライン）→ 8/15 以上を期待

根拠：
- 実験⑯/英語再実験で `remember()` 誤用は言語によらずモデルの癖と判明
- ツール説明に「ファイル保存の代替ではない」と書けばモデルの判断基準になる
- 英語では remember→write_file の2段階を踏んだ（説明強化で write_file のみに短縮できる）

## 設定変更

| 項目 | 変更前 | 変更後 |
|------|--------|--------|
| `_TOOL_LIST` memory 行 | `persist key-value notes` | `persist key-value notes across sessions. Do NOT use as a substitute for write_file — always save task outputs to files.` |
| `_TOOL_LIST_ZH` 内存行 | `持久化键值笔记。` | `在会话间持久化键值笔记。不要用来代替 write_file——任务输出必须保存到 /data/ 文件。` |

## 実験コマンド

```bash
# 英語（変更の効果を単独で見る）
./scripts/bench.sh --tier medium --models qwen2.5:14b --mode react

# 中国語（ベスト設定との比較）
./scripts/bench.sh --tier medium --models qwen2.5:14b --prompt zh --mode react
```

---

## 結果

> 実験後に `/record-experiment 20260307_tool_desc_memory_clarify` で記入

## 考察

> 実験後に `/conclude-experiment 20260307_tool_desc_memory_clarify` で記入
