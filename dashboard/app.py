from __future__ import annotations

import os
import sys
from pathlib import Path

from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv

# Allow imports from the project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from agents.allocator import AllocatorAgent
from agents.executor import ExecutorAgent
from agents.planner import PlannerAgent
from models import (
    COMPLEXITY_TO_TIER,
    TIER_PRICING_PER_1M_INPUT,
    TIER_PRICING_PER_1M_OUTPUT,
    CostReport,
    ExecutionPlan,
    ExecutorResult,
    PlannerResult,
    TaskGraph,
    Tier,
)

app = Flask(__name__)
CORS(app)

latest_report: dict | None = None


def _planner_cost(prompt_tokens: int, completion_tokens: int) -> float:
    tier = Tier.VERIFY
    return (
        prompt_tokens * TIER_PRICING_PER_1M_INPUT[tier] / 1_000_000
        + completion_tokens * TIER_PRICING_PER_1M_OUTPUT[tier] / 1_000_000
    )


def _short_label(description: str, max_words: int = 3) -> str:
    """Extract a short label from a subtask description."""
    words = description.split()
    label = " ".join(words[:max_words])
    if len(words) > max_words:
        label += "…"
    return label


def _to_frontend_json(
    task: str,
    budget: float,
    planner_result: PlannerResult,
    plan: ExecutionPlan,
    result: ExecutorResult,
) -> dict:
    """Transform our backend models to the JSON shape the frontend expects."""
    r = result.report
    graph = planner_result.graph
    subtask_map = {s.id: s for s in graph.subtasks}

    # 1. Budget summary (frontend expects utilization as 0-1 ratio)
    budget_summary = {
        "dollar_budget": r.budget_dollars,
        "dollar_spent": r.spent_dollars,
        "dollar_remaining": r.remaining_dollars,
        "budget_utilization": r.utilization_pct / 100.0,
    }

    # 2. Per-subtask metrics
    subtask_metrics = []
    for sr in r.subtask_results:
        subtask_metrics.append({
            "subtask_id": sr.subtask_id,
            "name": _short_label(sr.description),
            "tier": sr.tier.value,
            "tokens_budgeted": sr.tokens_budgeted,
            "tokens_consumed": sr.completion_tokens,
            "cost_dollars": sr.cost_dollars,
            "surplus_returned": sr.surplus,
        })

    # 3. Tier distribution
    total_active = sum(1 for sr in r.subtask_results if not sr.skipped)
    tier_distribution = []
    for tier_name, count in r.tier_counts.items():
        if count > 0:
            tier_distribution.append({
                "tier": tier_name,
                "count": count,
                "percentage": (count / total_active * 100) if total_active > 0 else 0,
            })

    # 4. Downgrade report
    downgrades_list = []
    skipped_names = []
    for sr in r.subtask_results:
        st = subtask_map[sr.subtask_id]
        default_tier = COMPLEXITY_TO_TIER[st.complexity]
        if sr.skipped:
            skipped_names.append(_short_label(sr.description))
        elif sr.tier != default_tier:
            downgrades_list.append({
                "subtask_id": sr.subtask_id,
                "name": _short_label(sr.description),
                "original_tier": default_tier.value,
                "final_tier": sr.tier.value,
            })

    downgrade_report = {
        "original_plan_cost": plan.total_estimated_cost_dollars,
        "final_plan_cost": r.spent_dollars,
        "downgrades": downgrades_list,
        "subtasks_skipped": skipped_names,
    }

    # 5. Efficiency stats
    efficiency_stats = {
        "total_tokens_budgeted": r.total_tokens_budgeted,
        "total_tokens_consumed": r.total_tokens_consumed,
        "total_surplus_generated": r.total_surplus,
        "token_efficiency": r.token_efficiency_pct,
    }

    # 6. Task graph summary (capitalize complexity keys)
    complexity_dist = {
        k.capitalize(): v for k, v in r.complexity_distribution.items()
    }
    task_graph_summary = {
        "total_subtasks": r.total_subtasks,
        "max_depth": r.max_depth,
        "parallelizable_subtasks": r.parallelizable_subtasks,
        "complexity_distribution": complexity_dist,
    }

    # 7. DAG for the SVG graph
    dag_nodes = []
    for s in graph.subtasks:
        dag_nodes.append({
            "id": s.id,
            "label": _short_label(s.description),
            "complexity": s.complexity.value.capitalize(),
        })

    dag_edges = []
    for s in graph.subtasks:
        for dep in s.dependencies:
            dag_edges.append({"from": dep, "to": s.id})

    return {
        "budget_summary": budget_summary,
        "subtask_metrics": subtask_metrics,
        "tier_distribution": tier_distribution,
        "downgrade_report": downgrade_report,
        "efficiency_stats": efficiency_stats,
        "task_graph_summary": task_graph_summary,
        "dag": {"nodes": dag_nodes, "edges": dag_edges},
        "task_input": task,
        "budget_input": budget,
        "deliverable": result.deliverable,
    }


@app.route("/api/run", methods=["POST"])
def run():
    global latest_report

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return jsonify({"error": "GOOGLE_API_KEY not configured"}), 500

    data = request.get_json(silent=True) or {}
    task = data.get("task", "").strip()
    budget = float(data.get("budget", 0.08))

    if not task:
        return jsonify({"error": "task is required"}), 400
    if budget <= 0:
        return jsonify({"error": "budget must be positive"}), 400

    # Step 1 — Plan
    planner = PlannerAgent(api_key=api_key)
    planner_result = planner.plan(task)
    planner_cost = _planner_cost(
        planner_result.usage.prompt_tokens,
        planner_result.usage.completion_tokens,
    )

    # Step 2 — Allocate
    allocator = AllocatorAgent()
    plan = allocator.allocate(
        graph=planner_result.graph,
        budget_dollars=budget,
        spent_dollars=planner_cost,
    )

    # Step 3 — Execute
    executor = ExecutorAgent(api_key=api_key)
    result = executor.execute(
        task=task,
        graph=planner_result.graph,
        plan=plan,
        planner_cost_dollars=planner_cost,
    )

    frontend_json = _to_frontend_json(task, budget, planner_result, plan, result)
    latest_report = frontend_json
    return jsonify(frontend_json)


@app.route("/api/report")
def api_report():
    if latest_report is None:
        return jsonify({"error": "No report available. Run a task first."}), 404
    return jsonify(latest_report)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
