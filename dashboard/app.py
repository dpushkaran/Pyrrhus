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

from agents.dynamic_executor import DynamicExecutor
from agents.evaluator import EvaluatorAgent
from agents.planner import PlannerAgent
from analysis.text_metrics import compute_text_metrics
from analysis.trace_store import load_traces, save_trace
from batch_runner import run_batch
from models import (
    COMPLEXITY_TO_TIER,
    TIER_PRICING_PER_1M_INPUT,
    TIER_PRICING_PER_1M_OUTPUT,
    CostReport,
    ExecutorResult,
    PlannerResult,
    PlannerTrace,
    ROIDecision,
    RunTrace,
    SubTaskTrace,
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
    result: ExecutorResult,
    subtask_qualities: dict | None = None,
    subtask_text_metrics: dict | None = None,
    deliverable_quality: dict | None = None,
    deliverable_text_metrics: dict | None = None,
    evaluation_cost: float = 0.0,
) -> dict:
    """Transform our backend models to the JSON shape the frontend expects."""
    r = result.report
    graph = planner_result.graph
    subtask_map = {s.id: s for s in graph.subtasks}
    sq = subtask_qualities or {}
    stm = subtask_text_metrics or {}

    budget_summary = {
        "dollar_budget": r.budget_dollars,
        "dollar_spent": r.spent_dollars,
        "dollar_remaining": r.remaining_dollars,
        "budget_utilization": r.utilization_pct / 100.0,
    }

    subtask_metrics = []
    for sr in r.subtask_results:
        entry: dict = {
            "subtask_id": sr.subtask_id,
            "name": _short_label(sr.description),
            "description": sr.description,
            "output": sr.output,
            "tier": sr.tier.value,
            "tokens_budgeted": sr.tokens_budgeted,
            "tokens_consumed": sr.completion_tokens,
            "cost_dollars": sr.cost_dollars,
            "surplus_returned": sr.surplus,
        }
        if sr.subtask_id in sq:
            entry["quality"] = sq[sr.subtask_id]
        if sr.subtask_id in stm:
            entry["text_metrics"] = stm[sr.subtask_id]
        if sr.attempts:
            entry["attempts"] = [
                {
                    "tier": a.tier.value,
                    "quality_score": a.quality_score,
                    "cost_dollars": a.cost_dollars,
                }
                for a in sr.attempts
            ]
        if sr.roi_decisions:
            entry["roi_decisions"] = [
                {
                    "subtask_id": d.subtask_id,
                    "current_tier": d.current_tier.value,
                    "current_quality": d.current_quality,
                    "proposed_tier": d.proposed_tier.value,
                    "upgrade_cost_estimate": d.upgrade_cost_estimate,
                    "expected_quality_lift": d.expected_quality_lift,
                    "roi": d.roi,
                    "decision": d.decision,
                    "reason": d.reason,
                }
                for d in sr.roi_decisions
            ]
        subtask_metrics.append(entry)

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

    # 4. Upgrade report (ROI-driven decisions)
    upgrade_decisions = []
    for d in r.roi_decisions:
        upgrade_decisions.append({
            "subtask_id": d.subtask_id,
            "current_tier": d.current_tier.value,
            "current_quality": d.current_quality,
            "proposed_tier": d.proposed_tier.value,
            "roi": d.roi,
            "decision": d.decision,
            "reason": d.reason,
        })

    upgrade_report = {
        "total_upgrades": r.total_upgrades,
        "evaluation_cost": r.evaluation_cost_dollars,
        "decisions": upgrade_decisions,
    }

    downgrade_report = None

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

    # 8. Savings comparison — what if every subtask ran at Deep tier?
    savings_items = []
    total_naive = 0.0
    total_actual = 0.0
    for sr in r.subtask_results:
        if sr.skipped:
            continue
        naive = (
            sr.prompt_tokens * TIER_PRICING_PER_1M_INPUT[Tier.DEEP] / 1_000_000
            + sr.completion_tokens * TIER_PRICING_PER_1M_OUTPUT[Tier.DEEP] / 1_000_000
        )
        actual = sr.cost_dollars
        savings_items.append({
            "subtask_id": sr.subtask_id,
            "name": _short_label(sr.description),
            "tier_used": sr.tier.value,
            "naive_cost": round(naive, 8),
            "actual_cost": round(actual, 8),
            "saved": round(naive - actual, 8),
        })
        total_naive += naive
        total_actual += actual

    savings = {
        "naive_total": round(total_naive, 8),
        "actual_total": round(total_actual, 8),
        "total_saved": round(total_naive - total_actual, 8),
        "savings_pct": round(
            (total_naive - total_actual) / total_naive * 100, 1
        ) if total_naive > 0 else 0,
        "items": savings_items,
        "explanation": (
            "Naive cost assumes every subtask runs at Deep tier "
            "(gemini-2.5-pro at $1.25/1M input, $10.00/1M output). "
            "Pyrrhus routes low-complexity work to cheaper tiers, "
            "saving money without sacrificing quality where it matters."
        ),
    }

    out = {
        "budget_summary": budget_summary,
        "subtask_metrics": subtask_metrics,
        "tier_distribution": tier_distribution,
        "downgrade_report": downgrade_report,
        "upgrade_report": upgrade_report,
        "efficiency_stats": efficiency_stats,
        "task_graph_summary": task_graph_summary,
        "dag": {"nodes": dag_nodes, "edges": dag_edges},
        "savings": savings,
        "task_input": task,
        "budget_input": budget,
        "deliverable": result.deliverable,
    }
    if deliverable_quality:
        out["deliverable_quality"] = deliverable_quality
    if deliverable_text_metrics:
        out["deliverable_text_metrics"] = deliverable_text_metrics
    if evaluation_cost > 0:
        out["evaluation_cost"] = evaluation_cost
    return out


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

    # Step 2 — Dynamic Execution (ROI-driven)
    executor = DynamicExecutor(api_key=api_key)
    result = executor.execute(
        task=task,
        graph=planner_result.graph,
        budget_dollars=budget,
        planner_cost_dollars=planner_cost,
    )

    # Step 4 — Evaluate quality and compute text metrics
    subtask_qualities: dict[int, dict] = {}
    subtask_text_metrics_map: dict[int, dict] = {}
    deliverable_quality_dict = None
    deliverable_tm_dict = None
    eval_cost = 0.0

    try:
        evaluator = EvaluatorAgent(api_key=api_key)
        planner_trace = PlannerTrace(
            task=task, model=planner_result.model,
            prompt_tokens=planner_result.usage.prompt_tokens,
            completion_tokens=planner_result.usage.completion_tokens,
            total_tokens=planner_result.usage.total_tokens,
            cost_dollars=planner_cost,
            graph_json=planner_result.graph.model_dump_json(),
        )
        subtask_traces = []
        for sr in result.report.subtask_results:
            quality = None
            if not sr.skipped and sr.output:
                try:
                    quality = evaluator.evaluate_subtask(sr.description, sr.output, task)
                    subtask_qualities[sr.subtask_id] = quality.model_dump()
                except Exception:
                    pass
            tm = compute_text_metrics(sr.output) if sr.output else None
            if tm:
                subtask_text_metrics_map[sr.subtask_id] = tm.model_dump()
            subtask_traces.append(SubTaskTrace(
                subtask_id=sr.subtask_id, description=sr.description,
                tier=sr.tier, model=sr.model, max_tokens=sr.tokens_budgeted,
                prompt=sr.prompt, output=sr.output,
                prompt_tokens=sr.prompt_tokens,
                completion_tokens=sr.completion_tokens,
                total_tokens=sr.total_tokens,
                cost_dollars=sr.cost_dollars, surplus=sr.surplus,
                skipped=sr.skipped, quality=quality, text_metrics=tm,
            ))
        deliverable_quality = None
        if result.deliverable:
            try:
                deliverable_quality = evaluator.evaluate_deliverable(task, result.deliverable)
                deliverable_quality_dict = deliverable_quality.model_dump()
            except Exception:
                pass
            dtm = compute_text_metrics(result.deliverable)
            deliverable_tm_dict = dtm.model_dump()

        eval_cost = evaluator.total_cost_dollars

        trace = RunTrace(
            task=task, budget_dollars=budget,
            planner_trace=planner_trace, subtask_traces=subtask_traces,
            deliverable=result.deliverable,
            deliverable_quality=deliverable_quality,
            total_cost_dollars=result.report.spent_dollars,
            evaluation_cost_dollars=eval_cost,
        )
        save_trace(trace)
    except Exception:
        pass

    frontend_json = _to_frontend_json(
        task, budget, planner_result, result,
        subtask_qualities=subtask_qualities,
        subtask_text_metrics=subtask_text_metrics_map,
        deliverable_quality=deliverable_quality_dict,
        deliverable_text_metrics=deliverable_tm_dict,
        evaluation_cost=eval_cost,
    )
    latest_report = frontend_json
    return jsonify(frontend_json)


