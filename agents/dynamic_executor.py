"""Dynamic ROI-driven executor.

Replaces the static Allocator + Executor pipeline. Every subtask starts at
the cheapest tier (FAST) and is upgraded only when the quality gate fails
AND the marginal ROI justifies the spend.
"""

from __future__ import annotations

import logging
from collections import defaultdict

from CAL.llm import LLM

from agents.evaluator import EvaluatorAgent
from llm_provider import extract_response, make_user_message
from models import (
    TIER_MAX_TOKENS,
    TIER_MODELS,
    TIER_PRICING_PER_1M_INPUT,
    TIER_PRICING_PER_1M_OUTPUT,
    CostReport,
    ExecutorResult,
    ROIDecision,
    SubTaskAttempt,
    SubTaskResult,
    TaskGraph,
    Tier,
)

logger = logging.getLogger(__name__)

TIER_LADDER: list[Tier] = [Tier.FAST, Tier.VERIFY, Tier.DEEP]

EXPECTED_LIFT: dict[tuple[Tier, Tier], float] = {
    (Tier.FAST, Tier.VERIFY): 2.0,
    (Tier.VERIFY, Tier.DEEP): 1.5,
    (Tier.FAST, Tier.DEEP): 3.0,
}

QUALITY_THRESHOLD = 6.0
MIN_ROI = 50.0
SYNTHESIS_RESERVE_FRACTION = 0.35


def _topological_sort(graph: TaskGraph) -> list[int]:
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


def _estimate_cost(tier: Tier) -> float:
    """Worst-case cost for one subtask call at *tier* (output only)."""
    return TIER_MAX_TOKENS[tier] * TIER_PRICING_PER_1M_OUTPUT[tier] / 1_000_000


def _actual_cost(prompt_tokens: int, completion_tokens: int, tier: Tier) -> float:
    inp = prompt_tokens * TIER_PRICING_PER_1M_INPUT[tier] / 1_000_000
    out = completion_tokens * TIER_PRICING_PER_1M_OUTPUT[tier] / 1_000_000
    return inp + out


def _build_context(
    task: str,
    subtask_desc: str,
    dep_ids: list[int],
    outputs: dict[int, str],
) -> str:
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


def _max_dag_depth(graph: TaskGraph) -> int:
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
    return sum(1 for s in graph.subtasks if not s.dependencies)


