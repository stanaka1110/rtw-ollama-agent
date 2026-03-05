# ollama_sample — Claude Code ステアリングファイル

## プロジェクト概要

LangChain + Ollama + MCP で動くローカル LLM エージェント。
CPU 推論環境（AMD Ryzen 9 6900HX, GPU なし, WSL2）での動作を前提としている。

エージェントモードは 2 種類:
- **plan_exec** — LLM がステップ計画を立てて逐次実行 + 自動リプラン
- **react** — ReAct ループ（計画フェーズなし、1 フェーズで推論＋ツール呼び出し）

---

## ディレクトリ構成

```
app/
├── main.py              # エントリポイント (argparse + asyncio.run)
├── config.py            # 定数・FEATURES フラグ・チューニング定数
├── web_server.py        # FastAPI Web UI
├── core/
│   ├── llm.py           # Ollama クライアント・モデル別設定 (num_ctx, temperature)
│   ├── models.py        # Step dataclass / parse_steps / format_checklist
│   ├── prompts.py       # プロンプトテンプレート (variant 管理)
│   └── utils.py         # MetricsLogger / setup_logging / ヘルパー
├── agent/
│   ├── executor.py      # Router → plan → exec の接続、AGENT_MODE 分岐
│   ├── exec_loop.py     # Plan-Execute ループ + Input Fixer + Watchdog + メトリクス
│   ├── react_loop.py    # ReAct ループ本体
│   ├── planner.py       # LLM による計画生成・リプラン・状態収集
│   ├── fixers.py        # ツール名/引数名/コンテンツの自動修正ロジック
│   └── loop_helpers.py  # ループ共通ユーティリティ
├── servers/             # MCP サーバー接続設定 (filesystem, shell, websearch, time, sqlite, memory)
└── tests/               # pytest 単体テスト
scripts/
├── bench.sh             # ベンチマーク実行スクリプト
docs/
└── experiments.md       # 実験ログ（時系列）
.claude/
└── commands/            # カスタムスキル (judge, plan-experiment, record-experiment, conclude-experiment)
```

---

## モジュール依存関係

レイヤー順（上が下に依存しない）。

```
[Layer 0] 内部依存なし
  config.py
  core/models.py
  servers/
  agent/fixers.py

[Layer 1] → Layer 0 のみ
  core/prompts.py      → config
  core/llm.py          → config
  core/utils.py        → config, core/models
  agent/loop_helpers.py → config, core/models
  agent/termination.py  → core/utils (遅延import)

[Layer 2] → Layer 0-1
  agent/planner.py     → agent/fixers, config, core/{models,prompts,utils}

[Layer 3] → Layer 0-2
  agent/exec_loop.py   → config, agent/{fixers,loop_helpers}, core/{models,prompts,utils}
  agent/react_loop.py  → config, agent/{fixers,loop_helpers,planner,termination}, core/{prompts,utils}

[Layer 4] エントリポイント直下
  agent/executor.py    → core/llm, agent/{exec_loop,react_loop,planner,fixers},
                         core/{models,prompts,utils}, servers

[Entrypoints]
  main.py / web_server.py → agent/executor
```

### 注意点
- `config.py` はすべてのモジュールの根。循環参照不可
- `agent/termination.py` の `core/utils` 参照は `check()` 内の遅延 import（循環回避）
- `agent/fixers.py` は内部依存ゼロ — 単体テスト・再利用が容易

---

## 設定・フラグ (`app/config.py`)

### 環境変数
| 変数 | 値例 | 説明 |
|------|------|------|
| `OLLAMA_MODEL` | `qwen2.5:7b` | 使用モデル |
| `AGENT_MODE` | `plan_exec` / `react` | エージェントモード |
| `PROMPT_VARIANT` | `default` / `zh` / `react_zh` | プロンプトバリアント |
| `LOG_LEVEL` | `WARNING` / `INFO` / `DEBUG` | ログ詳細度 |
| `TASK_TIER` | `easy` / `medium` / `hard` | ベンチ用ラベル |
| `EXEC_TIMEOUT` | `1200` | 実行ループ全体タイムアウト (秒) |

