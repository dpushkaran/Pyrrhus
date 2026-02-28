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
    Tier.FAST: "gemini-2.0-flash",
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
