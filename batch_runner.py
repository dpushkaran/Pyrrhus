"""Run the pipeline at multiple budget levels and collect traces."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from agents.allocator import AllocatorAgent
from agents.evaluator import EvaluatorAgent
from agents.executor import ExecutorAgent
from agents.planner import PlannerAgent
from analysis.text_metrics import compute_text_metrics
from analysis.trace_store import save_trace
from llm_provider import create_tier_llms
from models import (
    TIER_PRICING_PER_1M_INPUT,
    TIER_PRICING_PER_1M_OUTPUT,
    PlannerResult,
    PlannerTrace,
    RunTrace,
    SubTaskTrace,
    Tier,
)

logger = logging.getLogger(__name__)


def _planner_cost(result: PlannerResult) -> float:
    tier = Tier.VERIFY
    return (
        result.usage.prompt_tokens * TIER_PRICING_PER_1M_INPUT[tier] / 1_000_000
        + result.usage.completion_tokens * TIER_PRICING_PER_1M_OUTPUT[tier] / 1_000_000
    )


def _build_trace(
    task: str,
    budget: float,
    planner_result: PlannerResult,
    planner_cost_dollars: float,
    executor_result,
    evaluator: Optional[EvaluatorAgent],
) -> RunTrace:
    """Assemble a RunTrace from pipeline outputs, optionally scoring quality."""
    planner_trace = PlannerTrace(
        task=task,
        model=planner_result.model,
        prompt_tokens=planner_result.usage.prompt_tokens,
        completion_tokens=planner_result.usage.completion_tokens,
        total_tokens=planner_result.usage.total_tokens,
        cost_dollars=planner_cost_dollars,
        graph_json=planner_result.graph.model_dump_json(),
    )

    subtask_traces: list[SubTaskTrace] = []
    for sr in executor_result.report.subtask_results:
        quality = None
        if evaluator and not sr.skipped and sr.output:
            try:
                quality = evaluator.evaluate_subtask(
                    sr.description, sr.output, task
                )
            except Exception:
                logger.warning("Evaluator failed for subtask %d", sr.subtask_id, exc_info=True)

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
    if evaluator and executor_result.deliverable:
        try:
            deliverable_quality = evaluator.evaluate_deliverable(
                task, executor_result.deliverable
            )
        except Exception:
            logger.warning("Evaluator failed for deliverable", exc_info=True)

    return RunTrace(
        task=task,
        budget_dollars=budget,
        planner_trace=planner_trace,
        subtask_traces=subtask_traces,
        deliverable=executor_result.deliverable,
        deliverable_quality=deliverable_quality,
        total_cost_dollars=executor_result.report.spent_dollars,
        evaluation_cost_dollars=evaluator.total_cost_dollars if evaluator else 0.0,
    )


def run_single(
    api_key: str,
    task: str,
    budget: float,
    planner_result: PlannerResult,
    evaluate: bool = True,
    save: bool = True,
) -> RunTrace:
    """Execute the pipeline for one budget level using a pre-computed plan."""
    pc = _planner_cost(planner_result)

    allocator = AllocatorAgent()
    plan = allocator.allocate(
        graph=planner_result.graph,
        budget_dollars=budget,
        spent_dollars=pc,
    )

    tier_llms = create_tier_llms(api_key=api_key)
    executor = ExecutorAgent(tier_llms=tier_llms)
    result = executor.execute(
        task=task,
        graph=planner_result.graph,
        plan=plan,
        planner_cost_dollars=pc,
    )

    evaluator = EvaluatorAgent(api_key=api_key) if evaluate else None
    trace = _build_trace(task, budget, planner_result, pc, result, evaluator)

    if save:
        save_trace(trace)

    return trace


def run_batch(
    api_key: str,
    task: str,
    budgets: list[float],
    max_concurrency: int = 3,
    delay_between_launches: float = 1.0,
    evaluate: bool = True,
    save: bool = True,
) -> list[RunTrace]:
    """Run the pipeline at each budget level and return all traces.

    The planner is called once and shared across all runs so that
    budget is the only variable.
    """
    logger.info("Batch run: task=%r, budgets=%s", task, budgets)

    planner = PlannerAgent(api_key=api_key)
    planner_result = planner.plan(task)
    logger.info("Planner produced %d subtasks", len(planner_result.graph.subtasks))

    traces: list[RunTrace] = []

    def _run_one(budget: float) -> RunTrace:
        return run_single(
            api_key=api_key,
            task=task,
            budget=budget,
            planner_result=planner_result,
            evaluate=evaluate,
            save=save,
        )

    with ThreadPoolExecutor(max_workers=max_concurrency) as pool:
        futures = {}
        for i, b in enumerate(budgets):
            if i > 0:
                time.sleep(delay_between_launches)
            futures[pool.submit(_run_one, b)] = b

        for fut in as_completed(futures):
            budget = futures[fut]
            try:
                trace = fut.result()
                traces.append(trace)
                logger.info(
                    "Budget $%.4f done — quality %.1f, cost $%.6f",
                    budget,
                    trace.deliverable_quality.overall if trace.deliverable_quality else -1,
                    trace.total_cost_dollars,
                )
            except Exception:
                logger.error("Budget $%.4f failed", budget, exc_info=True)

    traces.sort(key=lambda t: t.budget_dollars)
    return traces
