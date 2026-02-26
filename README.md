# rtw-ollama-agent

LangChain + Ollama + MCP で動くローカル Plan-and-Execute エージェント。

「Reinventing The Wheel」の名の通り、既存のエージェントフレームワークをなるべく使わず、計画・実行・リプランのループを自前で実装しています。

---

## 特徴

- **完全ローカル実行** — Ollama によりモデルをローカルで動かします（デフォルト: `qwen2.5:7b`）
- **Plan-and-Execute** — LLM がタスクを番号付きステップに分解してから逐次実行します
- **自動リプラン** — ステップ失敗時や未完了ステップが残った場合に、完了済みを引き継ぎながら計画を立て直します
- **MCP ツール** — 6種のツールサーバーをコンテナで起動します
- **モジュール構造** — 責務ごとにファイルを分割し、純粋関数を中心に単体テストを整備しています

---

## アーキテクチャ

```
┌─────────────────────────────────────────────────────────┐
│ executor.py          run()                              │
│   ├── plan_runner.py  run_plan_phase()                  │
│   │     └── planner.py  make_plan() / gather_state()   │
│   └── exec_loop.py   run_exec_loop()                   │
│         ├── _invoke_tool()                              │
│         ├── _update_step()                              │
│         └── planner.py  _apply_replan()                 │
└─────────────────────────────────────────────────────────┘
```

### ファイル構成

```
app/
├── main.py          # エントリポイント (argparse + asyncio.run)
├── executor.py      # MCP セットアップ → plan → exec の接続
├── plan_runner.py   # 計画フェーズ
├── exec_loop.py     # 実行ループ + ツール呼び出し + ステップ更新
├── planner.py       # LLM による計画生成・リプラン生成
├── models.py        # Step dataclass / parse_steps / format_checklist
├── utils.py         # _sanitize / _task_message / setup_logging
├── config.py        # 定数 + プロンプトテンプレート
├── llm.py           # Ollama クライアント
├── servers/         # MCP サーバー設定
└── tests/           # 単体テスト (pytest)
```

---

## MCP ツール

| ツール | 用途 |
|---|---|
| filesystem | ファイル読み書き (`/data/` 以下) |
| shell | コマンド実行 (`/workspace`, `/data`) |
| websearch | Web 検索 + ページ取得 |
| time | 現在日時の取得 (JST) |
| sqlite | SQLite DB 操作 (`/data/agent.db`) |
| memory | キーバリュー形式のメモ永続化 |

---

## セットアップ

**前提:** Docker / Docker Compose がインストールされていること

```bash
git clone https://github.com/stanaka1110/rtw-ollama-agent.git
cd rtw-ollama-agent

# コンテナをビルド・起動 (初回は Ollama モデルのダウンロードに時間がかかります)
docker compose up -d
```

`ollama` サービスの `healthcheck` が通ればエージェントを使えます。

```bash
# ステータス確認
docker compose ps
```

---

## 使い方

プロジェクトルートの `agent` スクリプト経由で実行します。

```bash
# 実行権限を付与 (初回のみ)
chmod +x agent

# 実行例
./agent "ToDoリストに「買い物」を追加して"
./agent "現在時刻を教えて"
./agent "hello world を出力する Python を書いて実行して"
./agent "agent.db に users テーブルを作って3件のサンプルデータを挿入して"
```

---

## テスト

```bash
docker exec langchain_app python -m pytest tests/ -v
```

| テストファイル | 対象 |
|---|---|
| `test_models.py` | `parse_steps` / `format_checklist` |
| `test_utils.py` | `_sanitize` / `_task_message` / `_tool_descriptions` |
| `test_planner.py` | `gather_current_state` / `_apply_replan` |
| `test_exec_loop.py` | `_invoke_tool` / `_update_step` |

---

## モデルの変更

`docker-compose.yml` の環境変数を変更します。

```yaml
environment:
  - OLLAMA_MODEL=llama3.2:3b  # 任意の Ollama モデル
```

変更後は `docker compose up -d` で再起動します。
