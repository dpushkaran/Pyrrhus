"""LLM provider abstraction using Creevo Agent Library (CAL).

Provides a factory for creating tier-keyed LLM instances that can be
swapped between providers (Gemini, Anthropic) without changing agent code.
"""

from __future__ import annotations

import os
from typing import List, Optional

from google.genai import types

from CAL.llm import LLM, GeminiLLM
from CAL.message import Message, MessageRole
from CAL.content_blocks import TextBlock
from CAL.tool import Tool

from models import TIER_MAX_TOKENS, TIER_MODELS, Tier


class BudgetGeminiLLM(GeminiLLM):
    """GeminiLLM subclass that passes ``temperature`` and ``max_output_tokens``
    through to the Gemini API config — required for budget-controlled generation.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        max_tokens: int,
        temperature: float = 0.4,
    ):
        super().__init__(
            api_key=api_key,
            model=model,
            max_tokens=max_tokens,
        )
        self.temperature = temperature

    def generate_content(
        self,
        system_prompt: str,
        conversation_history: List[Message],
        tools: Optional[List[Tool]] = None,
    ) -> Message:
        formatted_history = []
        for message in conversation_history:
            parts = []
            if isinstance(message.content, str):
                parts.append(TextBlock(message.content).gemini_content_form())
            else:
                for block in message.content:
                    gemini_block = block.gemini_content_form()
                    parts.extend(
                        gemini_block
                        if isinstance(gemini_block, list)
                        else [gemini_block]
                    )

            role = message.role.value
            if role == "tool response":
                role = "user"
            elif role == "assistant":
                role = "model"

            if formatted_history and formatted_history[-1]["role"] == role:
                formatted_history[-1]["parts"].extend(parts)
            else:
                formatted_history.append({"role": role, "parts": parts})

        config_params: dict = {
            "system_instruction": system_prompt,
            "temperature": self.temperature,
            "max_output_tokens": self.max_tokens,
        }

        if tools:
            config_params["tools"] = [tool.gemini_input_form() for tool in tools]

        response = self.client.models.generate_content(
            model=self.model,
            contents=formatted_history,
            config=types.GenerateContentConfig(**config_params),
        )

        content_blocks = []
        if response.candidates and len(response.candidates) > 0:
            candidate = response.candidates[0]
            if candidate.content and candidate.content.parts:
                for part in candidate.content.parts:
                    if hasattr(part, "text") and part.text:
                        content_blocks.append(TextBlock(text=part.text))

        usage = {}
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            usage = {
                "prompt_tokens": getattr(
                    response.usage_metadata, "prompt_token_count", 0
                )
                or 0,
                "completion_tokens": getattr(
                    response.usage_metadata, "candidates_token_count", 0
                )
                or 0,
                "total_tokens": getattr(
                    response.usage_metadata, "total_token_count", 0
                )
                or 0,
            }

        finish_reason = None
        if response.candidates and len(response.candidates) > 0:
            candidate = response.candidates[0]
            if hasattr(candidate, "finish_reason"):
                finish_reason = str(candidate.finish_reason)

        return Message(
            role=MessageRole.ASSISTANT,
            content=content_blocks,
            usage=usage,
            metadata={"finish_reason": finish_reason} if finish_reason else {},
        )


# -----------------------------------------------------------------------
# Factory
# -----------------------------------------------------------------------


def create_tier_llms(
    api_key: str,
    provider: str = "gemini",
    temperature: float = 0.4,
) -> dict[Tier, LLM]:
    """Create one LLM instance per execution tier.

    Args:
        api_key: Provider API key.
        provider: ``"gemini"`` (default) or ``"anthropic"`` (stub).
        temperature: Sampling temperature for all tiers.

    Returns:
        A ``{Tier: LLM}`` dict ready to hand to ``ExecutorAgent`` or
        ``DynamicExecutor``.
    """
    if provider == "gemini":
        return {
            tier: BudgetGeminiLLM(
                api_key=api_key,
                model=TIER_MODELS[tier],
                max_tokens=TIER_MAX_TOKENS[tier],
                temperature=temperature,
            )
            for tier in Tier
        }

    raise ValueError(f"Unsupported provider: {provider!r}")


# -----------------------------------------------------------------------
# Response helpers
# -----------------------------------------------------------------------


def extract_response(msg: Message) -> tuple[str, int, int, int]:
    """Pull text and token counts out of a CAL ``Message``.

    Returns:
        ``(text, prompt_tokens, completion_tokens, total_tokens)``
    """
    text_parts: list[str] = []
    if isinstance(msg.content, list):
        for block in msg.content:
            if isinstance(block, TextBlock):
                text_parts.append(block.text)
    elif isinstance(msg.content, str):
        text_parts.append(msg.content)

    text = "\n".join(text_parts) if text_parts else ""

    usage = msg.usage or {}
    return (
        text,
        usage.get("prompt_tokens", 0),
        usage.get("completion_tokens", 0),
        usage.get("total_tokens", 0),
    )


def make_user_message(prompt: str) -> Message:
    """Wrap a plain prompt string into a CAL user ``Message``."""
    return Message(
        role=MessageRole.USER,
        content=[TextBlock(text=prompt)],
    )
