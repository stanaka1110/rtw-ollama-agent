import time

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_mcp_adapters.client import MultiServerMCPClient

import llm
from prompts import CHAT_PROMPT, ROUTER_PROMPT
from exec_loop import run_exec_loop
from models import format_checklist, parse_steps
from planner import make_plan
from servers import (
    FILESYSTEM_CONFIG,
    MEMORY_CONFIG,
    SHELL_CONFIG,
    SQLITE_CONFIG,
    TIME_CONFIG,
    WEBSEARCH_CONFIG,
)
from utils import _sanitize, setup_logging


async def classify_intent(prompt: str, model, logger) -> str:
    """Classify prompt as 'chat' or 'agent' with a single lightweight LLM call.

    Defaults to 'agent' on any ambiguous or unexpected output to ensure
    tool-requiring tasks are never silently dropped.
    """
    t0 = time.perf_counter()
    logger.info("[router] classifying intent...")
    response = await model.ainvoke([
        SystemMessage(content=ROUTER_PROMPT),
        HumanMessage(content=prompt),
    ])
    raw = response.content.strip().upper()
    intent = "chat" if raw.startswith("CHAT") else "agent"
    logger.info(f"[router] raw={raw!r} → intent={intent} ({time.perf_counter() - t0:.1f}s)")
    return intent


async def run(prompt: str) -> str | None:
    logger = setup_logging()
    model = llm.get_llm()

    logger.info(f"prompt: {prompt}")

    # --- Router: classify BEFORE expensive MCP setup ---
    intent = await classify_intent(prompt, model, logger)

    if intent == "chat":
        response = await model.ainvoke([
            SystemMessage(content=CHAT_PROMPT),
            HumanMessage(content=prompt),
        ])
        answer = _sanitize(response.content)
        logger.info(f"[chat] answer: {answer}")
        return answer

    # --- Agent mode: full Plan-and-Execute (unchanged) ---
    client = MultiServerMCPClient({
        "filesystem": FILESYSTEM_CONFIG,
        "shell":      SHELL_CONFIG,
        "websearch":  WEBSEARCH_CONFIG,
        "time":       TIME_CONFIG,
        "sqlite":     SQLITE_CONFIG,
        "memory":     MEMORY_CONFIG,
    })
    tools = await client.get_tools()
    tool_map = {t.name: t for t in tools}

    plan_text = await make_plan(prompt, tools, tool_map, model)
    steps = parse_steps(plan_text)
    logger.info(f"[plan]\n{format_checklist(steps)}")
    return await run_exec_loop(prompt, steps, tools, tool_map, model, logger)
