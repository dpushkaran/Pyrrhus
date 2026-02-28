"""LLM-as-judge quality evaluator using Gemini structured output."""

from __future__ import annotations

import logging

from google import genai
from google.genai import types

from models import QualityScore

logger = logging.getLogger(__name__)

EVALUATOR_MODEL = "gemini-2.5-flash-lite"

SUBTASK_SYSTEM_INSTRUCTION = """\
You are a strict quality evaluator. Given a subtask description, the overall \
task context, and the agent's output, score the output on four dimensions:

1. relevance  (0-10): Does the output address the subtask?
2. completeness (0-10): Does it cover all aspects of the subtask?
3. coherence (0-10): Is it logically structured and clearly written?
4. conciseness (0-10): Is it free of filler, repetition, and padding?

Also provide:
- overall (0-10): A single holistic quality score.
- rationale: One sentence explaining the score.

Be critical. Reserve 9-10 for exceptional work only.\
"""

DELIVERABLE_SYSTEM_INSTRUCTION = """\
You are a strict quality evaluator. Given the original user task and the final \
deliverable produced by a multi-agent pipeline, score the deliverable on four \
dimensions:

1. relevance  (0-10): Does the deliverable fulfil the user's task?
2. completeness (0-10): Are all requested components present?
3. coherence (0-10): Is the deliverable logically structured and readable?
4. conciseness (0-10): Is it free of filler, repetition, and unnecessary padding?

Also provide:
- overall (0-10): A single holistic quality score.
- rationale: One sentence explaining the score.

Be critical. Reserve 9-10 for exceptional work only.\
"""


class EvaluatorAgent:
    """Scores agent outputs using an LLM-as-judge approach.

    Evaluation cost is tracked but intentionally kept separate from
    the task budget — it is meta-analysis, not part of the pipeline.
    """

    def __init__(self, api_key: str, model: str = EVALUATOR_MODEL):
        self.client = genai.Client(api_key=api_key)
        self.model = model
        self.total_tokens_used = 0
        self.total_cost_dollars = 0.0

    def evaluate_subtask(
        self,
        subtask_description: str,
        output: str,
        task_context: str,
    ) -> QualityScore:
        """Score a single subtask output against its description."""
        prompt = (
            f"OVERALL TASK: {task_context}\n\n"
            f"SUBTASK: {subtask_description}\n\n"
            f"AGENT OUTPUT:\n{output}"
        )
        return self._evaluate(prompt, SUBTASK_SYSTEM_INSTRUCTION)

    def evaluate_deliverable(
        self,
        task: str,
        deliverable: str,
    ) -> QualityScore:
        """Score the final deliverable against the original task."""
        prompt = (
            f"USER TASK: {task}\n\n"
            f"DELIVERABLE:\n{deliverable}"
        )
        return self._evaluate(prompt, DELIVERABLE_SYSTEM_INSTRUCTION)

    def _evaluate(self, prompt: str, system_instruction: str) -> QualityScore:
        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
                response_schema=QualityScore,
                temperature=0.1,
            ),
        )

        score = QualityScore.model_validate_json(response.text)

        prompt_tokens = response.usage_metadata.prompt_token_count or 0
        completion_tokens = response.usage_metadata.candidates_token_count or 0
        total_tokens = response.usage_metadata.total_token_count or 0

        # Track cumulative evaluation cost (flash-lite pricing)
        input_cost = prompt_tokens * 0.10 / 1_000_000
        output_cost = completion_tokens * 0.40 / 1_000_000
        self.total_cost_dollars += input_cost + output_cost
        self.total_tokens_used += total_tokens

        logger.info(
            "Evaluator scored %.1f/10 (%d tokens, $%.6f cumulative)",
            score.overall,
            total_tokens,
            self.total_cost_dollars,
        )

        return score
