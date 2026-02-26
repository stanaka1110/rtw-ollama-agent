import logging
import time

from langchain_core.messages import HumanMessage, SystemMessage

from config import PLAN_PROMPT, REPLAN_PROMPT
from models import Step, format_checklist, parse_steps
from utils import _tool_descriptions

logger = logging.getLogger("agent")


async def gather_current_state(tool_map: dict) -> str:
    parts = []
    t0 = time.perf_counter()
    logger.info("[gather_state] start")
    for tool_name, label, args in [
        ("list_tables",    "SQLite tables",     {}),
        ("list_directory", "Files in /data",    {"path": "/data"}),
        ("list_memories",  "Stored memories",   {}),
    ]:
        if tool_name not in tool_map:
            continue
        try:
            result = await tool_map[tool_name].ainvoke(args)
            parts.append(f"[{label}]\n{result}")
        except Exception as e:
            parts.append(f"[{label}]\n(error: {e})")
    logger.info(f"[gather_state] done in {time.perf_counter() - t0:.1f}s")
    return "\n\n".join(parts) if parts else "(no state available)"


async def make_plan(prompt: str, tools: list, tool_map: dict, model) -> str:
    current_state = await gather_current_state(tool_map)
    messages = [
        SystemMessage(content=PLAN_PROMPT.format(
            current_state=current_state,
            tool_descriptions=_tool_descriptions(tools),
        )),
        HumanMessage(content=prompt),
    ]
    logger.info("[plan:llm] start")
    t0 = time.perf_counter()
    result = (await model.ainvoke(messages)).content
    logger.info(f"[plan:llm] done in {time.perf_counter() - t0:.1f}s")
    return result


async def replan(
    prompt: str,
    steps: list[Step],
    execution_history: list[str],
    tools: list,
    model,
    watchdog_hint: str = "",
) -> str:
    checklist = format_checklist(steps)
    history_text = "\n".join(execution_history[-10:])  # 直近10件に絞る

    # Prepend watchdog alert when repeated tool failures have been detected.
    watchdog_block = f"{watchdog_hint}\n\n" if watchdog_hint else ""

    messages = [
        SystemMessage(content=REPLAN_PROMPT.format(tool_descriptions=_tool_descriptions(tools))),
        HumanMessage(content=(
            f"{watchdog_block}"
            f"Original task: {prompt}\n\n"
            f"Current checklist:\n{checklist}\n\n"
            f"Recent execution history:\n{history_text}\n\n"
            "Create a revised plan for the remaining ⏳ and ❌ steps only."
        )),
    ]
    logger.info("[replan:llm] start")
    t0 = time.perf_counter()
    result = (await model.ainvoke(messages)).content
    logger.info(f"[replan:llm] done in {time.perf_counter() - t0:.1f}s")
    return result


async def _apply_replan(
    prompt, steps, execution_history, tools, model, logger,
    watchdog_hint: str = "",
) -> tuple[list[Step], int]:
    new_plan_text = await replan(
        prompt, steps, execution_history, tools, model,
        watchdog_hint=watchdog_hint,
    )
    new_steps = parse_steps(new_plan_text)
    done_steps = [s for s in steps if s.status == "done"]
    merged = done_steps + new_steps
    logger.info(f"[replan]\n{format_checklist(merged)}")
    return merged, len(done_steps)
