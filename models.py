from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field


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
    Tier.FAST: 2048,
    Tier.DEEP: 8192,
    Tier.VERIFY: 4096,
}

COMPLEXITY_TO_TIER = {
    Complexity.LOW: Tier.FAST,
    Complexity.MEDIUM: Tier.VERIFY,
    Complexity.HIGH: Tier.DEEP,
}

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


# ---------------------------------------------------------------------------
# Planner models
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Allocator models
# ---------------------------------------------------------------------------


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
# Executor models
# ---------------------------------------------------------------------------


class SubTaskAttempt(BaseModel):
    tier: Tier
    model: str
    output: str
    quality_score: float
    cost_dollars: float
    prompt_tokens: int
    completion_tokens: int


class ROIDecision(BaseModel):
    subtask_id: int
    current_tier: Tier
    current_quality: float
    proposed_tier: Tier
    upgrade_cost_estimate: float
    expected_quality_lift: float
    roi: float
    decision: str  # "upgrade" | "accept" | "budget_exceeded"
    reason: str


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
    prompt: str = ""
    attempts: list[SubTaskAttempt] = []
    roi_decisions: list[ROIDecision] = []
    final_attempt_index: int = 0


class CostReport(BaseModel):
    budget_dollars: float
    spent_dollars: float
    remaining_dollars: float
    utilization_pct: float

    subtask_results: list[SubTaskResult]

    tier_counts: dict[str, int]
    subtasks_skipped: int
    subtasks_downgraded: int

    downgrades_applied: list[str]

    total_tokens_budgeted: int
    total_tokens_consumed: int
    total_surplus: int
    token_efficiency_pct: float

    total_subtasks: int
    max_depth: int
    parallelizable_subtasks: int
    complexity_distribution: dict[str, int]

    total_upgrades: int = 0
    roi_decisions: list[ROIDecision] = []
    evaluation_cost_dollars: float = 0.0


class ExecutorResult(BaseModel):
    deliverable: str
    report: CostReport


# ---------------------------------------------------------------------------
# Trace & analysis models
# ---------------------------------------------------------------------------


class QualityScore(BaseModel):
    relevance: float = Field(..., ge=0, le=10)
    completeness: float = Field(..., ge=0, le=10)
    coherence: float = Field(..., ge=0, le=10)
    conciseness: float = Field(..., ge=0, le=10)
    overall: float = Field(..., ge=0, le=10)
    rationale: str = ""


class TextMetrics(BaseModel):
    word_count: int = 0
    type_token_ratio: float = 0.0
    compression_ratio: float = 0.0
    ngram_repetition_rate: float = 0.0
    avg_sentence_length: float = 0.0
    filler_phrase_count: int = 0


class SubTaskTrace(BaseModel):
    subtask_id: int
    description: str
    tier: Tier
    model: str
    max_tokens: int
    prompt: str
    output: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_dollars: float = 0.0
    surplus: int = 0
    skipped: bool = False
    quality: Optional[QualityScore] = None
    text_metrics: Optional[TextMetrics] = None
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class PlannerTrace(BaseModel):
    task: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_dollars: float = 0.0
    graph_json: str = ""
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class RunTrace(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    task: str
    budget_dollars: float
    planner_trace: PlannerTrace
    subtask_traces: list[SubTaskTrace] = []
    deliverable: str = ""
    deliverable_quality: Optional[QualityScore] = None
    total_cost_dollars: float = 0.0
    evaluation_cost_dollars: float = 0.0
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
