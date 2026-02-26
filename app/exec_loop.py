import time

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import ToolException

from config import MAX_FAILURES_BEFORE_REPLAN, MAX_REPLANS, MAX_STEPS, SYSTEM_PROMPT
from models import Step, format_checklist
from planner import _apply_replan
from utils import _sanitize, _task_message


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
            return answer

        tc = response.tool_calls[0]
        logger.info(f"[Tool Call] {tc['name']}({tc['args']})")
        messages.append(AIMessage(content=response.content, tool_calls=[tc]))

        result_str, is_error = await _invoke_tool(tc, tool_map)
        logger.info(f"[Tool Result] {result_str[:500]}")
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
