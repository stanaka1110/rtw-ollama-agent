# 実験ログ — ollama_sample エージェント改善記録

CPU 推論環境（AMD Ryzen 9 6900HX, GPU なし）での qwen2.5 エージェントの品質・速度改善記録。

---

## 環境

| 項目 | 値 |
|------|----|
| CPU | AMD Ryzen 9 6900HX |
| GPU | なし（CPU 推論のみ） |
| 推論速度 | prefill 29 tok/s / generation 7b: 10.9 tok/s, 14b: 6.0 tok/s |
| OS | WSL2 + Docker |
| モデル | qwen2.5:7b, qwen2.5:14b |
| ベンチタスク | medium tier 3問（SQLite+Python, Web検索+ファイル, スクリプト作成+レビュー） |

---

## 実験① ベースライン測定（2026-03-03）

### 設定
- `num_ctx=4096`（デフォルト）
- `tool_result_trimming=False`
- タスク: hard tier 3問

### 結果
| モデル | TCA | StepCR | 平均時間 | TIMEOUT(1200s)内完了 |
|--------|-----|--------|---------|-------------------|
| 7b | 0.622 | 58.3% | ~837s | 1/3 |
| 14b | 0.917 | 68.9% | ~1398s | 0/3 |

### 考察
- 14b は全タスクタイムアウト。turn あたり 34〜505s の激しいばらつき
- 14b の "stuck" ターン（505s/turn）は tool call をせずに ~3000 token の長文生成が原因
- **主因は prefill コスト**: コンテキスト 3000 token → prefill 103s + gen 60s ≈ 163s/turn

---

## 実験② num_ctx=2048 試験（2026-03-03）

### 設定
- `num_ctx=2048`（縮小）

### 結果
| モデル | TCA | StepCR | 平均時間 | 問題 |
|--------|-----|--------|---------|------|
| 7b | 1.000 (ループ) | 100% (ループ) | — | コンテキスト溢れで同ツール繰り返し |
| 14b | 0.500 | 56.2% | — | 計画全体参照不可で誤動作 |

### 考察
- 2048 は両モデルに小さすぎる
- 7b: fetch_page 1 回で 300〜800 token 消費 → 3〜4 ターンで満杯 → ループ
- 14b: TCA 0.917 → 0.500 に激減（計画全体が消えて誤動作）
- **結論**: num_ctx 削減ではなく、ツール結果そのものをトリミングするべき

---

## 実験③ tool_result_trimming 追加（2026-03-03）

### 実装
- fetch_page の結果を 8331 chars → 1536 chars（▲82%）に切り捨て
- TOOL_RESULT_MAX_CHARS でツール別上限を設定

### 結果
| モデル | TCA | StepCR |
|--------|-----|--------|
| 7b | 0.785 | 63.9% |
| 14b | 0.933 | 63.5% |

### 考察
- 14b の stuck が 505s → 315s に改善
- ベースラインより両モデルとも TCA 向上
- **最も効果的な単一改善**: コンテキスト肥大の根本対策

---

## 実験④ num_predict_limit（exec=512）（2026-03-03/04）

### 設定
- `num_predict_limit=True`, exec フェーズ上限 512 tokens

### 結果
| モデル | TCA | StepCR | 速度変化 |
|--------|-----|--------|---------|
| 7b | 0.600 | 71.4% | task2/3: 1300s → 277/269s（大幅短縮） |
| 14b | 0.695 | 55.5% | — |

### 考察
- TCA が大幅低下（14b: 0.933→0.695, 7b: 0.785→0.600）
- モデルがツールコール JSON 出力前に 512 token を使い切って途切れるケースが増加
- 速度は改善するが品質の犠牲が大きい
- **結論**: 512 は厳しすぎ。768 で再試験の余地あり

---

## 実験⑤ スライディングウィンドウ window=8（2026-03-04）

### 設定
- `message_window=True`, `MESSAGE_WINDOW_SIZE=8`（直近 4 ターン保持）

### 結果
| モデル | TCA | StepCR |
|--------|-----|--------|
| 7b | 0.822 | 47.5% |
| 14b | 0.917 | 67.5% |

### 考察
- 14b: TCA 維持、stuck なし → **14b には有効**
- 7b: StepCR 63.9% → 47.5% に低下 → 小モデルは会話履歴への依存度が高い
- window=8 は 7b に小さすぎ。window=12 が次の候補

---

## 実験⑥ スライディングウィンドウ window=12（2026-03-04）
**結果ディレクトリ**: `compare_20260304_192920`

### 設定
- `MESSAGE_WINDOW_SIZE=12`（直近 6 ターン保持）

