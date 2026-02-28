from __future__ import annotations

import sys
from pathlib import Path

from flask import Flask, jsonify, request
from flask_cors import CORS

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import (
    BudgetSummary,
    CostReport,
    DowngradeReport,
    EfficiencyStats,
    SubtaskMetrics,
    TaskGraphSummary,
    Tier,
    TierDistribution,
)

app = Flask(__name__)
CORS(app)

# ---------------------------------------------------------------------------
# Sample data mirroring the ARCHITECTURE.md blog-post example
# ---------------------------------------------------------------------------

SAMPLE_REPORT = CostReport(
    budget_summary=BudgetSummary(
        dollar_budget=0.08,
        dollar_spent=0.06,
        dollar_remaining=0.02,
        budget_utilization=0.75,
    ),
    subtask_metrics=[
        SubtaskMetrics(
            subtask_id=1,
            name="Research",
            tier=Tier.FAST,
            tokens_budgeted=500,
            tokens_consumed=400,
            cost_dollars=0.004,
            surplus_returned=100,
        ),
        SubtaskMetrics(
            subtask_id=2,
            name="Summarize",
            tier=Tier.FAST,
            tokens_budgeted=1000,
            tokens_consumed=900,
            cost_dollars=0.008,
            surplus_returned=100,
        ),
        SubtaskMetrics(
            subtask_id=3,
            name="Trends",
            tier=Tier.DEEP,
            tokens_budgeted=2000,
            tokens_consumed=1800,
            cost_dollars=0.018,
            surplus_returned=200,
        ),
        SubtaskMetrics(
            subtask_id=4,
            name="Write",
            tier=Tier.DEEP,
            tokens_budgeted=3000,
            tokens_consumed=2600,
            cost_dollars=0.024,
            surplus_returned=400,
        ),
        SubtaskMetrics(
            subtask_id=5,
            name="Review",
            tier=Tier.VERIFY,
            tokens_budgeted=1000,
            tokens_consumed=800,
            cost_dollars=0.006,
            surplus_returned=200,
        ),
    ],
    tier_distribution=[
        TierDistribution(tier=Tier.FAST, count=2, percentage=40.0),
        TierDistribution(tier=Tier.DEEP, count=2, percentage=40.0),
        TierDistribution(tier=Tier.VERIFY, count=1, percentage=20.0),
    ],
    downgrade_report=DowngradeReport(
        original_plan_cost=0.08,
        final_plan_cost=0.06,
        downgrades=[],
        subtasks_skipped=[],
    ),
    efficiency_stats=EfficiencyStats(
        total_tokens_budgeted=7500,
        total_tokens_consumed=6500,
        total_surplus_generated=1000,
        token_efficiency=86.7,
    ),
    task_graph_summary=TaskGraphSummary(
        total_subtasks=5,
        max_depth=4,
        parallelizable_subtasks=0,
        complexity_distribution={"Low": 2, "High": 2, "Medium": 1},
    ),
)

SAMPLE_DAG = {
    "nodes": [
        {"id": 1, "label": "Research", "complexity": "Low"},
        {"id": 2, "label": "Summarize", "complexity": "Low"},
        {"id": 3, "label": "Trends", "complexity": "High"},
        {"id": 4, "label": "Write", "complexity": "High"},
        {"id": 5, "label": "Review", "complexity": "Medium"},
    ],
    "edges": [
        {"from": 1, "to": 2},
        {"from": 2, "to": 3},
        {"from": 2, "to": 4},
        {"from": 3, "to": 4},
        {"from": 4, "to": 5},
    ],
}


@app.route("/api/run", methods=["POST"])
def run():
    data = request.get_json(silent=True) or {}
    task_input = data.get("task", "")
    budget_input = data.get("budget", 0.08)

    report = SAMPLE_REPORT.model_dump()
    report["task_input"] = task_input
    report["budget_input"] = budget_input
    report["dag"] = SAMPLE_DAG
    return jsonify(report)


@app.route("/api/report")
def api_report():
    report = SAMPLE_REPORT.model_dump()
    report["dag"] = SAMPLE_DAG
    return jsonify(report)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
