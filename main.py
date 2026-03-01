"""Entry point — run the full Planner → Allocator → Executor pipeline.

Supports two modes:
  python main.py [task]              — single run with trace + quality eval
  python main.py --batch [task]      — sweep across multiple budget levels
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time

from dotenv import load_dotenv

from agents.dynamic_executor import DynamicExecutor
from agents.evaluator import EvaluatorAgent
from agents.planner import PlannerAgent
from analysis.text_metrics import compute_text_metrics
from analysis.trace_store import save_trace
from batch_runner import run_batch
from models import (
    TIER_PRICING_PER_1M_INPUT,
    TIER_PRICING_PER_1M_OUTPUT,
    PlannerTrace,
    RunTrace,
    SubTaskTrace,
    Tier,
)

load_dotenv()


def _planner_cost_dollars(prompt_tokens: int, completion_tokens: int) -> float:
    tier = Tier.VERIFY
    inp = prompt_tokens * TIER_PRICING_PER_1M_INPUT[tier] / 1_000_000
    out = completion_tokens * TIER_PRICING_PER_1M_OUTPUT[tier] / 1_000_000
    return inp + out


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Budget-aware agent pipeline")
    parser.add_argument("task", nargs="?", default=None, help="Task to execute")
    parser.add_argument(
        "--batch", action="store_true",
        help="Run the task at multiple budget levels",
    )
    parser.add_argument(
        "--budgets",
        default="0.01,0.02,0.04,0.08,0.16",
        help="Comma-separated budget levels for batch mode (dollars)",
    )
    parser.add_argument(
        "--budget", type=float, default=None,
        help="Single-run budget in dollars (default: $0.08 or BUDGET_DOLLARS env var)",
    )
    parser.add_argument(
        "--no-eval", action="store_true",
        help="Skip quality evaluation (faster, no evaluator cost)",
    )
    parser.add_argument(
        "--concurrency", type=int, default=3,
        help="Max parallel runs in batch mode",
    )
    return parser.parse_args()


def _run_single(api_key: str, task: str, budget: float, evaluate: bool) -> None:
    """Original single-run pipeline with trace logging and quality eval."""
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

    # ── Step 2: Dynamic Execution ──────────────────────────────────────
    print()
    print("=" * 64)
    print("STEP 2 — DYNAMIC EXECUTOR (ROI-driven)")
    print("=" * 64)

    executor = DynamicExecutor(api_key=api_key)
    result = executor.execute(
        task=task,
        graph=planner_result.graph,
        budget_dollars=budget,
        planner_cost_dollars=planner_cost,
    )
    r = result.report

    print()
    for sr in r.subtask_results:
        attempts_str = " → ".join(
            f"{a.tier.value}({a.quality_score:.1f})" for a in sr.attempts
        )
        print(
            f"  [{sr.subtask_id}] {sr.tier.value:<6} │ "
            f"attempts: {attempts_str} │ "
            f"${sr.cost_dollars:.6f}"
        )

    if r.roi_decisions:
        print(f"\n  ROI Decisions:")
        for d in r.roi_decisions:
            print(
                f"    • Subtask {d.subtask_id}: {d.current_tier.value} → "
                f"{d.proposed_tier.value} | quality {d.current_quality:.1f} | "
                f"ROI {d.roi:.0f} | {d.decision}"
            )

    # ── Step 4: Evaluate & trace ─────────────────────────────────────────
    evaluator = EvaluatorAgent(api_key=api_key) if evaluate else None

    planner_trace = PlannerTrace(
        task=task,
        model=planner_result.model,
        prompt_tokens=planner_result.usage.prompt_tokens,
        completion_tokens=planner_result.usage.completion_tokens,
        total_tokens=planner_result.usage.total_tokens,
        cost_dollars=planner_cost,
        graph_json=planner_result.graph.model_dump_json(),
    )

    subtask_traces: list[SubTaskTrace] = []
    for sr in r.subtask_results:
        quality = None
        if evaluator and not sr.skipped and sr.output:
            try:
                quality = evaluator.evaluate_subtask(sr.description, sr.output, task)
            except Exception:
                pass
        text_metrics = compute_text_metrics(sr.output) if sr.output else None
        subtask_traces.append(
            SubTaskTrace(
                subtask_id=sr.subtask_id,
                description=sr.description,
                tier=sr.tier,
                model=sr.model,
                max_tokens=sr.tokens_budgeted,
                prompt=sr.prompt,
                output=sr.output,
                prompt_tokens=sr.prompt_tokens,
                completion_tokens=sr.completion_tokens,
                total_tokens=sr.total_tokens,
                cost_dollars=sr.cost_dollars,
                surplus=sr.surplus,
                skipped=sr.skipped,
                quality=quality,
                text_metrics=text_metrics,
            )
        )

    deliverable_quality = None
    if evaluator and result.deliverable:
        try:
            deliverable_quality = evaluator.evaluate_deliverable(task, result.deliverable)
        except Exception:
            pass

    trace = RunTrace(
        task=task,
        budget_dollars=budget,
        planner_trace=planner_trace,
        subtask_traces=subtask_traces,
        deliverable=result.deliverable,
        deliverable_quality=deliverable_quality,
        total_cost_dollars=r.spent_dollars,
        evaluation_cost_dollars=evaluator.total_cost_dollars if evaluator else 0.0,
    )
    save_trace(trace)

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
    print(f"    Upgrades: {r.total_upgrades}  │  Eval cost: ${r.evaluation_cost_dollars:.6f}")

    print(f"\n  Efficiency")
    print(f"    Tokens budgeted:  {r.total_tokens_budgeted:,}")
    print(f"    Tokens consumed:  {r.total_tokens_consumed:,}")
    print(f"    Total surplus:    {r.total_surplus:,}")
    print(f"    Token efficiency: {r.token_efficiency_pct:.1f}%")

    print(f"\n  Task Graph")
    print(f"    Subtasks: {r.total_subtasks}  │  Max depth: {r.max_depth}  │  "
          f"Parallelizable: {r.parallelizable_subtasks}")
    print(f"    Complexity: {r.complexity_distribution}")

    if deliverable_quality:
        print(f"\n  Quality (LLM-as-judge)")
        print(f"    Relevance:    {deliverable_quality.relevance:.1f}/10")
        print(f"    Completeness: {deliverable_quality.completeness:.1f}/10")
        print(f"    Coherence:    {deliverable_quality.coherence:.1f}/10")
        print(f"    Conciseness:  {deliverable_quality.conciseness:.1f}/10")
        print(f"    Overall:      {deliverable_quality.overall:.1f}/10")
        print(f"    Rationale:    {deliverable_quality.rationale}")

    if evaluator:
        print(f"\n  Evaluation cost: ${evaluator.total_cost_dollars:.6f} "
              f"({evaluator.total_tokens_used} tokens)")

    # Text metrics for the deliverable
    if result.deliverable:
        dm = compute_text_metrics(result.deliverable)
        print(f"\n  Deliverable Text Metrics")
        print(f"    Words:            {dm.word_count}")
        print(f"    Type-token ratio: {dm.type_token_ratio:.3f}")
        print(f"    Compression:      {dm.compression_ratio:.3f}")
        print(f"    N-gram repeat:    {dm.ngram_repetition_rate:.3f}")
        print(f"    Avg sent length:  {dm.avg_sentence_length:.1f} words")
        print(f"    Filler phrases:   {dm.filler_phrase_count}")

    print(f"\n  Wall time: {elapsed:.1f}s")
    print(f"  Trace saved: {trace.run_id}")

    # ── Deliverable ──────────────────────────────────────────────────────
    print()
    print("=" * 64)
    print("DELIVERABLE")
    print("=" * 64)
    print()
    print(result.deliverable)


def _run_batch(api_key: str, task: str, budgets: list[float],
               concurrency: int, evaluate: bool) -> None:
    """Batch mode: sweep multiple budgets and print a comparison table."""
    print(f"Task:     {task}")
    print(f"Budgets:  {', '.join(f'${b:.4f}' for b in budgets)}")
    print(f"Workers:  {concurrency}")
    print()

    t0 = time.time()
    traces = run_batch(
        api_key=api_key,
        task=task,
        budgets=budgets,
        max_concurrency=concurrency,
        evaluate=evaluate,
    )
    elapsed = time.time() - t0

    # ── Comparison table ─────────────────────────────────────────────────
    print()
    print("=" * 80)
    print("BATCH COMPARISON")
    print("=" * 80)

    header = (
        f"  {'Budget':>8}  {'Spent':>10}  {'Quality':>7}  "
        f"{'TTR':>5}  {'Compress':>8}  {'Ngram%':>6}  {'Fillers':>7}  {'Words':>6}"
    )
    print(header)
    print(f"  {'─'*8}  {'─'*10}  {'─'*7}  {'─'*5}  {'─'*8}  {'─'*6}  {'─'*7}  {'─'*6}")

    for tr in traces:
        qual = tr.deliverable_quality.overall if tr.deliverable_quality else -1.0
        dm = compute_text_metrics(tr.deliverable) if tr.deliverable else None
        print(
            f"  ${tr.budget_dollars:>7.4f}"
            f"  ${tr.total_cost_dollars:>9.6f}"
            f"  {qual:>6.1f}"
            f"  {dm.type_token_ratio if dm else 0:>5.3f}"
            f"  {dm.compression_ratio if dm else 0:>8.3f}"
            f"  {dm.ngram_repetition_rate * 100 if dm else 0:>5.1f}%"
            f"  {dm.filler_phrase_count if dm else 0:>7}"
            f"  {dm.word_count if dm else 0:>6}"
        )

    print(f"\n  Wall time: {elapsed:.1f}s")
    print(f"  Traces saved: {len(traces)}")


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    args = _parse_args()

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        sys.exit("GOOGLE_API_KEY not set in environment or .env file")

    task = args.task or "Research and write a blog post about the best AI startups in 2025"
    evaluate = not args.no_eval

    if args.batch:
        budgets = [float(b.strip()) for b in args.budgets.split(",")]
        _run_batch(api_key, task, budgets, args.concurrency, evaluate)
    else:
        budget = args.budget or float(os.getenv("BUDGET_DOLLARS", "0.08"))
        _run_single(api_key, task, budget, evaluate)


if __name__ == "__main__":
    main()
