# ── Sentence fragments ──────────────────────────────────────────────────────
# Atomic prompt sentences reused across prompt types and variants.
# Each value is a single self-contained instruction.

SENTENCES: dict[str, str] = {
    # Language
    "lang_jp":          "[CRITICAL] You MUST respond ONLY in Japanese. NEVER output Chinese characters.",
    "lang_plan":        "[LANGUAGE: OUTPUT IN JAPANESE ONLY. DO NOT USE CHINESE OR ENGLISH IN YOUR OUTPUT.]",

    # Exec-loop behavior
    "use_tools":        "Always use tools — never just describe what you would do.",
    "one_at_a_time":    "Call ONE tool at a time and wait for the result before calling the next.",
    "follow_plan":      "Follow the execution plan step by step until all steps are complete.",
    "toolcall_only":    "[CRITICAL] When calling a tool, output ONLY the <tool_call> JSON block. Do NOT write any text before or after the tool call.",
    "arg_names":        'IMPORTANT: Use EXACTLY these argument names. Do NOT use "cmd", "dir", "filepath", "text", or any other variant.',

    # Planner
    "plan_format":      "For each step, write: <number>. <tool_name>: <具体的な内容>\nBe specific about arguments. Do NOT execute — only plan.",
    "plan_use_state":   "Use the current state information to make informed decisions (e.g. don't create a table that already exists).",

    # Replanner
    "replan_task":      "The execution encountered failures. Review the checklist below and create a REVISED plan for the REMAINING steps only.",
    "replan_no_done":   "Do NOT re-include already completed (✅) steps under any circumstances.",
    "replan_fix":       "Fix the approach for failed (❌) steps based on the error details.",
    "replan_alt":       "If a tool failed repeatedly, choose a DIFFERENT tool or method.",
}

# ── Fixed blocks (tool list and examples) ───────────────────────────────────

_TOOL_LIST = """\
You are a helpful AI assistant with the following tools:
- filesystem (read_file, write_file, etc.): paths must start with /data/
- shell (execute_command): use cwd=/workspace or cwd=/data, shell=bash.
  To run a Python file, use: python3 /data/<filename> (never ./filename)
- websearch (web_search, fetch_page): search the internet.
  After web_search, call fetch_page on the best URL to get actual content.
- time (get_current_datetime): get the current date/time in JST.
- sqlite (list_tables, query): SQLite DB at /data/agent.db for structured data.
- memory (remember, recall, list_memories, forget): persist key-value notes."""

_TOOL_EXAMPLES = """\
## Tool call examples (correct argument names)

Example 1 — Run a shell command:
<tool_call>
{"name": "execute_command", "arguments": {"command": "python3 /data/test.py", "cwd": "/data", "shell": "bash"}}
</tool_call>

Example 2 — Write a file:
<tool_call>
{"name": "write_file", "arguments": {"path": "/data/hello.py", "content": "print('hello')"}}
</tool_call>"""

# ── System prompt variant definitions ───────────────────────────────────────
# "rules":    ordered SENTENCES keys → assembled into numbered Rules: block
# "examples": bool → include _TOOL_EXAMPLES
# "footer":   SENTENCES keys appended after examples (unnumbered)

_SYSTEM_VARIANTS: dict[str, dict] = {
    # Baseline: current behaviour
    "default": {
        "rules":    ["lang_jp", "use_tools", "one_at_a_time", "follow_plan"],
        "examples": True,
        "footer":   ["arg_names"],
    },
    # v1: add explicit "output ONLY <tool_call>" rule, drop examples
    "v1": {
        "rules":    ["lang_jp", "toolcall_only", "use_tools", "one_at_a_time", "follow_plan"],
        "examples": False,
        "footer":   ["arg_names"],
    },
    # v2: strict toolcall + keep examples for argument-name guidance
    "v2": {
        "rules":    ["lang_jp", "toolcall_only", "use_tools", "one_at_a_time", "follow_plan"],
        "examples": True,
        "footer":   ["arg_names"],
    },
}


def build_system_prompt(variant: str = "default") -> str:
    cfg = _SYSTEM_VARIANTS.get(variant, _SYSTEM_VARIANTS["default"])
    parts = [_TOOL_LIST, "Rules:"]
    for i, key in enumerate(cfg["rules"], 1):
        parts.append(f"{i}. {SENTENCES[key]}")
    if cfg.get("examples"):
        parts.append(_TOOL_EXAMPLES)
    for key in cfg.get("footer", []):
        parts.append(SENTENCES[key])
    return "\n".join(parts)


def build_plan_prompt(variant: str = "default") -> str:  # noqa: ARG001 (variant reserved)
    s = SENTENCES
    return (
        s["lang_plan"] + "\n\n"
        "You are a task planner. Given a user request, the current system state, "
        "and available tools, output a concrete numbered execution plan.\n"
        + s["plan_format"] + "\n"
        + s["plan_use_state"] + "\n\n"
        "Current system state:\n{current_state}\n\n"
        "Available tools:\n{tool_descriptions}"
    )


def build_replan_prompt(variant: str = "default") -> str:  # noqa: ARG001
    s = SENTENCES
    rules = [s["replan_no_done"], s["replan_fix"], s["replan_alt"]]
    return (
        s["lang_plan"] + "\n\n"
        "You are a task planner. " + s["replan_task"] + "\n"
        "ABSOLUTE RULES:\n"
        + "\n".join(f"- {r}" for r in rules) + "\n\n"
        "Available tools:\n{tool_descriptions}"
    )


# ── Router / Chat (no variants needed) ──────────────────────────────────────

ROUTER_PROMPT = """\
You are an input classifier. Decide if the user's message needs tool use.

CHAT — no tools needed: greetings, casual conversation, thanks, opinions,
follow-up questions about a previous answer.
  Examples: "こんにちは", "ありがとう", "それはどういう意味？", "元気ですか"

AGENT — tool use required: search, file operations, calculations, data
retrieval, code writing, date/time lookup, or any action-oriented request.
  Examples: "天気を調べて", "ファイルを作成して", "今日の日付は？", "〇〇を検索して"

Reply with exactly one word: CHAT or AGENT"""

# Chat path only. No tools are bound here — tool instructions cause
# hallucinated tool calls on instruction-following models like mistral.
CHAT_PROMPT = """\
You are a friendly and helpful AI assistant.
[CRITICAL] You MUST respond ONLY in Japanese. NEVER output Chinese characters."""

# ── Module-level exports (backward-compatible) ───────────────────────────────
# Built at import time from PROMPT_VARIANT in config.
# All existing `from core.prompts import SYSTEM_PROMPT` calls continue to work.

from config import PROMPT_VARIANT as _VARIANT  # noqa: E402

SYSTEM_PROMPT = build_system_prompt(_VARIANT)
PLAN_PROMPT   = build_plan_prompt(_VARIANT)
REPLAN_PROMPT = build_replan_prompt(_VARIANT)
