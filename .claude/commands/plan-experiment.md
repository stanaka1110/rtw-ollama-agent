新しい実験計画ドキュメントを `docs/experiments/` に作成します。

## 手順

1. `$ARGUMENTS` を実験名（スネークケース）として使用する。
   未指定の場合はユーザーに実験名を確認する。

2. 以下の情報を会話から読み取るか、不明な場合はユーザーに確認する：
   - **目的**: 何を改善・検証したいか
   - **仮説**: 期待される結果とその根拠
   - **設定変更**: 変更するコード・パラメータ（具体的に）
   - **実験コマンド**: 使用する bench コマンド

3. 今日の日付（YYYYMMDD形式）を取得し、
   `docs/experiments/YYYYMMDD_<name>.md` を以下のテンプレートで Write ツールを使って作成する：

```
# 実験: <name>

**日時**: YYYY-MM-DD
**ステータス**: 計画中

---

## 目的

<何を改善・検証したいか>

## 仮説

<期待される結果と根拠>

## 設定変更

| 項目 | 変更前 | 変更後 |
|------|--------|--------|
| <param> | <before> | <after> |

## 実験コマンド

```bash
<bench コマンド>
```

---

## 結果

> 実験後に `/record-experiment <filename>` で記入

## 考察

> 実験後に `/conclude-experiment <filename>` で記入
```

4. ファイル作成後、以下を実行する：
   ```
   git add docs/experiments/<filename>.md
   git commit -m "experiment: add plan for <name>"
   git push
   ```

5. 完了後に以下を伝える：
   - 作成したファイルパス
   - 実験実行後のコマンド例：
     ```
     /record-experiment <filename>
     ```
