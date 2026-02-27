import re
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


# Patterns that are unambiguously conversational — no LLM call needed.
_CHAT_RE = re.compile(
    r'^(こんにちは|おはよう|こんばんは|ありがとう|どうも|よろしく|'
    r'お疲れ|ただいま|いただきます|ごちそうさま|はじめまして|'
    r'hello|hi\b|hey\b|thanks|thank you|good (morning|evening|night))',
    re.IGNORECASE,
)

def _quick_classify(prompt: str) -> str | None:
    """Keyword pre-filter: returns 'chat' for obvious greetings, else None."""
    if _CHAT_RE.match(prompt.strip()):
        return "chat"
    return None


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
    # Strip <think>...</think> blocks emitted by reasoning models (deepseek-r1, etc.)
    # before checking for CHAT/AGENT, then search anywhere in the response.
    raw = re.sub(r"<think>.*?</think>", "", response.content, flags=re.DOTALL).strip().upper()
    m = re.search(r"\b(CHAT|AGENT)\b", raw)
    intent = "chat" if (m and m.group(1) == "CHAT") else "agent"
    logger.info(f"[router] raw={raw[:120]!r} → intent={intent} ({time.perf_counter() - t0:.1f}s)")
    return intent


async def run(prompt: str) -> str | None:
    logger = setup_logging()
    model = llm.get_llm()

    logger.info(f"prompt: {prompt}")

    # --- Router: keyword pre-filter, then LLM fallback ---
    intent = _quick_classify(prompt)
    if intent:
        logger.info(f"[router] quick_classify → {intent}")
    else:
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