class DynamicExecutor:
    """ROI-driven executor that starts cheap and upgrades on evidence.

    For each subtask:
      1. Run at FAST tier.
      2. Evaluate quality via a cheap LLM call.
      3. If quality < threshold, compute ROI of upgrading to the next tier.
      4. Upgrade if ROI exceeds minimum and budget permits; otherwise accept.
    """

    def __init__(self, tier_llms: dict[Tier, LLM], api_key: str):
        self.tier_llms = tier_llms
        self.evaluator = EvaluatorAgent(api_key=api_key)

    def execute(
        self,
        task: str,
        graph: TaskGraph,
        budget_dollars: float,
        planner_cost_dollars: float = 0.0,
    ) -> ExecutorResult:
        subtask_map = {s.id: s for s in graph.subtasks}
        order = _topological_sort(graph)
        final_id = order[-1] if order else None

        remaining_total = budget_dollars - planner_cost_dollars
        synthesis_reserve = remaining_total * SYNTHESIS_RESERVE_FRACTION
        upstream_budget = remaining_total - synthesis_reserve

        outputs: dict[int, str] = {}
        results: list[SubTaskResult] = []
        all_roi_decisions: list[ROIDecision] = []
        total_spent = planner_cost_dollars
        upstream_spent = 0.0
        total_upgrades = 0

        for sid in order:
            subtask = subtask_map[sid]
            is_final = sid == final_id

            if is_final:
                available = budget_dollars - total_spent
            else:
                available = min(
                    upstream_budget - upstream_spent,
                    budget_dollars - total_spent,
                )

            prompt = _build_context(
                task, subtask.description, subtask.dependencies, outputs,
            )

            tier_idx = 0
            attempts: list[SubTaskAttempt] = []
            decisions: list[ROIDecision] = []
            subtask_cost = 0.0

            while tier_idx < len(TIER_LADDER):
                tier = TIER_LADDER[tier_idx]
                max_tokens = TIER_MAX_TOKENS[tier]
                est = _estimate_cost(tier)

                if est > available:
                    if not attempts:
                        logger.warning(
                            "Subtask %d: cannot afford tier %s ($%.6f > $%.6f available)",
                            sid, tier.value, est, available,
                        )
                    break

                logger.info(
                    "Subtask %d → %s (%s, max_tokens=%d)",
                    sid, tier.value, TIER_MODELS[tier], max_tokens,
                )

                llm = self.tier_llms[tier]
                llm.max_tokens = max_tokens
                response = llm.generate_content(
                    system_prompt="",
                    conversation_history=[make_user_message(prompt)],
                )

                output_text, p_tok, c_tok, _ = extract_response(response)
                cost = _actual_cost(p_tok, c_tok, tier)

                score, reason = self.evaluator.quick_score(
                    subtask.description, output_text, task,
                )

                attempt = SubTaskAttempt(
                    tier=tier,
                    model=TIER_MODELS[tier],
                    output=output_text,
                    quality_score=score,
                    cost_dollars=cost,
                    prompt_tokens=p_tok,
                    completion_tokens=c_tok,
                )
                attempts.append(attempt)
                subtask_cost += cost
                available -= cost

                logger.info(
                    "Subtask %d @ %s: quality %.1f/10 ($%.6f) — %s",
                    sid, tier.value, score, cost, reason,
                )

                if score >= QUALITY_THRESHOLD:
                    break

                if tier_idx + 1 < len(TIER_LADDER):
                    next_tier = TIER_LADDER[tier_idx + 1]
                    upgrade_est = _estimate_cost(next_tier)
                    lift = EXPECTED_LIFT.get(
                        (tier, next_tier),
                        EXPECTED_LIFT.get((Tier.FAST, Tier.VERIFY), 2.0),
                    )
                    roi = lift / upgrade_est if upgrade_est > 0 else 0.0

                    if roi >= MIN_ROI and upgrade_est <= available:
                        decision = ROIDecision(
                            subtask_id=sid,
                            current_tier=tier,
                            current_quality=score,
                            proposed_tier=next_tier,
                            upgrade_cost_estimate=upgrade_est,
                            expected_quality_lift=lift,
                            roi=round(roi, 1),
                            decision="upgrade",
                            reason=(
                                f"Quality {score:.1f} < {QUALITY_THRESHOLD}, "
                                f"ROI {roi:.0f} >= {MIN_ROI} — upgrading"
                            ),
                        )
                        decisions.append(decision)
                        all_roi_decisions.append(decision)
                        total_upgrades += 1
                        logger.info(
                            "Subtask %d: UPGRADE %s → %s (ROI %.0f)",
                            sid, tier.value, next_tier.value, roi,
                        )
                        tier_idx += 1
                        continue
                    else:
                        if upgrade_est > available:
                            dec_type = "budget_exceeded"
                            dec_reason = (
                                f"Quality {score:.1f} < {QUALITY_THRESHOLD}, "
                                f"but upgrade cost ${upgrade_est:.6f} > "
                                f"${available:.6f} available"
                            )
                        else:
                            dec_type = "accept"
                            dec_reason = (
                                f"Quality {score:.1f} < {QUALITY_THRESHOLD}, "
                                f"ROI {roi:.0f} < {MIN_ROI} — not worth upgrading"
                            )
                        decision = ROIDecision(
                            subtask_id=sid,
                            current_tier=tier,
                            current_quality=score,
                            proposed_tier=next_tier,
                            upgrade_cost_estimate=upgrade_est,
                            expected_quality_lift=lift,
                            roi=round(roi, 1),
                            decision=dec_type,
                            reason=dec_reason,
                        )
                        decisions.append(decision)
                        all_roi_decisions.append(decision)
                break

            best = max(attempts, key=lambda a: a.quality_score) if attempts else None
            best_idx = attempts.index(best) if best else 0

            if best:
                outputs[sid] = best.output
                final_tier = best.tier
            else:
                outputs[sid] = ""
                final_tier = Tier.FAST

            total_prompt = sum(a.prompt_tokens for a in attempts)
            total_comp = sum(a.completion_tokens for a in attempts)
            total_tok = total_prompt + total_comp

            total_spent += subtask_cost
            if not is_final:
                upstream_spent += subtask_cost

            results.append(
                SubTaskResult(
                    subtask_id=sid,
                    description=subtask.description,
                    tier=final_tier,
                    model=TIER_MODELS[final_tier],
                    tokens_budgeted=TIER_MAX_TOKENS[final_tier],
                    prompt_tokens=total_prompt,
                    completion_tokens=total_comp,
                    total_tokens=total_tok,
                    cost_dollars=subtask_cost,
                    surplus=0,
                    output=best.output if best else "",
                    prompt=prompt,
                    attempts=attempts,
                    roi_decisions=decisions,
                    final_attempt_index=best_idx,
                )
            )

            logger.info(
                "Subtask %d: accepted @ %s, %d attempts, $%.6f total",
                sid, final_tier.value, len(attempts), subtask_cost,
            )

        deliverable = self._pick_deliverable(order, outputs)
        report = self._build_report(
            graph, results, planner_cost_dollars, total_spent,
            budget_dollars, all_roi_decisions, total_upgrades,
        )

        return ExecutorResult(deliverable=deliverable, report=report)

    @staticmethod
    def _pick_deliverable(order: list[int], outputs: dict[int, str]) -> str:
        parts = [outputs[sid] for sid in order if sid in outputs and outputs[sid]]
        if not parts:
            return "(No output produced — budget may have been insufficient.)"
        return "\n\n".join(parts)

    def _build_report(
        self,
        graph: TaskGraph,
        results: list[SubTaskResult],
        planner_cost: float,
        total_spent: float,
        budget: float,
        roi_decisions: list[ROIDecision],
        total_upgrades: int,
    ) -> CostReport:
        remaining = budget - total_spent
        utilization = (total_spent / budget * 100) if budget > 0 else 0.0

        tier_counts: dict[str, int] = {"fast": 0, "deep": 0, "verify": 0}
        for r in results:
            tier_counts[r.tier.value] = tier_counts.get(r.tier.value, 0) + 1

        tok_budgeted = sum(r.tokens_budgeted for r in results)
        tok_consumed = sum(r.completion_tokens for r in results)
        tok_surplus = sum(r.surplus for r in results)
        tok_efficiency = (tok_consumed / tok_budgeted * 100) if tok_budgeted > 0 else 0.0

        complexity_dist: dict[str, int] = {"low": 0, "medium": 0, "high": 0}
        for s in graph.subtasks:
            complexity_dist[s.complexity.value] += 1

        upgrade_descriptions = [
            f"Subtask {d.subtask_id}: {d.current_tier.value} → {d.proposed_tier.value} "
            f"(quality {d.current_quality:.1f}, ROI {d.roi:.0f})"
            for d in roi_decisions
            if d.decision == "upgrade"
        ]

        return CostReport(
            budget_dollars=budget,
            spent_dollars=total_spent,
            remaining_dollars=remaining,
            utilization_pct=utilization,
            subtask_results=results,
            tier_counts=tier_counts,
            subtasks_skipped=0,
            subtasks_downgraded=0,
            downgrades_applied=upgrade_descriptions,
            total_tokens_budgeted=tok_budgeted,
            total_tokens_consumed=tok_consumed,
            total_surplus=tok_surplus,
            token_efficiency_pct=tok_efficiency,
            total_subtasks=len(graph.subtasks),
            max_depth=_max_dag_depth(graph),
            parallelizable_subtasks=_parallelizable_count(graph),
            complexity_distribution=complexity_dist,
            total_upgrades=total_upgrades,
            roi_decisions=roi_decisions,
            evaluation_cost_dollars=self.evaluator.total_cost_dollars,
        )
