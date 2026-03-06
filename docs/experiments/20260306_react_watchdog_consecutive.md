# 実験: react_watchdog_consecutive

**日時**: 2026-03-06
**ステータス**: 計画中

---

## 目的

react_loop には exec_loop の watchdog（連続エラー検出 + アプローチ変更誘導）が存在しない。
Task1 (SQLite+Python) で同じ SyntaxError が Turn2・4・5 と3回繰り返されたように、
react モードでは同一エラーが発生し続けても何も介入しない。

`REACT_WATCHDOG=consecutive` で有効になる factory 実装を追加し、
N 回連続エラー時にフィードバックを注入することで SyntaxError ループを脱出させ、
Judge スコアを改善する。

## 仮説

連続エラー検出（consecutive）watchdog を react_loop に追加することで：
- Task1 の SyntaxError ループが中断され、モデルが別アプローチを試みる
- Judge スコア: 5/15（実験⑮）→ 8/15 以上を期待
- TCA は維持（0.8 以上）、AvgSec は text ベースライン（404s）に近づく

根拠：
- Task1 失敗の直接原因は「同じ SyntaxError → 同じ修正試み → 同じ失敗」の繰り返し
- watchdog フィードバックで「別のアプローチ」を促せば計算ロジックを SQL に切り替える等の回避が期待できる
- exec_loop では同様の仕組みが replan トリガーとして機能している

## 設定変更

| 項目 | 変更前 | 変更後 |
|------|--------|--------|
| `REACT_WATCHDOG` env var | なし（未実装） | `"consecutive"`（有効）|
| `app/agent/base/watchdog.py` | 存在しない | 新規作成（ReactWatchdog ABC + factory） |
| `app/config.py` | REACT_WATCHDOG なし | `REACT_WATCHDOG = os.environ.get(...)` 追加 |
| `app/agent/loops/react_loop.py` | watchdog なし | 連続エラー追跡 + フィードバック注入 |
| `scripts/bench.sh` | `--react-watchdog` フラグなし | 追加 |

### 実装設計

```
app/agent/base/watchdog.py
  ReactWatchdog(ABC)
    .check(consecutive_errors: int, last_result: str) -> str | None

  NoopWatchdog       ← REACT_WATCHDOG=none (デフォルト・既存挙動)
  ConsecutiveErrorWatchdog(threshold=2)
                     ← REACT_WATCHDOG=consecutive (実験A)

  get_react_watchdog(name: str) -> ReactWatchdog  ← factory
```

react_loop の変更点：
- `consecutive_errors` カウンタを追加
- ツール実行後 `is_error=True` なら +1、成功なら 0 リセット
- `watchdog.check()` が文字列を返したら `HumanMessage` としてメッセージに追加

## 実験コマンド

```bash
REACT_WATCHDOG=consecutive \
  ./scripts/bench.sh --tier medium --models qwen2.5:14b --prompt zh --mode react
```

比較ベースライン（watchdog なし、実験⑮相当）:
```bash
./scripts/bench.sh --tier medium --models qwen2.5:14b --prompt zh --mode react
```

---

## 結果

> 実験後に `/record-experiment 20260306_react_watchdog_consecutive` で記入

## 考察

> 実験後に `/conclude-experiment 20260306_react_watchdog_consecutive` で記入
