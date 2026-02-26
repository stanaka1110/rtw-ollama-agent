import difflib
import time
from collections import defaultdict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import ToolException

from config import MAX_FAILURES_BEFORE_REPLAN, MAX_REPLANS, MAX_STEPS
from prompts import SYSTEM_PROMPT
from models import Step, format_checklist
from planner import _apply_replan
from utils import MetricsLogger, _sanitize, _task_message

# Mapping of commonly hallucinated tool names → correct MCP tool names.
# Observed across llama3.2:3b, mistral and other small open-weight models.
_TOOL_NAME_ALIAS: dict[str, str] = {
    # filesystem
    "read_text_file":           "read_file",
    "read_file_content":        "read_file",
    "write_text_file":          "write_file",
    "create_file":              "write_file",
    "save_file":                "write_file",
    "list_files":               "list_directory",
    "list_directory_with_sizes": "list_directory",
    "ls":                       "list_directory",
    "delete_file":              "remove_file",
    # shell
    "run_command":              "execute_command",
    "run_shell":                "execute_command",
    "shell_execute":            "execute_command",
    "bash":                     "execute_command",
    "exec":                     "execute_command",
    "run_bash":                 "execute_command",
    # websearch
    "search_web":               "web_search",
    "internet_search":          "web_search",
    "get_page":                 "fetch_page",
    "fetch_url":                "fetch_page",
    "open_url":                 "fetch_page",
    # time
    "current_time":             "get_current_datetime",
    "get_time":                 "get_current_datetime",
    "get_datetime":             "get_current_datetime",
    "now":                      "get_current_datetime",
    # sqlite
    "sql_query":                "query",
    "execute_sql":              "query",
    "run_sql":                  "query",
    # memory
    "store_memory":             "remember",
    "save_memory":              "remember",
    "get_memory":               "recall",
    "retrieve_memory":          "recall",
    "delete_memory":            "forget",
    "remove_memory":            "forget",
}

# Minimum similarity ratio accepted by difflib fuzzy fallback.
# 0.80 is intentionally conservative to avoid mis-corrections.
_FUZZY_CUTOFF = 0.80


def _fix_tool_name(tc: dict, tool_map: dict) -> tuple[dict, str | None]:
    """Try to correct a hallucinated tool name before invocation.

    Correction strategy (in order):
    1. Exact match in tool_map  → no change needed.
    2. Alias table lookup       → deterministic, high-confidence correction.
    3. difflib fuzzy match      → catches variations not in the alias table.

    Returns (fixed_tc, fix_description) where fix_description is None when
    no correction was applied.  Uses '→' for alias fixes and '~>' for fuzzy
    fixes so they are distinguishable in logs and metrics.
    """
    name = tc["name"]
    if name in tool_map:
        return tc, None

    # Strategy 1: alias table
    if name in _TOOL_NAME_ALIAS:
        corrected = _TOOL_NAME_ALIAS[name]
        if corrected in tool_map:
            return {**tc, "name": corrected}, f"{name} → {corrected}"

    # Strategy 2: difflib fuzzy match (conservative cutoff)
    candidates = difflib.get_close_matches(name, tool_map.keys(), n=1, cutoff=_FUZZY_CUTOFF)
    if candidates:
        corrected = candidates[0]
        return {**tc, "name": corrected}, f"{name} ~> {corrected}"

    return tc, None


# Mapping of commonly hallucinated argument names → correct schema names.
# These are patterns observed across llama3, mistral and other open-weight models.
_ARG_ALIAS: dict[str, str] = {
    "cmd":          "command",
    "shell_cmd":    "command",
    "sh":           "shell",
    "dir":          "cwd",
    "working_dir":  "cwd",
    "workdir":      "cwd",
    "file":         "path",
    "filepath":     "path",
    "filename":     "path",
    "file_path":    "path",
    "text":         "content",
    "body":         "content",
    "data":         "content",
    "q":            "query",
    "search":       "query",
    "sql_query":    "sql",
    "statement":    "sql",
    "url":          "uri",
    "link":         "uri",
}


def _fix_args(tc: dict, tool_map: dict) -> tuple[dict, list[str]]:
    """Normalize argument names to match the tool's declared schema.

    Returns (fixed_tc, fixes_applied) where fixes_applied is a list of
    "wrong_key → correct_key" strings for logging.
    """
    tool = tool_map.get(tc["name"])
    if tool is None:
        return tc, []

    try:
        expected_keys: set[str] = set(tool.args_schema.model_fields.keys())
    except AttributeError:
        return tc, []

    new_args: dict = {}
    fixes: list[str] = []

    for k, v in tc["args"].items():
        if k in expected_keys:
            new_args[k] = v
        elif k in _ARG_ALIAS and _ARG_ALIAS[k] in expected_keys:
            correct = _ARG_ALIAS[k]
            new_args[correct] = v
            fixes.append(f"{k} → {correct}")
        else:
            new_args[k] = v

    return {**tc, "args": new_args}, fixes


async def _invoke_tool(tc: dict, tool_map: dict) -> tuple[str, bool]:
    """ツールを呼び出し (result_str, is_error) を返す。

    Unknown tool names return a descriptive error instead of raising KeyError.
    """
    if tc["name"] not in tool_map:
        available = ", ".join(sorted(tool_map.keys()))
        return (
            f"Error: Unknown tool '{tc['name']}'. "
            f"Available tools: {available}",
            True,
        )
    try:
        result = await tool_map[tc["name"]].ainvoke(tc["args"])
        result_str = str(result)
        is_error = "Error:" in result_str or "SQL error:" in result_str
    except ToolException as e:
        result_str = f"Tool error: {e}"
        is_error = True
    return result_str, is_error


