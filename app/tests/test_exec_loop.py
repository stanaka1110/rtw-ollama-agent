import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.tools import ToolException

sys.path.insert(0, str(Path(__file__).parent.parent))

from exec_loop import _invoke_tool, _update_step
from models import Step


def _make_tool(return_value=None, side_effect=None):
    tool = MagicMock()
    if side_effect is not None:
        tool.ainvoke = AsyncMock(side_effect=side_effect)
    else:
        tool.ainvoke = AsyncMock(return_value=return_value)
    return tool


# ── _invoke_tool ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_invoke_tool_success():
    tc = {"name": "list_tables", "args": {}}
    tool_map = {"list_tables": _make_tool("table1, table2")}
    result_str, is_error = await _invoke_tool(tc, tool_map)
    assert result_str == "table1, table2"
    assert is_error is False


@pytest.mark.asyncio
async def test_invoke_tool_error_keyword_in_result():
    tc = {"name": "query", "args": {"sql": "BAD SQL"}}
    tool_map = {"query": _make_tool("SQL error: near BAD")}
    result_str, is_error = await _invoke_tool(tc, tool_map)
    assert is_error is True


@pytest.mark.asyncio
async def test_invoke_tool_tool_exception():
    tc = {"name": "write_file", "args": {"path": "/forbidden"}}
    tool_map = {"write_file": _make_tool(side_effect=ToolException("permission denied"))}
    result_str, is_error = await _invoke_tool(tc, tool_map)
    assert is_error is True
    assert "Tool error:" in result_str


# ── _update_step ───────────────────────────────────────────────────

def test_update_step_success_advances_index():
    steps = [
        Step(number=1, text="1. step one", status="pending"),
        Step(number=2, text="2. step two", status="pending"),
    ]
    new_idx = _update_step(steps, 0, False, "ok result")
    assert steps[0].status == "done"
    assert "ok result" in steps[0].note
    assert new_idx == 1


def test_update_step_failure_keeps_index():
    steps = [Step(number=1, text="1. step one", status="pending")]
    new_idx = _update_step(steps, 0, True, "some error message")
    assert steps[0].status == "failed"
    assert "some error message" in steps[0].note
    assert new_idx == 0


def test_update_step_out_of_bounds_is_noop():
    steps = [Step(number=1, text="1. step one", status="done")]
    new_idx = _update_step(steps, 1, False, "extra result")
    assert new_idx == 1  # unchanged, no IndexError
