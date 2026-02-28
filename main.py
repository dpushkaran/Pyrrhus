"""Entry point — run the planner + allocator pipeline and print the result."""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

from agents.planner import PlannerAgent
from agents.allocator import AllocatorAgent
from models import TIER_PRICING_PER_1M_OUTPUT

load_dotenv()


def _planner_cost_dollars(prompt_tokens: int, completion_tokens: int) -> float:
    """Estimate the planner's own cost (runs on gemini-2.5-flash = Verify tier)."""
    input_rate = 0.15 / 1_000_000
    output_rate = 0.60 / 1_000_000
    return prompt_tokens * input_rate + completion_tokens * output_rate


def main() -> None:
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        sys.exit("GOOGLE_API_KEY not set in environment or .env file")

    task = (
        "Research and write a blog post about the best AI startups in 2025"
        if len(sys.argv) < 2
        else " ".join(sys.argv[1:])
    )
    budget = float(os.getenv("BUDGET_DOLLARS", "0.08"))

    print(f"Task:   {task}")
    print(f"Budget: ${budget:.2f}\n")

    # --- Step 1: Plan --------------------------------------------------------
    planner = PlannerAgent(api_key=api_key)
    result = planner.plan(task)

    planner_cost = _planner_cost_dollars(
        result.usage.prompt_tokens, result.usage.completion_tokens
    )

    print("=" * 64)
    print("TASK GRAPH (from Planner)")
    print("=" * 64)
    for st in result.graph.subtasks:
        deps = f" (depends on: {st.dependencies})" if st.dependencies else ""
        print(f"  [{st.id}] {st.description}")
        print(f"       complexity: {st.complexity.value}{deps}")
    print(f"\n  Planner cost: ${planner_cost:.6f}  ({result.usage.total_tokens} tokens)")

    # --- Step 2: Allocate ----------------------------------------------------
    allocator = AllocatorAgent()
    plan = allocator.allocate(
        graph=result.graph,
        budget_dollars=budget,
        spent_dollars=planner_cost,
    )

    print()
    print("=" * 64)
    print("EXECUTION PLAN (from Allocator)")
    print("=" * 64)
    print(f"  {'ID':<4} {'Tier':<8} {'Model':<20} {'Max Tok':<9} {'Est Cost':<10} {'Status'}")
    print(f"  {'--':<4} {'----':<8} {'-----':<20} {'-------':<9} {'--------':<10} {'------'}")
    for a in plan.allocations:
        status = "SKIP" if a.skipped else "ok"
        print(
            f"  {a.subtask_id:<4} {a.tier.value:<8} {a.model:<20} "
            f"{a.max_tokens:<9} ${a.estimated_cost_dollars:<9.6f} {status}"
        )

    print(f"\n  Total estimated:  ${plan.total_estimated_cost_dollars:.6f}  "
          f"({plan.total_estimated_tokens} tokens)")
    print(f"  Budget:           ${plan.budget_dollars:.2f}")
    print(f"  Remaining:        ${plan.budget_dollars - planner_cost - plan.total_estimated_cost_dollars:.6f}")

    if plan.downgrades_applied:
        print(f"\n  Downgrades:")
        for d in plan.downgrades_applied:
            print(f"    • {d}")
    else:
        print(f"\n  Downgrades: none")


if __name__ == "__main__":
    main()
