"""
LangChain + Ollama + MCP オーケストレーター (Plan-and-Execute with Replan)

使い方:
  python main.py "<プロンプト>"
"""

import argparse
import asyncio

from executor import run

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MCP オーケストレーター")
    parser.add_argument("prompt", help="LLM へのプロンプト")
    args = parser.parse_args()
    asyncio.run(run(args.prompt))
