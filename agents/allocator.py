from __future__ import annotations

import logging
from collections import defaultdict

from models import (
    COMPLEXITY_TO_TIER,
    TIER_MAX_TOKENS,
    TIER_MODELS,
    TIER_PRICING_PER_1M_OUTPUT,
    Complexity,
    ExecutionPlan,
    SubTask,
    SubTaskAllocation,
    TaskGraph,
    Tier,
)

logger = logging.getLogger(__name__)


def _estimate_cost(tokens: int, tier: Tier) -> float:
    """Estimate dollar cost for *tokens* output tokens at *tier* pricing."""
    return tokens * TIER_PRICING_PER_1M_OUTPUT[tier] / 1_000_000


def _criticality_order(graph: TaskGraph) -> list[int]:
    """Return subtask IDs sorted from **least** critical to **most** critical.

    Criticality proxy: the longest path from a subtask to any leaf node.
    Subtasks closer to the final deliverable (deeper in the DAG) are more
    critical and should be downgraded last.
    """
    subtask_map = {s.id: s for s in graph.subtasks}
    dependents: dict[int, list[int]] = defaultdict(list)
    for s in graph.subtasks:
        for dep in s.dependencies:
            dependents[dep].append(s.id)

    depth_cache: dict[int, int] = {}

    def max_depth(sid: int) -> int:
        if sid in depth_cache:
            return depth_cache[sid]
        children = dependents.get(sid, [])
        if not children:
            depth_cache[sid] = 0
            return 0
        d = 1 + max(max_depth(c) for c in children)
        depth_cache[sid] = d
        return d

    for s in graph.subtasks:
        max_depth(s.id)

    return sorted(depth_cache, key=lambda sid: depth_cache[sid])


class AllocatorAgent:
    """Routes subtasks to model tiers and enforces the dollar budget.

    Pure algorithmic logic — no LLM call. The budget is treated as a
    ceiling: the allocator intentionally builds in buffer so surplus can
    be redistributed downstream by the Executor.
    """

    def allocate(
        self,
        graph: TaskGraph,
        budget_dollars: float,
        spent_dollars: float = 0.0,
    ) -> ExecutionPlan:
        """Produce an ExecutionPlan for *graph* under *budget_dollars*.

        *spent_dollars* accounts for tokens already consumed (e.g. by the
        Planner) so the Allocator plans against the remaining budget.
        """
        remaining = budget_dollars - spent_dollars
        if remaining <= 0:
            raise ValueError(
                f"Budget exhausted before allocation: "
                f"${budget_dollars:.4f} budget, ${spent_dollars:.4f} already spent"
            )

        subtask_map = {s.id: s for s in graph.subtasks}
        crit_order = _criticality_order(graph)

        allocs: dict[int, SubTaskAllocation] = {}
        for s in graph.subtasks:
            tier = COMPLEXITY_TO_TIER[s.complexity]
            max_tok = TIER_MAX_TOKENS[tier]
            allocs[s.id] = SubTaskAllocation(
                subtask_id=s.id,
                tier=tier,
                model=TIER_MODELS[tier],
                max_tokens=max_tok,
                estimated_cost_dollars=_estimate_cost(max_tok, tier),
            )

        downgrades: list[str] = []

        # --- Downgrade pass 1: Deep → Verify (least critical first) ---------
        for sid in crit_order:
            if self._total_cost(allocs) <= remaining:
                break
            a = allocs[sid]
            if a.tier == Tier.DEEP and not a.skipped:
                self._set_tier(a, Tier.VERIFY)
                downgrades.append(
                    f"Subtask {sid}: Deep → Verify (budget pressure)"
                )

        # --- Downgrade pass 2: remaining Deep → Fast -------------------------
        for sid in crit_order:
            if self._total_cost(allocs) <= remaining:
                break
            a = allocs[sid]
            if a.tier == Tier.DEEP and not a.skipped:
                self._set_tier(a, Tier.FAST)
                downgrades.append(
                    f"Subtask {sid}: Deep → Fast (budget pressure)"
                )

        # --- Downgrade pass 3: skip least-critical Verify subtasks -----------
        for sid in crit_order:
            if self._total_cost(allocs) <= remaining:
                break
            a = allocs[sid]
            if a.tier == Tier.VERIFY and not a.skipped:
                a.skipped = True
                a.max_tokens = 0
                a.estimated_cost_dollars = 0.0
                downgrades.append(
                    f"Subtask {sid}: skipped (budget pressure)"
                )

        # --- Downgrade pass 4: proportional max_tokens reduction -------------
        if self._total_cost(allocs) > remaining:
            active = [a for a in allocs.values() if not a.skipped]
            current_cost = sum(a.estimated_cost_dollars for a in active)
            if current_cost > 0:
                scale = remaining / current_cost
                for a in active:
                    new_max = max(128, int(a.max_tokens * scale))
                    a.max_tokens = new_max
                    a.estimated_cost_dollars = _estimate_cost(new_max, a.tier)
                downgrades.append(
                    f"All subtasks: max_tokens scaled to {scale:.0%} (budget pressure)"
                )

        ordered_allocs = [allocs[s.id] for s in graph.subtasks]
        total_tokens = sum(a.max_tokens for a in ordered_allocs)
        total_cost = sum(a.estimated_cost_dollars for a in ordered_allocs)

        logger.info(
            "Allocator: %d subtasks, est $%.4f / $%.4f budget, %d downgrades",
            len(ordered_allocs),
            total_cost,
            remaining,
            len(downgrades),
        )

        return ExecutionPlan(
            allocations=ordered_allocs,
            total_estimated_tokens=total_tokens,
            total_estimated_cost_dollars=total_cost,
            budget_tokens=total_tokens,
            budget_dollars=budget_dollars,
            downgrades_applied=downgrades,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _total_cost(allocs: dict[int, SubTaskAllocation]) -> float:
        return sum(a.estimated_cost_dollars for a in allocs.values())

    @staticmethod
    def _set_tier(alloc: SubTaskAllocation, tier: Tier) -> None:
        alloc.tier = tier
        alloc.model = TIER_MODELS[tier]
        alloc.max_tokens = TIER_MAX_TOKENS[tier]
        alloc.estimated_cost_dollars = _estimate_cost(alloc.max_tokens, tier)
