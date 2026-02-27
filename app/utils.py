import json
import logging
import re
from datetime import datetime
from pathlib import Path

from config import LOG_DIR
from models import Step, format_checklist

METRICS_FILE = LOG_DIR / "metrics.jsonl"


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


class MetricsLogger:
    """Per-session metrics collector.

    Tracks Tool Calling Accuracy (TCA), Arg-Fit Rate, and Step Completion Rate,
    then appends a single JSONL record to METRICS_FILE at the end of each run.
    """

    def __init__(self, model_name: str, prompt: str):
        self.model_name = model_name
        self.prompt = prompt
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        self._turns: list[dict] = []

    def log_turn(
        self,
        turn: int,
        tool_called: bool,
        tool_name: str | None = None,
        tool_name_fix: str | None = None,
        arg_fixes: list[str] | None = None,
        is_error: bool | None = None,
    ) -> None:
        """Record one LLM turn."""
        self._turns.append({
            "turn": turn,
            "tool_called": tool_called,
            "tool_name": tool_name,
            "tool_name_fix": tool_name_fix,
            "arg_fixes": arg_fixes or [],
            "is_error": is_error,
        })

    def write_summary(self, steps: list[Step]) -> None:
        """Compute aggregated metrics and append to metrics.jsonl."""
        total_turns = len(self._turns)
        tool_turns = [t for t in self._turns if t["tool_called"]]
        name_fix_turns = [t for t in tool_turns if t.get("tool_name_fix")]
        arg_fix_turns  = [t for t in tool_turns if t["arg_fixes"]]

        tca = len(tool_turns) / total_turns if total_turns > 0 else 0.0

        # Tool-Name Accuracy: fraction of tool calls with correct name on first try
        tool_name_accuracy = (
            (len(tool_turns) - len(name_fix_turns)) / len(tool_turns)
            if tool_turns else 1.0
        )
        # Arg-Fit Rate: tool calls where all args matched schema without fixing
        arg_fit_rate = (
            (len(tool_turns) - len(arg_fix_turns)) / len(tool_turns)
            if tool_turns else 1.0
        )
        done_count = sum(1 for s in steps if s.status == "done")
        step_completion_rate = done_count / len(steps) if steps else 0.0

        record = {
            "session_id": self.session_id,
            "timestamp": datetime.now().isoformat(),
            "model": self.model_name,
            "prompt_preview": self.prompt[:100],
            "tca": round(tca, 3),
            "tool_name_accuracy": round(tool_name_accuracy, 3),
            "arg_fit_rate": round(arg_fit_rate, 3),
            "step_completion_rate": round(step_completion_rate, 3),
            "total_turns": total_turns,
            "total_steps": len(steps),
            "done_steps": done_count,
            "tool_name_fixes": len(name_fix_turns),
            "arg_fixes": len(arg_fix_turns),
            "turns": self._turns,
        }

        METRICS_FILE.parent.mkdir(exist_ok=True)
        with METRICS_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(exist_ok=True)
    log_file = LOG_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    logger = logging.getLogger("agent")
    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    sh = logging.StreamHandler()  # also write to stderr → captured by docker exec 2>
    sh.setFormatter(formatter)
    logger.addHandler(sh)
    return logger
