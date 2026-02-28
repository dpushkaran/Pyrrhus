from __future__ import annotations

import json
import logging
from typing import Optional

from google import genai
from google.genai import types

from models import (
    Complexity,
    PlannerResult,
    SubTask,
    TaskGraph,
    TokenUsage,
)

logger = logging.getLogger(__name__)

PLANNER_MODEL = "gemini-2.5-flash"

SYSTEM_INSTRUCTION = """\
You are a task decomposition engine. Given a user's task, break it into \
discrete subtasks that together produce the final deliverable.

Rules:
1. Assign each subtask a unique integer ID starting from 1.
2. Write a clear, actionable one-sentence description for each subtask.
3. Rate complexity:
   - low: simple retrieval, formatting, lookups, or straightforward generation.
   - medium: moderate synthesis, quality checks, verification, summarisation.
   - high: creative writing, trend analysis, multi-source reasoning, long-form composition.
4. List dependency IDs — subtasks that MUST complete before this one can start.
5. The subtasks must form a valid DAG (no circular dependencies).
6. Aim for 3–7 subtasks. Prefer fewer, coarser subtasks over many tiny ones.
7. The final subtask should always produce or review the user-facing deliverable.\
"""


def _validate_dag(graph: TaskGraph) -> None:
    """Raise ValueError if the graph has invalid references or cycles."""
    ids = {s.id for s in graph.subtasks}
    for s in graph.subtasks:
        for dep in s.dependencies:
            if dep not in ids:
                raise ValueError(
                    f"Subtask {s.id} depends on non-existent subtask {dep}"
                )
            if dep == s.id:
                raise ValueError(f"Subtask {s.id} depends on itself")

    visited: set[int] = set()
    in_stack: set[int] = set()
    adj = {s.id: s.dependencies for s in graph.subtasks}

    def dfs(node: int) -> None:
        if node in in_stack:
            raise ValueError(f"Cycle detected involving subtask {node}")
        if node in visited:
            return
        in_stack.add(node)
        for dep in adj.get(node, []):
            dfs(dep)
        in_stack.discard(node)
        visited.add(node)

    for s in graph.subtasks:
        dfs(s.id)


class PlannerAgent:
    """Decomposes a user task into a structured subtask DAG.

    Uses Gemini structured output to produce a TaskGraph with complexity
    ratings and dependency edges. The planner is budget-unaware — it
    decomposes based purely on what the task requires. Budget constraints
    are applied downstream by the Allocator.
    """

    def __init__(self, api_key: str, model: str = PLANNER_MODEL):
        self.client = genai.Client(api_key=api_key)
        self.model = model

    def plan(self, task: str) -> PlannerResult:
        """Decompose *task* into a validated TaskGraph.

        Returns a PlannerResult containing the graph and token usage so the
        orchestrator can account for the planner's own cost.
        """
        response = self.client.models.generate_content(
            model=self.model,
            contents=task,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
                response_schema=TaskGraph,
                temperature=0.2,
            ),
        )

        graph = TaskGraph.model_validate_json(response.text)
        _validate_dag(graph)

        usage = TokenUsage(
            prompt_tokens=response.usage_metadata.prompt_token_count or 0,
            completion_tokens=response.usage_metadata.candidates_token_count or 0,
            total_tokens=response.usage_metadata.total_token_count or 0,
        )

        logger.info(
            "Planner decomposed task into %d subtasks, used %d tokens",
            len(graph.subtasks),
            usage.total_tokens,
        )

        return PlannerResult(
            task=task,
            graph=graph,
            usage=usage,
            model=self.model,
        )
