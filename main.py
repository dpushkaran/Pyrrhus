"""Entry point — run the full Planner → Allocator → Executor pipeline."""

from __future__ import annotations

import os
import sys
import time

from dotenv import load_dotenv

from agents.allocator import AllocatorAgent
from agents.executor import ExecutorAgent
from agents.planner import PlannerAgent
from models import TIER_PRICING_PER_1M_INPUT, TIER_PRICING_PER_1M_OUTPUT, Tier

load_dotenv()


def _planner_cost_dollars(prompt_tokens: int, completion_tokens: int) -> float:
    """Planner runs on gemini-2.5-flash (Verify tier pricing)."""
    tier = Tier.VERIFY
    inp = prompt_tokens * TIER_PRICING_PER_1M_INPUT[tier] / 1_000_000
    out = completion_tokens * TIER_PRICING_PER_1M_OUTPUT[tier] / 1_000_000
    return inp + out


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
    print(f"Budget: ${budget:.4f}")
    print()
    t0 = time.time()

    # ── Step 1: Plan ─────────────────────────────────────────────────────
    print("=" * 64)
    print("STEP 1 — PLANNER")
    print("=" * 64)

    planner = PlannerAgent(api_key=api_key)
    planner_result = planner.plan(task)
    planner_cost = _planner_cost_dollars(
        planner_result.usage.prompt_tokens,
        planner_result.usage.completion_tokens,
    )

    for st in planner_result.graph.subtasks:
        deps = f"  deps: {st.dependencies}" if st.dependencies else ""
        print(f"  [{st.id}] [{st.complexity.value:<6}] {st.description}{deps}")
    print(f"\n  Planner cost: ${planner_cost:.6f}  "
          f"({planner_result.usage.total_tokens} total tokens)")

    # ── Step 2: Allocate ─────────────────────────────────────────────────
    print()
    print("=" * 64)
    print("STEP 2 — ALLOCATOR")
    print("=" * 64)

    allocator = AllocatorAgent()
    plan = allocator.allocate(
        graph=planner_result.graph,
        budget_dollars=budget,
        spent_dollars=planner_cost,
    )

    print(f"  {'ID':<4} {'Tier':<8} {'Model':<20} {'MaxTok':<8} {'EstCost':<12} {'Status'}")
    print(f"  {'─'*4} {'─'*8} {'─'*20} {'─'*8} {'─'*12} {'─'*6}")
    for a in plan.allocations:
        status = "SKIP" if a.skipped else "ok"
        print(
            f"  {a.subtask_id:<4} {a.tier.value:<8} {a.model:<20} "
            f"{a.max_tokens:<8} ${a.estimated_cost_dollars:<11.6f} {status}"
        )

    if plan.downgrades_applied:
        print(f"\n  Downgrades:")
        for d in plan.downgrades_applied:
            print(f"    • {d}")

    # ── Step 3: Execute ──────────────────────────────────────────────────
    print()
    print("=" * 64)
    print("STEP 3 — EXECUTOR")
    print("=" * 64)

    executor = ExecutorAgent(api_key=api_key)
    result = executor.execute(
        task=task,
        graph=planner_result.graph,
        plan=plan,
        planner_cost_dollars=planner_cost,
    )
    r = result.report

    print()
    for sr in r.subtask_results:
        if sr.skipped:
            print(f"  [{sr.subtask_id}] SKIPPED")
            continue
        print(
            f"  [{sr.subtask_id}] {sr.tier.value:<6} │ "
            f"budget {sr.tokens_budgeted:>5} out │ "
            f"used {sr.completion_tokens:>5} out ({sr.total_tokens:>5} total) │ "
            f"${sr.cost_dollars:.6f} │ "
            f"surplus +{sr.surplus}"
        )

    elapsed = time.time() - t0

    # ── Cost Report ──────────────────────────────────────────────────────
    print()
    print("=" * 64)
    print("COST REPORT")
    print("=" * 64)

    print(f"\n  Budget Summary")
    print(f"    Budget:      ${r.budget_dollars:.4f}")
    print(f"    Spent:       ${r.spent_dollars:.6f}")
    print(f"    Remaining:   ${r.remaining_dollars:.6f}")
    print(f"    Utilization: {r.utilization_pct:.1f}%")

    print(f"\n  Tier Distribution")
    for tier_name, count in r.tier_counts.items():
        if count > 0:
            print(f"    {tier_name:<8} {count} subtask(s)")
    print(f"    Skipped: {r.subtasks_skipped}  │  Downgraded: {r.subtasks_downgraded}")

    print(f"\n  Efficiency")
    print(f"    Tokens budgeted:  {r.total_tokens_budgeted:,}")
    print(f"    Tokens consumed:  {r.total_tokens_consumed:,}")
    print(f"    Total surplus:    {r.total_surplus:,}")
    print(f"    Token efficiency: {r.token_efficiency_pct:.1f}%")

    print(f"\n  Task Graph")
    print(f"    Subtasks: {r.total_subtasks}  │  Max depth: {r.max_depth}  │  "
          f"Parallelizable: {r.parallelizable_subtasks}")
    print(f"    Complexity: {r.complexity_distribution}")

    print(f"\n  Wall time: {elapsed:.1f}s")

    # ── Deliverable ──────────────────────────────────────────────────────
    print()
    print("=" * 64)
    print("DELIVERABLE")
    print("=" * 64)
    print()
    print(result.deliverable)


if __name__ == "__main__":
    main()
