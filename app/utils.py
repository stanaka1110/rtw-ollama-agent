import logging
import re
from datetime import datetime

from config import LOG_DIR
from models import Step, format_checklist


def _tool_descriptions(tools: list) -> str:
    return "\n".join(f"- {t.name}: {t.description}" for t in tools)


def _task_message(prompt: str, steps: list[Step]) -> str:
    checklist = format_checklist(steps)
    pending = sum(1 for s in steps if s.status == "pending")
    return (
        f"Task: {prompt}\n\n"
        f"Execution checklist ({pending} steps remaining):\n{checklist}\n\n"
        "IMPORTANT: Execute the ⏳ steps one by one using tools. "
        "Do NOT give a final answer until all steps are ✅."
    )


def _sanitize(text: str) -> str:
    text = re.sub(r"<tool_call>.*?</tool_call>", "", text, flags=re.DOTALL)
    lines = [line for line in text.splitlines() if not re.match(r'\s*\{"name":', line)]
    return "\n".join(lines).strip()


def setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(exist_ok=True)
    log_file = LOG_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    logger = logging.getLogger("agent")
    logger.setLevel(logging.DEBUG)
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(fh)
    return logger
