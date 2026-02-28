from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel


class Complexity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Tier(str, Enum):
    FAST = "fast"
    DEEP = "deep"
    VERIFY = "verify"


TIER_MODELS = {
    Tier.FAST: "gemini-2.5-flash-lite",
    Tier.DEEP: "gemini-2.5-pro",
    Tier.VERIFY: "gemini-2.5-flash",
}

TIER_MAX_TOKENS = {
    Tier.FAST: 1024,
    Tier.DEEP: 4096,
    Tier.VERIFY: 2048,
}

COMPLEXITY_TO_TIER = {
    Complexity.LOW: Tier.FAST,
    Complexity.MEDIUM: Tier.VERIFY,
    Complexity.HIGH: Tier.DEEP,
}

# Dollars per 1M input tokens (approximate, used for budget conversion)
TIER_PRICING_PER_1M_INPUT = {
    Tier.FAST: 0.10,
    Tier.DEEP: 1.25,
    Tier.VERIFY: 0.15,
}

TIER_PRICING_PER_1M_OUTPUT = {
    Tier.FAST: 0.40,
    Tier.DEEP: 10.00,
    Tier.VERIFY: 0.60,
}


class SubTask(BaseModel):
    id: int
    description: str
    complexity: Complexity
    dependencies: list[int] = []


class TaskGraph(BaseModel):
    subtasks: list[SubTask]


class TokenUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class PlannerResult(BaseModel):
    task: str
    graph: TaskGraph
    usage: TokenUsage
    model: str


class SubTaskAllocation(BaseModel):
    subtask_id: int
    tier: Tier
    model: str
    max_tokens: int
    estimated_cost_dollars: float
    skipped: bool = False


class ExecutionPlan(BaseModel):
    allocations: list[SubTaskAllocation]
    total_estimated_tokens: int
    total_estimated_cost_dollars: float
    budget_tokens: int
    budget_dollars: float
    downgrades_applied: list[str] = []


# ---------------------------------------------------------------------------
# Output metric models (populated after a run completes)
# ---------------------------------------------------------------------------


class BudgetSummary(BaseModel):
    dollar_budget: float
    dollar_spent: float
    dollar_remaining: float
    budget_utilization: float


class SubtaskMetrics(BaseModel):
    subtask_id: int
    name: str
    tier: Tier
    tokens_budgeted: int
    tokens_consumed: int
    cost_dollars: float
    surplus_returned: int


class TierDistribution(BaseModel):
    tier: Tier
    count: int
    percentage: float


class DowngradeEntry(BaseModel):
    subtask_id: int
    name: str
    original_tier: Tier
    final_tier: Tier


class DowngradeReport(BaseModel):
    original_plan_cost: float
    final_plan_cost: float
    downgrades: list[DowngradeEntry] = []
    subtasks_skipped: list[str] = []


class EfficiencyStats(BaseModel):
    total_tokens_budgeted: int
    total_tokens_consumed: int
    total_surplus_generated: int
    token_efficiency: float


class TaskGraphSummary(BaseModel):
# Executor output models
# ---------------------------------------------------------------------------


class SubTaskResult(BaseModel):
    subtask_id: int
    description: str
    tier: Tier
    model: str
    tokens_budgeted: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_dollars: float
    surplus: int
    output: str
    skipped: bool = False


class CostReport(BaseModel):
    # Budget summary
    budget_dollars: float
    spent_dollars: float
    remaining_dollars: float
    utilization_pct: float

    # Per-subtask breakdown
    subtask_results: list[SubTaskResult]

    # Tier distribution
    tier_counts: dict[str, int]
    subtasks_skipped: int
    subtasks_downgraded: int

    # Downgrade report
    downgrades_applied: list[str]

    # Efficiency
    total_tokens_budgeted: int
    total_tokens_consumed: int
    total_surplus: int
    token_efficiency_pct: float

    # Task graph summary
    total_subtasks: int
    max_depth: int
    parallelizable_subtasks: int
    complexity_distribution: dict[str, int]


class CostReport(BaseModel):
    budget_summary: BudgetSummary
    subtask_metrics: list[SubtaskMetrics]
    tier_distribution: list[TierDistribution]
    downgrade_report: Optional[DowngradeReport] = None
    efficiency_stats: EfficiencyStats
    task_graph_summary: TaskGraphSummary
class ExecutorResult(BaseModel):
    deliverable: str
    report: CostReport