### 結果
| モデル | TCA | StepCR | 平均時間 |
|--------|-----|--------|---------|
| 7b | 0.742 | 90.5% | ~637s |
| 14b | 0.944 | 50.4% | ~1399s |

### 考察
- 7b: StepCR 47.5% → **90.5%**（大幅改善）、window=12 で履歴が保持されタスク継続性向上
- 14b: TCA 最高値（0.944）だが StepCR が低下
  - 後に判明: **arg_fixer のバグ**（MCP ツールの args_schema が dict 形式に未対応）が原因
  - write_file に `file_path` が渡り続けて繰り返し失敗 → タイムアウト

---

## 実験⑦ num_predict exec=768 + window=12（2026-03-04）
**結果ディレクトリ**: `compare_20260304_214041`

### 設定
- `num_predict_limit=True`, exec=768 tokens, `MESSAGE_WINDOW_SIZE=12`

### 結果
| モデル | TCA | StepCR | 平均時間 |
|--------|-----|--------|---------|
| 7b | 0.489 | 46.2% | ~737s |
| 14b | 0.783 | 35.0% | ~1405s |

### 考察
- exec=512 より緩くしたが依然 TCA が大幅低下
- モデルがツールコール JSON 前に 768 token の説明文を生成して途切れるケースが多い
- **結論**: exec フェーズの num_predict 制限は根本的に不適。router フェーズ（32 token）のみ有効

---

## 実験⑧ arg_fixer バグ修正後の確認（2026-03-05）
**結果ディレクトリ**: `compare_20260305_010816`

### バグ内容
MCP ツールの `args_schema` が Pydantic モデルでなく JSON Schema dict 形式の場合、`model_fields` アクセスで AttributeError が発生し修正がスキップされていた。

```python
# 修正前（Pydantic のみ対応）
expected_keys = set(schema.model_fields.keys())

# 修正後（dict / Pydantic 両対応）
if isinstance(schema, dict):
    expected_keys = set(schema.get("properties", {}).keys())
elif hasattr(schema, "model_fields"):
    expected_keys = set(schema.model_fields.keys())
```

### 結果（7b, medium tier）
| モデル | TCA | StepCR | 平均時間 |
|--------|-----|--------|---------|
| 7b | 0.688 | 69.3% | ~637s |

---

## 実験⑨ medium tier ベンチ確立（7b, zh prompt）（2026-03-05）
**結果ディレクトリ**: `bench_20260305_101829`, `bench_20260305_123241`

### 設定
- `PROMPT_VARIANT=zh`（中国語命令文 → 日本語出力）
- `message_window=True, size=12`, `tool_result_trimming=True`
- モード: plan_exec

### 結果（2回の平均）
| 試行 | TCA | StepCR | ErrRate | AvgSec |
|------|-----|--------|---------|--------|
| 1回目 (101829) | 0.802 | 100.0% | 0.278 | 724s |
| 2回目 (123241) | 0.671 | 83.3% | 0.150 | 766s |

### 考察
- zh バリアントで 7b の安定性が向上（命令追従性の改善）
- 1回目は StepCR 100%（全ステップ完了）を達成
- ErrRate が高め（15〜28%）→ ツールエラーが多いが replan で回復

---

## 実験⑩ medium tier ベンチ（14b, zh prompt, plan_exec）（2026-03-05）
**結果ディレクトリ**: `bench_20260305_153708`

### 結果
| TCA | StepCR | ErrRate | Replans | AvgSec |
|-----|--------|---------|---------|--------|
| 0.944 | 59.3% | 0.289 | 1.0 | 1001s |

### 考察
- TCA は高いが全タスクで replan が発生し時間がかかる
- タスク1(1442s), タスク2(1351s) はタイムアウト超え、タスク3(780s)のみ完了
- plan → exec → replan の LLM 呼び出し積み重ねがボトルネック

---

## 実験⑪ ReAct モード実装 + react vs plan_exec 比較（2026-03-05）
**結果ディレクトリ**: `bench_20260305_193001`（react）, `bench_20260305_204518`（plan_exec）

### 背景
Plan-and-Execute は make_plan()（+180s）+ replan（+160s）の LLM 呼び出しがオーバーヘッドになり、14b × CPU では全タスクがタイムアウト。計画フェーズを省く ReAct ループを実装。

### 実装
- `app/agent/react_loop.py` 新規作成
- `AGENT_MODE=react` 環境変数で切替
- `app/core/prompts.py` に `react` / `react_zh` バリアント追加（`follow_plan` ルール除外）

