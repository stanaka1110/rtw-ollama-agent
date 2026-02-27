import os

from langchain_ollama import ChatOllama

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
OLLAMA_MODEL    = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")

# Per-model recommended settings derived from benchmark runs.
# temperature=0.0 maximises determinism for tool-calling tasks.
# num_ctx controls context window; larger = more history but slower inference.
_MODEL_CONFIGS: dict[str, dict] = {
    "qwen2.5:7b":        {"temperature": 0.0, "num_ctx": 4096},
    "qwen2.5:14b":       {"temperature": 0.0, "num_ctx": 4096},
    "llama3.1:8b":       {"temperature": 0.1, "num_ctx": 4096},
    "llama3.2:3b":       {"temperature": 0.1, "num_ctx": 4096},
    "mistral:7b":        {"temperature": 0.0, "num_ctx": 4096},
    "gemma3:9b":         {"temperature": 0.0, "num_ctx": 8192},
    # --- newly added models ---
    "lfm2.5-thinking":   {"temperature": 0.0, "num_ctx": 4096},  # 1.2B reasoning
    "gemma3:4b":         {"temperature": 0.0, "num_ctx": 4096},  # 4B general
    "phi4":              {"temperature": 0.0, "num_ctx": 8192},  # 14B STEM/logic
    "qwen3:30b-a3b":     {"temperature": 0.0, "num_ctx": 4096},  # 30B MoE (keep ctx small for speed)
    "deepseek-r1:14b":   {"temperature": 0.0, "num_ctx": 8192},  # 14B distilled reasoning
}

_DEFAULT_CONFIG: dict = {"temperature": 0.0, "num_ctx": 4096}


def get_llm() -> ChatOllama:
    cfg = _MODEL_CONFIGS.get(OLLAMA_MODEL, _DEFAULT_CONFIG)
    return ChatOllama(
        model=OLLAMA_MODEL,
        base_url=OLLAMA_BASE_URL,
        temperature=cfg["temperature"],
        num_ctx=cfg["num_ctx"],
    )
