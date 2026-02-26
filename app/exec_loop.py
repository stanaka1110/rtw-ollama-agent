import time

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import ToolException

from config import MAX_FAILURES_BEFORE_REPLAN, MAX_REPLANS, MAX_STEPS, SYSTEM_PROMPT
from models import Step, format_checklist
from planner import _apply_replan
from utils import MetricsLogger, _sanitize, _task_message

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
    """ツールを呼び出し (result_str, is_error) を返す。"""
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
                steps, current_step_idx = await _apply_replan(
                    prompt, steps, execution_history, tools, model, logger
                )
                consecutive_failures = 0
                messages.append(HumanMessage(content=_task_message(prompt, steps)))
                continue

            answer = _sanitize(response.content)
            logger.info(f"final answer:\n{answer}")
            metrics.write_summary(steps)
            return answer

        tc = response.tool_calls[0]

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
            if consecutive_failures >= MAX_FAILURES_BEFORE_REPLAN and replan_count < MAX_REPLANS:
                replan_count += 1
                logger.info(f"[replan triggered] {consecutive_failures} consecutive failures (replan {replan_count}/{MAX_REPLANS})")
                steps, current_step_idx = await _apply_replan(
                    prompt, steps, execution_history, tools, model, logger
                )
                consecutive_failures = 0
                messages.append(HumanMessage(content=_task_message(prompt, steps)))
        else:
            consecutive_failures = 0

    logger.warning("最大ステップ数に達しました。")
    metrics.write_summary(steps)