### 結果（14b, medium 3問, zh）
| 指標 | **react** | plan_exec |
|------|----------:|----------:|
| タスク完了 | **3/3 ✅** | 0/3 ❌（全 timeout） |
| AvgSec | **404s** | 1241s（3.1倍遅い） |
| TCA | 0.472 | 0.583 |
| ErrRate | **0.000** | 0.178 |
| Replans | **0** | 1.0 |

| タスク | react | plan_exec |
|--------|------:|----------:|
| SQLite + Python レポート | 282s ✅ | 1428s ❌ |
| Web 検索 → ファイル保存 | 553s ✅ | 1734s ❌ |
| スクリプト作成 → レビュー | 440s ✅ | 1529s ❌ |

### Judge スコア（react, bench_20260305_193001）
| タスク | スコア | 主な問題 |
|--------|-------:|---------|
| SQLite + Python レポート | 0/5 | tool call を1回も出さず「これからやる」で終了 |
| Web 検索 → asyncio_notes.txt | 5/5 | 完全に正しく完了 |
| primes.py 作成・実行・レビュー | 2/5 | primes.py 作成・実行は完了、review.txt 未作成 |
| **合計** | **7/15** | — |

### 考察
- react モードは plan_exec の **3倍速**、全タスク完走
- TCA=0.472 が低い → 「やると言って終わる」パターンが品質のボトルネック
- plan_exec は make_plan + replan でコンテキスト肥大 → stuck → timeout

---

## 実験⑫ react + toolcall_only_zh（TCA 改善試み）（2026-03-06）
**結果ディレクトリ**: `bench_20260305_222534`

### 仮説
`toolcall_only_zh` ルールを追加し「tool call だけ出力せよ」と強制することで TCA を改善できる。

### 結果（14b, medium 3問, zh）
| 指標 | react+toolcall | react（前実験） |
|------|---------------:|---------------:|
| TCA | **0.944** | 0.472 |
| AvgSec | 994s | **404s** |
| タスク完了 | 1/3 ❌ | **3/3 ✅** |

### 考察
- TCA は 0.472 → 0.944 に大幅改善
- しかし**モデルが終了条件を失い無限ループ**に陥る
  - plan_exec では「全ステップ完了→終了」のゴール条件がある
  - react では「tool call 不要になったらテキスト回答」という自己判断が必要
  - `toolcall_only` はそのテキスト出力を禁じるため終われなくなる
- **結論**: `toolcall_only` は react と非互換。リバート済み

---

## 全実験 総括

### plan_exec モード（hard tier 3問, EXEC_TIMEOUT=1200s）
| 設定 | 14b TCA | 14b StepCR | 7b TCA | 7b StepCR |
|------|---------|-----------|--------|-----------|
| base (num_ctx=4096) | 0.917 | 68.9% | 0.622 | 58.3% |
| num_ctx=2048 | 0.500 | 56.2% | 1.000(ループ) | 100%(ループ) |
| +trim | **0.933** | 63.5% | 0.785 | 63.9% |
| +trim+predict(512) | 0.695 | 55.5% | 0.600 | 71.4% |
| +trim+window(8) | 0.917 | **67.5%** | 0.822 | 47.5% |
| +trim+window(12) | **0.944** | 50.4%※ | 0.742 | **90.5%** |
| +trim+window(12)+predict(768) | 0.783 | 35.0% | 0.489 | 46.2% |

※ arg_fixer バグ（修正済み）の影響で StepCR が低下していた可能性あり

### react vs plan_exec（medium tier, 14b, zh, EXEC_TIMEOUT=1200s）
| 指標 | react | plan_exec |
|------|------:|----------:|
| タスク完了 | **3/3** | 0/3 |
| AvgSec | **404s** | 1241s |
| TCA | 0.472 | 0.583 |
| Judge スコア | 7/15 | 測定不可（空回答） |

---

## 現在のベスト設定

| 対象 | 設定 |
|------|------|
| 14b × medium タスク | `AGENT_MODE=react`, `PROMPT_VARIANT=zh`, `tool_result_trimming=True`, `message_window=True` |
| 14b × plan_exec（参考） | `trim=True`, `window=True, size=12`, `num_predict_limit=False` |
| 7b × plan_exec | `trim=True`, `window=True, size=12`, `num_predict_limit=False` |

---

## 今後の改善候補

| 優先度 | 課題 | アイデア |
|--------|------|---------|
| 高 | react TCA=0.472（tool call を出さず終了） | プロンプトで「答えが出るまでツールを使い続けろ」を強化。`toolcall_only` 以外の手法 |
| 高 | Judge スコアの自動化 | `/judge` スキルを bench.sh に統合 |
| 中 | window=12 後の 14b StepCR 低下 | arg_fixer バグ修正後の再試験 |
| 低 | GPU 化 | ROCm/CUDA 対応で根本的な速度改善 |
