"""Entry point — run the planner agent on a sample task and print the result."""

from __future__ import annotations

import json
import os
import sys

from dotenv import load_dotenv

from agents.planner import PlannerAgent

load_dotenv()


def main() -> None:
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        sys.exit("GOOGLE_API_KEY not set in environment or .env file")

    task = (
        "Research and write a blog post about the best AI startups in 2025"
        if len(sys.argv) < 2
        else " ".join(sys.argv[1:])
    )

    print(f"Task: {task}\n")

    planner = PlannerAgent(api_key=api_key)
    result = planner.plan(task)

    print("=" * 60)
    print("TASK GRAPH")
    print("=" * 60)
    for st in result.graph.subtasks:
        deps = f" (depends on: {st.dependencies})" if st.dependencies else ""
        print(f"  [{st.id}] {st.description}")
        print(f"       complexity: {st.complexity.value}{deps}")
    print()
    print(f"Planner model:  {result.model}")
    print(f"Prompt tokens:  {result.usage.prompt_tokens}")
    print(f"Output tokens:  {result.usage.completion_tokens}")
    print(f"Total tokens:   {result.usage.total_tokens}")


if __name__ == "__main__":
    main()
