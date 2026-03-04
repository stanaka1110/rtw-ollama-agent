"""Tool-call correction utilities.

Corrects hallucinated tool names and argument names emitted by small open-weight
models before the tool is actually invoked.  All functions are pure / stateless
and operate only on the tool-call dict and the tool_map.
"""

import difflib

# ---------------------------------------------------------------------------
# Tool name correction
# ---------------------------------------------------------------------------

# Mapping of commonly hallucinated tool names → correct MCP tool names.
# Observed across llama3.2:3b, mistral and other small open-weight models.
_TOOL_NAME_ALIAS: dict[str, str] = {
    # filesystem
    "read_text_file":            "read_file",
    "read_file_content":         "read_file",
    "write_text_file":           "write_file",
    "create_file":               "write_file",
    "save_file":                 "write_file",
    "list_files":                "list_directory",
    "list_directory_with_sizes": "list_directory",
    "ls":                        "list_directory",
    "delete_file":               "remove_file",
    # shell
    "run_command":               "execute_command",
    "run_shell":                 "execute_command",
    "shell_execute":             "execute_command",
    "bash":                      "execute_command",
    "exec":                      "execute_command",
    "run_bash":                  "execute_command",
    # websearch
    "search_web":                "web_search",
    "internet_search":           "web_search",
    "get_page":                  "fetch_page",
    "fetch_url":                 "fetch_page",
    "open_url":                  "fetch_page",
    # time
    "current_time":              "get_current_datetime",
    "get_time":                  "get_current_datetime",
    "get_datetime":              "get_current_datetime",
    "now":                       "get_current_datetime",
    # sqlite
    "sql_query":                 "query",
    "execute_sql":               "query",
    "run_sql":                   "query",
    # memory
    "store_memory":              "remember",
    "save_memory":               "remember",
    "get_memory":                "recall",
    "retrieve_memory":           "recall",
    "delete_memory":             "forget",
    "remove_memory":             "forget",
}

# Minimum similarity ratio accepted by difflib fuzzy fallback.
# 0.80 is intentionally conservative to avoid mis-corrections.
_FUZZY_CUTOFF = 0.80


def _fix_tool_name(tc: dict, tool_map: dict) -> tuple[dict, str | None]:
    """Try to correct a hallucinated tool name before invocation.

    Correction strategy (in order):
    1. Exact match in tool_map  → no change needed.
    2. Alias table lookup       → deterministic, high-confidence correction.
    3. difflib fuzzy match      → catches variations not in the alias table.

    Returns (fixed_tc, fix_description) where fix_description is None when
    no correction was applied.  Uses '→' for alias fixes and '~>' for fuzzy
    fixes so they are distinguishable in logs and metrics.
    """
    name = tc["name"]
    if name in tool_map:
        return tc, None

    # Strategy 1: alias table
    if name in _TOOL_NAME_ALIAS:
        corrected = _TOOL_NAME_ALIAS[name]
        if corrected in tool_map:
            return {**tc, "name": corrected}, f"{name} → {corrected}"

    # Strategy 2: difflib fuzzy match (conservative cutoff)
    candidates = difflib.get_close_matches(name, tool_map.keys(), n=1, cutoff=_FUZZY_CUTOFF)
    if candidates:
        corrected = candidates[0]
        return {**tc, "name": corrected}, f"{name} ~> {corrected}"

    return tc, None


# ---------------------------------------------------------------------------
# Argument name correction
# ---------------------------------------------------------------------------

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

    Handles both Pydantic-backed LangChain tools (args_schema.model_fields)
    and MCP tools that expose a raw JSON Schema dict (args_schema["properties"]).

    Returns (fixed_tc, fixes_applied) where fixes_applied is a list of
    "wrong_key → correct_key" strings for logging.
    """
    tool = tool_map.get(tc["name"])
    if tool is None:
        return tc, []

    schema = tool.args_schema
    if isinstance(schema, dict):
        # MCP tools expose args_schema as a JSON Schema dict
        expected_keys: set[str] = set(schema.get("properties", {}).keys())
    elif hasattr(schema, "model_fields"):
        # Native LangChain StructuredTool with Pydantic model
        expected_keys = set(schema.model_fields.keys())
    else:
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


# ---------------------------------------------------------------------------
# Content fixer
# ---------------------------------------------------------------------------

def _fix_content(tc: dict) -> tuple[dict, str | None]:
    """In write_file calls, convert literal \\n / \\t escape sequences to actual
    characters.  Small models often emit JSON with double-escaped newlines
    (e.g. "content": "line1\\nline2") which produce a SyntaxError when the
    string is written verbatim to a Python file.
    """
    if tc["name"] != "write_file":
        return tc, None
    content = tc["args"].get("content", "")
    if "\\" not in content:
        return tc, None
    fixed = content.replace("\\n", "\n").replace("\\t", "\t")
    if fixed == content:
        return tc, None
    return {**tc, "args": {**tc["args"], "content": fixed}}, "\\n/\\t → actual chars in content"
