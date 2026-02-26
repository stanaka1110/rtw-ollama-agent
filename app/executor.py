from langchain_mcp_adapters.client import MultiServerMCPClient

import llm
from exec_loop import run_exec_loop
from plan_runner import run_plan_phase
from servers import (
    FILESYSTEM_CONFIG,
    MEMORY_CONFIG,
    SHELL_CONFIG,
    SQLITE_CONFIG,
    TIME_CONFIG,
    WEBSEARCH_CONFIG,
)
from utils import setup_logging


async def run(prompt: str) -> str | None:
    logger = setup_logging()
    model = llm.get_llm()

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

    logger.info(f"prompt: {prompt}")

    steps = await run_plan_phase(prompt, tools, tool_map, model, logger)
    return await run_exec_loop(prompt, steps, tools, tool_map, model, logger)
