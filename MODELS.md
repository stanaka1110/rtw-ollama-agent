# モデル比較レポート

このプロジェクトで動作確認したOllamaモデルの比較。

---

## 検証環境

- GPU: NVIDIA（580.126.09 ドライバー）
- Docker + NVIDIA Container Toolkit
- Ollama / LangChain-Ollama / langchain-mcp-adapters

---

## テスト結果サマリー

| モデル | サイズ | Tool calling | 時刻取得 | Python実行 | 速度 |
|---|---|---|---|---|---|
| **qwen2.5:7b** | 4.7 GB | ✅ | ✅ 6秒 | ✅ 6秒 | ⭐ 最速 |
| qwen2.5:14b | 9.0 GB | ✅ | ✅ 5秒 | ❌ 67秒 | 遅い（失敗） |
| mistral:7b | 4.4 GB | ❌ | ❌ 26秒 | ❌ 46秒 | 遅い（失敗） |
| llama3.2:3b | 2.0 GB | ✅ | ✅ 10秒 | ❌ 60秒 | 普通（失敗） |
| llama3.1:8b | 4.9 GB | ✅ | ✅ 〜10秒 | ⚠️ 不安定 | 普通 |
| qwen2.5-coder:14b-instruct | 9.0 GB | ❌ | ❌ | ❌ | CPU:114秒 |

---

## 各モデルの詳細

### ✅ qwen2.5:7b（推奨）

このプロジェクトの元設計モデル。全テストで最も安定した動作。

```
タスク: 現在時刻を教えて
→ 現在の時刻は2026年02月26日 15:34:53 (JST)です。（6秒）

タスク: 1から5の2乗をPythonで計算
→ 1 / 4 / 9 / 16 / 25（6秒、正常実行）
```

- Tool calling: ✅ 正常
- 引数名の一貫性: ✅ `command` / `shell` / `cwd` を正しく使用
- 文字列リテラルのエスケープ: ✅ 問題なし
- プラン生成: ✅ ステップ番号が正しく生成される

---

### ⚠️ qwen2.5:14b

時刻取得は動作するが、Pythonスクリプト生成・実行タスクで失敗。

```
タスク: 現在時刻を教えて → ✅ 5秒
タスク: Python実行 → ❌ 67秒（エスケープ問題でスクリプト破損、ループ）
```

- Tool calling: ✅
- Python文字列生成: ❌ `\` が混入しスクリプトが壊れる
- 14Bの割に速度メリットが出ない（失敗するため長時間かかる）

---

### ❌ mistral:7b

Tool callingが機能しない。ツールを実際に呼ばず、呼ぶべき関数名をテキストで説明するだけ。

```
タスク: 現在時刻を教えて
→ "get_current_datetime() を実行します"（テキスト説明のみ）
```

- Tool calling: ❌（LangChainのbind_toolsが機能しない）
- 英語で応答する傾向あり（日本語指示を無視）
- このプロジェクトでは使用不可

---

### ⚠️ llama3.2:3b

時刻取得は動作するが、複数ステップタスクは失敗。軽量なため単純タスク専用。

```
タスク: 現在時刻を教えて → ✅ 10秒
タスク: Python実行 → ❌ 60秒（空の結果）
```

- Tool calling: ✅（単純な1ステップタスクのみ）
- 複数ステップのプランニング: ❌ 能力不足
- メモリ節約が最優先な場合のみ検討

---

### ⚠️ llama3.1:8b

Tool callingは機能するが、複雑タスクで不安定。

- Python文字列の `"` がJSONと干渉して切れる（`print(` → 不完全）
- `execute_command` の引数名が `cmd` / `command` で揺れる
- プランのステップ番号が重複することがある

---

### ❌ qwen2.5-coder:14b-instruct

Tool callingが根本的に機能しない。

- `response.tool_calls` が常に空
- ツール呼び出しをプレーンテキストのJSONとして出力してしまう
- CPU動作時: 1回のLLM呼び出しに58〜114秒

---

## 失敗パターンの考察

モデルの失敗を「原因の種類」で分類すると、プロンプト調整で改善できるものとできないものに分かれる。

### パターン1: Tool calling APIレベルの非互換（プロンプトで解決不可）

`mistral:7b` と `qwen2.5-coder:14b-instruct` はツールを実際に呼ばず、テキストで関数名を書くだけになる。

```
# mistral:7b の実際の出力
"get_current_datetime() を実行します"  ← 説明文としてのテキスト
```

これは Ollama 上の tool calling 実装と langchain-ollama の `bind_tools()` との根本的な非互換であり、プロンプトを変えても `response.tool_calls` が空のままになる。

### パターン2: ツール引数の生成が壊れる（プロンプトで改善余地あり）

`llama3.1:8b` は `execute_command` に渡すパラメータ名が `cmd` になることがある（正: `command`）。SYSTEM_PROMPT に具体例を追加すれば改善できる可能性がある。

```python
# 現在の SYSTEM_PROMPT
- shell (execute_command): use cwd=/workspace or cwd=/data, shell=bash.

# 強化案（引数名と例を明示）
- shell (execute_command): required args are command (str), shell='bash', cwd (str).
  Example: execute_command(command="python3 /data/x.py", shell="bash", cwd="/workspace")
```

`qwen2.5:14b` の `\` 混入（Pythonコードにバックスラッシュが混入してSyntaxError）は、モデルがJSONシリアライズ時に二重エスケープを起こすモデル固有の挙動で、`"シングルクォートを使え"` などの指示で部分的に回避できるが根本解決にはならない。

### パターン3: プランニング能力の限界（モデルサイズの問題）

`llama3.2:3b` は1ステップのタスクは動くが複数ステップで崩れる。システムプロンプト・ツール一覧・現在状態・タスクを同時に処理しながら構造化プランを生成するには3Bパラメータでは能力が足りない。これはプロンプトでは補えない。

---

### なぜ qwen2.5:7b だけが完璧に動くのか

| 要素 | 詳細 |
|---|---|
| Tool calling 実装 | Qwen2.5 の Ollama 実装が langchain-ollama の `bind_tools()` と相性が良い |
| 日本語対応 | Alibaba 製モデルは日本語・中国語で大量学習済みで、日本語指示に忠実 |
| 引数の厳密さ | `command` / `shell` / `cwd` を SYSTEM_PROMPT の通りに正しく使う |
| プラン形式の再現 | `1. tool_name: ...` というプロジェクト固有のフォーマットを正確に踏襲する |
| サイズと速度のバランス | 7B は推論精度・速度・VRAM 消費のトレードオフが最適 |

**主因は「プロンプト」ではなく「モデルと Ollama の tool calling 実装の相性」。** ただし `llama3.1:8b` の引数名問題など、プロンプト強化で改善できる部分も存在する。他モデルで同等の動作を得るためにはプロンプトのかなりの調整が必要になり、プロジェクトのプロンプトが Qwen2.5 の挙動に最適化されていることが大きい。

---

## 結論・推奨

**`qwen2.5:7b` を使用すること。**

- プロジェクトの元設計モデルであり、プロンプトとの相性が最良
- 4.7GBと軽量ながら全テストで最速・最安定
- Tool calling / プラン生成 / Python実行すべて正常動作

```yaml
# docker-compose.yml
OLLAMA_MODEL=qwen2.5:7b
```