def _update_step(steps: list[Step], idx: int, is_error: bool, result_str: str) -> int:
    """現在のステップ状態を更新し、次のインデックスを返す。"""
    if idx < len(steps):
        if is_error:
            steps[idx].status = "failed"
            steps[idx].note = result_str[:120]
        else:
            steps[idx].status = "done"
            steps[idx].note = result_str[:80]
            idx += 1
    return idx


def _build_watchdog_hint(tool_failure_counts: dict) -> str:
    repeated = {k: v for k, v in tool_failure_counts.items() if v >= 2}
    if not repeated:
        return ""
    return (
        f"[WATCHDOG] The following tools have failed {repeated} times total. "
        "Do NOT call them with the same arguments again. "
        "Use a completely different tool or a different approach."
    )


async def run_exec_loop(
    prompt: str, steps: list[Step], tools: list, tool_map: dict, model, logger
) -> str | None:
    llm_with_tools = model.bind_tools(tools)
    execution_history: list[str] = []
    consecutive_failures = 0
    replan_count = 0
    current_step_idx = 0

    model_name: str = getattr(model, "model", "unknown")
    metrics = MetricsLogger(model_name=model_name, prompt=prompt)
    # Tracks total failures per tool name across all replans (never resets).
    # Used by the Execution Watchdog to detect tools that keep failing.
    tool_failure_counts: dict[str, int] = defaultdict(int)

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=_task_message(prompt, steps)),
    ]

    for turn in range(MAX_STEPS):
        logger.info(f"[exec:llm] start (turn {turn + 1}, step {current_step_idx + 1}/{len(steps)})")
        t0 = time.perf_counter()
        response = await llm_with_tools.ainvoke(messages)
        logger.info(f"[exec:llm] done in {time.perf_counter() - t0:.1f}s")

        if not response.tool_calls:
            metrics.log_turn(turn=turn + 1, tool_called=False)
            pending_steps = [s for s in steps if s.status == "pending"]
            if (pending_steps or consecutive_failures > 0) and replan_count < MAX_REPLANS:
                replan_count += 1
                reason = "pending steps remain" if pending_steps else "gave up after error"
                logger.info(f"[replan triggered] {reason} (replan {replan_count}/{MAX_REPLANS})")

                watchdog_hint = _build_watchdog_hint(tool_failure_counts)
                steps, current_step_idx = await _apply_replan(
                    prompt, steps, execution_history, tools, model, logger,
                    watchdog_hint=watchdog_hint,
                )
                consecutive_failures = 0
                messages.append(HumanMessage(content=_task_message(prompt, steps)))
                continue

            answer = _sanitize(response.content)
            logger.info(f"final answer:\n{answer}")
            metrics.write_summary(steps)
            return answer

        tc = response.tool_calls[0]

        # --- Tool Name Fixer: correct hallucinated tool names ---
        tc, tool_name_fix = _fix_tool_name(tc, tool_map)
        if tool_name_fix:
            logger.warning(f"[tool_fix] {tool_name_fix}")

        # --- Input Fixer: normalize argument names before invocation ---
        tc, arg_fixes = _fix_args(tc, tool_map)
        if arg_fixes:
            logger.warning(f"[arg_fix] {tc['name']}: {', '.join(arg_fixes)}")

        logger.info(f"[Tool Call] {tc['name']}({tc['args']})")
        messages.append(AIMessage(content=response.content, tool_calls=[tc]))

        result_str, is_error = await _invoke_tool(tc, tool_map)
        logger.info(f"[Tool Result] {result_str[:500]}")

        metrics.log_turn(
            turn=turn + 1,
            tool_called=True,
            tool_name=tc["name"],
            tool_name_fix=tool_name_fix,
            arg_fixes=arg_fixes,
            is_error=is_error,
        )

        execution_history.append(
            f"{tc['name']}({tc['args']}) → {'ERROR: ' if is_error else ''}{result_str[:200]}"
        )
        messages.append(ToolMessage(content=result_str, tool_call_id=tc["id"]))

        current_step_idx = _update_step(steps, current_step_idx, is_error, result_str)
        logger.info(f"[checklist]\n{format_checklist(steps)}")

        if is_error:
            consecutive_failures += 1
            tool_failure_counts[tc["name"]] += 1

            if consecutive_failures >= MAX_FAILURES_BEFORE_REPLAN and replan_count < MAX_REPLANS:
                replan_count += 1
                logger.info(f"[replan triggered] {consecutive_failures} consecutive failures (replan {replan_count}/{MAX_REPLANS})")

                watchdog_hint = _build_watchdog_hint(tool_failure_counts)
                if watchdog_hint:
                    logger.warning(f"[watchdog] {watchdog_hint}")

                steps, current_step_idx = await _apply_replan(
                    prompt, steps, execution_history, tools, model, logger,
                    watchdog_hint=watchdog_hint,
                )
                consecutive_failures = 0
                messages.append(HumanMessage(content=_task_message(prompt, steps)))
        else:
            consecutive_failures = 0

    logger.warning("最大ステップ数に達しました。")
    metrics.write_summary(steps)
