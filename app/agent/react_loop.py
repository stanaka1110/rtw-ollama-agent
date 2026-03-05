"""ReAct (Reason + Act) loop.

Single-phase execution: no planning step.  The model observes the current
state, reasons, and acts (calls tools) iteratively until it produces a final
text answer or the timeout / step limit is reached.

Differences from plan_exec:
  - No make_plan() / parse_steps() call   → saves 1 LLM call per task
  - No _do_replan()                        → no extra LLM call on failures
  - No steps list                          → write_summary(steps=[])
  - No step index / consecutive_failures tracking
"""

import asyncio
import time

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from agent.fixers import _fix_args, _fix_content, _fix_tool_name
from agent.loop_helpers import _apply_window, _invoke_tool, _trim_tool_result
from agent.planner import gather_current_state
from config import EXEC_TIMEOUT, FEATURES, MAX_STEPS, PROMPT_VARIANT
from core.prompts import build_system_prompt
from core.utils import MetricsLogger, _sanitize


def _react_variant() -> str:
    """Resolve the system-prompt variant for react mode.

    react_zh when PROMPT_VARIANT is 'zh', else react.
    """
    return "react_zh" if PROMPT_VARIANT == "zh" else "react"


async def run_react_loop(
    prompt: str,
    tools: list,
    tool_map: dict,
    model,
    logger,
) -> str | None:
    """Execute the ReAct loop.

    Gathers initial state, then runs an observe-think-act loop until the model
    emits a final text answer (no tool call) or the timeout / step limit hits.

    Returns the final answer string, or None on timeout / max_steps.
    """
    system_prompt = build_system_prompt(_react_variant())

    # Gather current state and embed in the first HumanMessage.
    current_state = await gather_current_state(tool_map, prompt)
    if current_state and current_state != "(state gathering skipped)":
        human_content = f"Task: {prompt}\n\nCurrent state:\n{current_state}"
    else:
        human_content = f"Task: {prompt}"

    llm_with_tools = model.bind_tools(tools)
    model_name: str = getattr(model, "model", "unknown")
    metrics = MetricsLogger(model_name=model_name, prompt=prompt)

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_content),
    ]

    loop_start = time.perf_counter()

    def _remaining() -> float:
        """Remaining seconds before EXEC_TIMEOUT (minimum 5s to avoid instant kill)."""
        return max(5.0, EXEC_TIMEOUT - (time.perf_counter() - loop_start))

    for turn in range(MAX_STEPS):
        elapsed = time.perf_counter() - loop_start
        if elapsed > EXEC_TIMEOUT:
            logger.warning(f"タイムアウト ({elapsed:.0f}s > {EXEC_TIMEOUT}s)。")
            metrics.write_summary([], termination="timeout")
            return None

        ctx_messages = messages
        if FEATURES.get("message_window", False):
            ctx_messages, truncated = _apply_window(messages)
            if truncated:
                logger.info(
                    f"[window] {len(messages)} → {len(ctx_messages)} messages"
                    f" (dropped {len(messages) - len(ctx_messages)} oldest)"
                )

        logger.info(f"[react:llm] start (turn {turn + 1})")
        t0 = time.perf_counter()
        try:
            response = await asyncio.wait_for(
                llm_with_tools.ainvoke(ctx_messages), timeout=_remaining()
            )
        except asyncio.TimeoutError:
            elapsed = time.perf_counter() - loop_start
            logger.warning(f"[react:llm] LLM呼び出しがタイムアウト ({elapsed:.0f}s)。")
            metrics.write_summary([], termination="timeout")
            return None
        except Exception as e:
            logger.error(f"[react:llm] LLM呼び出しエラー: {type(e).__name__}: {e}")
            metrics.write_summary([], termination="llm_error")
            return f"[エラー] このモデルはツール呼び出しに非対応か、LLM呼び出しに失敗しました: {e}"
        logger.info(f"[react:llm] done in {time.perf_counter() - t0:.1f}s")

        if not response.tool_calls:
            metrics.log_turn(turn=turn + 1, tool_called=False)
            answer = _sanitize(response.content)
            logger.info(f"final answer:\n{answer}")
            metrics.write_summary([], termination="answer")
            return answer

        tc = response.tool_calls[0]

        # --- Tool Name Fixer ---
        tool_name_fix = None
        if FEATURES.get("tool_name_fixer", True):
            tc, tool_name_fix = _fix_tool_name(tc, tool_map)
            if tool_name_fix:
                logger.warning(f"[tool_fix] {tool_name_fix}")

        # --- Arg Fixer ---
        arg_fixes: list[str] = []
        if FEATURES.get("arg_fixer", True):
            tc, arg_fixes = _fix_args(tc, tool_map)
            if arg_fixes:
                logger.warning(f"[arg_fix] {tc['name']}: {', '.join(arg_fixes)}")

        # --- Content Fixer ---
        if FEATURES.get("content_fixer", True):
            tc, content_fix = _fix_content(tc)
            if content_fix:
                logger.warning(f"[content_fix] {tc['name']}: {content_fix}")

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

        # --- Tool Result Trimming ---
        ctx_result = result_str
        if FEATURES.get("tool_result_trimming", True):
            ctx_result, original_len = _trim_tool_result(tc["name"], result_str)
            if len(ctx_result) < original_len:
                logger.info(
                    f"[trim] {tc['name']}: {original_len} → {len(ctx_result)} chars"
                )

        messages.append(ToolMessage(content=ctx_result, tool_call_id=tc["id"]))

    logger.warning("最大ステップ数に達しました。")
    metrics.write_summary([], termination="max_steps")
    return None