@app.route("/api/report")
def api_report():
    if latest_report is None:
        return jsonify({"error": "No report available. Run a task first."}), 404
    return jsonify(latest_report)


@app.route("/api/batch", methods=["POST"])
def batch():
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return jsonify({"error": "GOOGLE_API_KEY not configured"}), 500

    data = request.get_json(silent=True) or {}
    task = data.get("task", "").strip()
    budgets = data.get("budgets", [0.01, 0.02, 0.04, 0.08, 0.16])
    concurrency = int(data.get("concurrency", 3))

    if not task:
        return jsonify({"error": "task is required"}), 400
    if not budgets or not isinstance(budgets, list):
        return jsonify({"error": "budgets must be a non-empty list"}), 400

    traces = run_batch(
        api_key=api_key,
        task=task,
        budgets=[float(b) for b in budgets],
        max_concurrency=concurrency,
        evaluate=True,
    )

    rows = []
    for tr in traces:
        dm = compute_text_metrics(tr.deliverable) if tr.deliverable else None
        rows.append({
            "run_id": tr.run_id,
            "budget": tr.budget_dollars,
            "spent": tr.total_cost_dollars,
            "quality": tr.deliverable_quality.overall if tr.deliverable_quality else None,
            "quality_scores": tr.deliverable_quality.model_dump() if tr.deliverable_quality else None,
            "text_metrics": dm.model_dump() if dm else None,
            "evaluation_cost": tr.evaluation_cost_dollars,
            "subtask_count": len(tr.subtask_traces),
            "skipped_count": sum(1 for s in tr.subtask_traces if s.skipped),
        })

    return jsonify({"task": task, "runs": rows})


@app.route("/api/traces")
def api_traces():
    traces = load_traces()
    summaries = []
    for tr in traces:
        summaries.append({
            "run_id": tr.run_id,
            "task": tr.task,
            "budget": tr.budget_dollars,
            "spent": tr.total_cost_dollars,
            "quality": tr.deliverable_quality.overall if tr.deliverable_quality else None,
            "subtask_count": len(tr.subtask_traces),
            "timestamp": tr.timestamp,
        })
    return jsonify(summaries)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from compare import compare_bp
    app.register_blueprint(compare_bp)
    app.run(debug=True, port=5001)