### FEATURES フラグ（主要なもの）
| フラグ | デフォルト | 効果 |
|--------|-----------|------|
| `agent_mode` | `"plan_exec"` | エージェントモード選択 |
| `tool_result_trimming` | `True` | ツール結果を切り捨てコンテキスト節約 |
| `tool_name_fixer` | `True` | ハルシネーションツール名を自動修正 |
| `arg_fixer` | `True` | 引数名を正規化 |
| `content_fixer` | `True` | write_file の \\n アンエスケープ |
| `watchdog` | `True` | 繰り返し失敗ツールへの警告 |
| `state_skip_optimization` | `True` | 不要な gather_state をスキップ |
| `num_predict_limit` | `False` | フェーズ別生成 token 上限（無効推奨） |
| `message_window` | `True` | スライディングウィンドウ（prefill 節約） |

### スライディングウィンドウ設定
- `MESSAGE_WINDOW_SIZE = 12` — 直近 6 ターン保持（7b/14b 両方に有効）
- `MESSAGE_WINDOW_HEAD = 2` — 先頭 System+Task メッセージは常に保持

### ツール結果トリミング
- `TOOL_RESULT_DEFAULT_MAX_CHARS = 2000`
- ツール別上限は `TOOL_RESULT_MAX_CHARS` dict で設定

---

## 実行方法

### エージェント起動
```bash
./agent "タスクの指示"
```

### コンテナ操作
```bash
docker compose up -d        # 起動
docker compose ps           # 状態確認
docker exec langchain_app python -m pytest tests/ -v  # 単体テスト
```

### ベンチマーク
```bash
# scripts/ ディレクトリから実行
./scripts/bench.sh --tier medium --models qwen2.5:14b --prompt zh --mode react
./scripts/bench.sh --tier quick   # 簡易チェック
```

ベンチ結果は `test_results/bench_YYYYMMDD_HHMMSS/` に保存される。

---

## 実験ワークフロー

カスタムスキルを使って実験を管理する:

```
/plan-experiment   # docs/experiments/ に実験計画ドキュメントを作成
/record-experiment # 実験結果を記録
/conclude-experiment # 考察をまとめ experiments.md を更新
/judge             # タスク完了品質を 0-5 点で評価（judge_report.md に出力）
```

---

## アーキテクチャ上の注意点

### CPU 推論の制約
- prefill: 29 tok/s、generation: 7b=10.9 tok/s / 14b=6.0 tok/s
- コンテキスト肥大が最大のボトルネック（prefill コストが支配的）
- `tool_result_trimming` と `message_window` がこれを緩和する

### モデル別ベスト設定
| モデル | 推奨設定 |
|--------|---------|
| qwen2.5:14b × medium | `AGENT_MODE=react`, `PROMPT_VARIANT=zh`, trim+window |
| qwen2.5:7b  × plan_exec | `PROMPT_VARIANT=zh`, trim+window(12), num_predict なし |

### やってはいけないこと
- `num_predict_limit=True` を exec フェーズに適用 — tool call JSON が途切れ TCA が激減する
- `toolcall_only` ルールを react バリアントに追加 — 終了条件を失い無限ループになる
- `MESSAGE_WINDOW_SIZE < 12` を 7b に適用 — 履歴不足で StepCR が大幅低下する
- `num_ctx=2048` — 両モデルに対して小さすぎる（ループや誤動作が発生）

### MCP ツールの既知問題
- MCPシェルサーバーのコンテナに pytest 未インストール
  → エージェントが `pytest` を実行すると `command not found`
  → `python -m pytest` は app コンテナ側で通る

---

## テスト

```bash
# 単体テスト（appコンテナ内）
docker exec langchain_app python -m pytest tests/ -v

# テスト対象
# test_models.py    — parse_steps / format_checklist
# test_utils.py     — _sanitize / _task_message / _tool_descriptions
# test_planner.py   — gather_current_state / _apply_replan
# test_exec_loop.py — _invoke_tool / _update_step
# test_router.py    — classify_intent
```

---

## メトリクス定義

各セッション終了時に `/app/logs/metrics.jsonl` へ追記される。

| 指標 | 説明 |
|------|------|
| TCA | Tool Calling Accuracy — ターン中にツールを呼んだ割合 |
| ArgFit | 引数修正なしでスキーマ一致した割合 |
| StepCR | Step Completion Rate — 全ステップ中に完了できた割合 |
