from __future__ import annotations

import logging
from collections import defaultdict

from google import genai
from google.genai import types

from models import (
    TIER_MAX_TOKENS,
    TIER_PRICING_PER_1M_INPUT,
    TIER_PRICING_PER_1M_OUTPUT,
    Complexity,
    CostReport,
    ExecutionPlan,
    ExecutorResult,
    SubTaskAllocation,
    SubTaskResult,
    TaskGraph,
    Tier,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _topological_sort(graph: TaskGraph) -> list[int]:
    """Return subtask IDs in dependency-respecting execution order."""
    adj: dict[int, list[int]] = {s.id: list(s.dependencies) for s in graph.subtasks}
    in_degree: dict[int, int] = {s.id: 0 for s in graph.subtasks}
    for s in graph.subtasks:
        for dep in s.dependencies:
            in_degree[s.id] += 1

    queue = [sid for sid, deg in in_degree.items() if deg == 0]
    order: list[int] = []

    dependents: dict[int, list[int]] = defaultdict(list)
    for s in graph.subtasks:
        for dep in s.dependencies:
            dependents[dep].append(s.id)

    while queue:
        queue.sort()
        sid = queue.pop(0)
        order.append(sid)
        for child in dependents[sid]:
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append(child)

    return order


def _build_context(
    task: str,
    subtask_desc: str,
    dep_ids: list[int],
    outputs: dict[int, str],
) -> str:
    """Build the prompt sent to a tier agent."""
    parts = [f"OVERALL TASK: {task}\n", f"YOUR SUBTASK: {subtask_desc}\n"]

    if dep_ids:
        parts.append("CONTEXT FROM PRIOR SUBTASKS:\n")
        for did in dep_ids:
            text = outputs.get(did, "")
            if text:
                parts.append(f"--- Subtask {did} output ---\n{text}\n")

    parts.append(
        "Produce a thorough, high-quality response for YOUR SUBTASK. "
        "Use the context above where relevant but DO NOT repeat or "
        "restate content from prior subtasks — produce only NEW content."
    )
    return "\n".join(parts)


def _subtask_cost(
    prompt_tokens: int, completion_tokens: int, tier: Tier
) -> float:
    """Compute actual dollar cost from token counts at tier pricing."""
    input_cost = prompt_tokens * TIER_PRICING_PER_1M_INPUT[tier] / 1_000_000
    output_cost = completion_tokens * TIER_PRICING_PER_1M_OUTPUT[tier] / 1_000_000
    return input_cost + output_cost


def _max_dag_depth(graph: TaskGraph) -> int:
    """Longest path through the DAG (number of edges)."""
    subtask_map = {s.id: s for s in graph.subtasks}
    cache: dict[int, int] = {}

    def depth(sid: int) -> int:
        if sid in cache:
            return cache[sid]
        deps = subtask_map[sid].dependencies
        if not deps:
            cache[sid] = 0
            return 0
        d = 1 + max(depth(d) for d in deps)
        cache[sid] = d
        return d

    return max(depth(s.id) for s in graph.subtasks) if graph.subtasks else 0


def _parallelizable_count(graph: TaskGraph) -> int:
    """Count subtasks with no dependencies (could run concurrently)."""
    return sum(1 for s in graph.subtasks if not s.dependencies)


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


class ExecutorAgent:
    """Walks the task DAG, dispatches subtasks to tier models, and tracks costs.

    After each subtask completes the executor:
      1. Logs actual tokens consumed (track_usage)
      2. Returns surplus tokens to the pool (reallocate_surplus)
      3. Opportunistically boosts downstream token caps from the surplus

    At the end it assembles the full CostReport (build_report).
    """

    def __init__(self, api_key: str):
        self.client = genai.Client(api_key=api_key)

    def execute(
        self,
        task: str,
        graph: TaskGraph,
        plan: ExecutionPlan,
        planner_cost_dollars: float = 0.0,
    ) -> ExecutorResult:
        alloc_map = {a.subtask_id: a for a in plan.allocations}
        subtask_map = {s.id: s for s in graph.subtasks}

        outputs: dict[int, str] = {}
        results: list[SubTaskResult] = []
        surplus_pool = 0
        total_spent = planner_cost_dollars

        order = _topological_sort(graph)

        for sid in order:
            alloc = alloc_map[sid]
            subtask = subtask_map[sid]

            # --- Skip if allocator dropped this subtask ----------------------
            if alloc.skipped:
                results.append(
                    SubTaskResult(
                        subtask_id=sid,
                        description=subtask.description,
                        tier=alloc.tier,
                        model=alloc.model,
                        tokens_budgeted=0,
                        prompt_tokens=0,
                        completion_tokens=0,
                        total_tokens=0,
                        cost_dollars=0.0,
                        surplus=0,
                        output="",
                        skipped=True,
                    )
                )
                logger.info("Subtask %d: skipped by allocator", sid)
                continue

            # --- Surplus redistribution (opportunistic) ----------------------
            tier_max = TIER_MAX_TOKENS[alloc.tier]
            if surplus_pool > 0 and alloc.max_tokens < tier_max:
                boost = min(surplus_pool, tier_max - alloc.max_tokens)
                alloc.max_tokens += boost
                surplus_pool -= boost
                logger.info(
                    "Subtask %d: boosted max_tokens by %d from surplus (now %d)",
                    sid, boost, alloc.max_tokens,
                )

            # --- Build prompt and dispatch -----------------------------------
            prompt = _build_context(
                task,
                subtask.description,
                subtask.dependencies,
                outputs,
            )

            logger.info(
                "Subtask %d → %s (%s, max_tokens=%d)",
                sid, alloc.tier.value, alloc.model, alloc.max_tokens,
            )

            response = self.client.models.generate_content(
                model=alloc.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    max_output_tokens=alloc.max_tokens,
                    temperature=0.4,
                ),
            )

            output_text = response.text or ""
            outputs[sid] = output_text

            # --- Track usage -------------------------------------------------
            prompt_tokens = response.usage_metadata.prompt_token_count or 0
            completion_tokens = response.usage_metadata.candidates_token_count or 0
            total_tokens = response.usage_metadata.total_token_count or 0

            cost = _subtask_cost(prompt_tokens, completion_tokens, alloc.tier)
            total_spent += cost

            surplus = max(0, alloc.max_tokens - completion_tokens)
            surplus_pool += surplus

            results.append(
                SubTaskResult(
                    subtask_id=sid,
                    description=subtask.description,
                    tier=alloc.tier,
                    model=alloc.model,
                    tokens_budgeted=alloc.max_tokens,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    cost_dollars=cost,
                    surplus=surplus,
                    output=output_text,
                    prompt=prompt,
                )
            )

            logger.info(
                "Subtask %d: consumed %d tokens ($%.6f), surplus %d",
                sid, total_tokens, cost, surplus,
            )

        # --- Build report ----------------------------------------------------
        deliverable = self._pick_deliverable(order, results, outputs)
        report = self._build_report(
            graph, plan, results, planner_cost_dollars, total_spent,
        )

        return ExecutorResult(deliverable=deliverable, report=report)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _pick_deliverable(
        order: list[int],
        results: list[SubTaskResult],
        outputs: dict[int, str],
    ) -> str:
        """Concatenate all subtask outputs in execution order."""
        parts = [outputs[sid] for sid in order if sid in outputs and outputs[sid]]
        if not parts:
            return "(No output produced — budget may have been insufficient.)"
        return "\n\n".join(parts)

    @staticmethod
    def _build_report(
        graph: TaskGraph,
        plan: ExecutionPlan,
        results: list[SubTaskResult],
        planner_cost: float,
        total_spent: float,
    ) -> CostReport:
        budget = plan.budget_dollars
        remaining = budget - total_spent
        utilization = (total_spent / budget * 100) if budget > 0 else 0.0

        # Tier distribution
        tier_counts: dict[str, int] = {"fast": 0, "deep": 0, "verify": 0}
        for r in results:
            if not r.skipped:
                tier_counts[r.tier.value] = tier_counts.get(r.tier.value, 0) + 1

        skipped = sum(1 for r in results if r.skipped)
        downgraded = len(plan.downgrades_applied)

        # Efficiency (compared against completion tokens since budget = max output)
        tok_budgeted = sum(r.tokens_budgeted for r in results)
        tok_consumed = sum(r.completion_tokens for r in results)
        tok_surplus = sum(r.surplus for r in results)
        tok_efficiency = (tok_consumed / tok_budgeted * 100) if tok_budgeted > 0 else 0.0

        # Task graph summary
        complexity_dist: dict[str, int] = {"low": 0, "medium": 0, "high": 0}
        for s in graph.subtasks:
            complexity_dist[s.complexity.value] += 1

        return CostReport(
            budget_dollars=budget,
            spent_dollars=total_spent,
            remaining_dollars=remaining,
            utilization_pct=utilization,
            subtask_results=results,
            tier_counts=tier_counts,
            subtasks_skipped=skipped,
            subtasks_downgraded=downgraded,
            downgrades_applied=plan.downgrades_applied,
            total_tokens_budgeted=tok_budgeted,
            total_tokens_consumed=tok_consumed,
            total_surplus=tok_surplus,
            token_efficiency_pct=tok_efficiency,
            total_subtasks=len(graph.subtasks),
            max_depth=_max_dag_depth(graph),
            parallelizable_subtasks=_parallelizable_count(graph),
            complexity_distribution=complexity_dist,
        )
