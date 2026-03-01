"""SSE endpoint for side-by-side Pyrrhus vs Deep-model comparison.

Self-contained: includes its own evaluator and text metrics so it doesn't
depend on files outside the core agent pipeline.
"""

from __future__ import annotations

import gzip
import json
import logging
import os
import queue
import re
import threading
from collections import Counter, defaultdict

from flask import Blueprint, Response, request
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from agents.allocator import AllocatorAgent
from agents.planner import PlannerAgent
from models import (
    TIER_MAX_TOKENS,
    TIER_MODELS,
    TIER_PRICING_PER_1M_INPUT,
    TIER_PRICING_PER_1M_OUTPUT,
    TaskGraph,
    Tier,
)

logger = logging.getLogger(__name__)
compare_bp = Blueprint("compare", __name__)


# ---------------------------------------------------------------------------
# Inline quality score model (for structured Gemini output)
# ---------------------------------------------------------------------------

class QualityScore(BaseModel):
    relevance: float = Field(..., ge=0, le=10)
    completeness: float = Field(..., ge=0, le=10)
    coherence: float = Field(..., ge=0, le=10)
    conciseness: float = Field(..., ge=0, le=10)
    overall: float = Field(..., ge=0, le=10)
    rationale: str = ""


EVAL_SYSTEM = """\
You are a strict quality evaluator. Given the original user task and the final \
deliverable, score the deliverable on four dimensions:
1. relevance  (0-10): Does the deliverable fulfil the user's task?
2. completeness (0-10): Are all requested components present?
3. coherence (0-10): Is the deliverable logically structured and readable?
4. conciseness (0-10): Is it free of filler, repetition, and unnecessary padding?
Also provide:
- overall (0-10): A single holistic quality score.
- rationale: One sentence explaining the score.
Be critical. Reserve 9-10 for exceptional work only.\
"""


def _evaluate(client: genai.Client, task: str, deliverable: str) -> dict | None:
    try:
        resp = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=f"USER TASK: {task}\n\nDELIVERABLE:\n{deliverable}",
            config=types.GenerateContentConfig(
                system_instruction=EVAL_SYSTEM,
                response_mime_type="application/json",
                response_schema=QualityScore,
                temperature=0.1,
            ),
        )
        return QualityScore.model_validate_json(resp.text).model_dump()
    except Exception:
        logger.warning("Evaluation failed", exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Inline text metrics
# ---------------------------------------------------------------------------

_SENTENCE_SPLIT = re.compile(r"[.!?]+\s+")
_WORD_SPLIT = re.compile(r"\b[a-zA-Z]+\b")

FILLER_PHRASES = [
    "it is important to note", "it's important to note",
    "it is worth noting", "as mentioned earlier",
    "in order to", "essentially", "basically",
    "fundamentally", "it should be noted that",
    "the fact that", "moving forward", "going forward",
    "at the end of the day", "in today's world",
    "it goes without saying", "needless to say",
]


def _text_metrics(text: str) -> dict:
    if not text or not text.strip():
        return {"word_count": 0, "type_token_ratio": 0, "compression_ratio": 0,
                "ngram_repetition_rate": 0, "avg_sentence_length": 0,
                "filler_phrase_count": 0}

    text_lower = text.lower()
    words = _WORD_SPLIT.findall(text_lower)
    wc = len(words)
    ttr = len(set(words)) / wc if wc else 0

    raw = text.encode("utf-8")
    comp = gzip.compress(raw, compresslevel=6)
    cr = len(comp) / len(raw) if raw else 0

    ngrams = [tuple(words[i:i + 3]) for i in range(len(words) - 2)] if len(words) >= 3 else []
    counts = Counter(ngrams)
    ngram_rep = sum(1 for c in counts.values() if c > 1) / len(counts) if counts else 0

    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]
    avg_sl = sum(len(_WORD_SPLIT.findall(s)) for s in sentences) / len(sentences) if sentences else 0

    fillers = sum(text_lower.count(p) for p in FILLER_PHRASES)

    return {
        "word_count": wc,
        "type_token_ratio": round(ttr, 4),
        "compression_ratio": round(cr, 4),
        "ngram_repetition_rate": round(ngram_rep, 4),
        "avg_sentence_length": round(avg_sl, 2),
        "filler_phrase_count": fillers,
    }


# ---------------------------------------------------------------------------
# DAG helpers (mirrored from executor)
# ---------------------------------------------------------------------------

def _topological_sort(graph: TaskGraph) -> list[int]:
    in_degree: dict[int, int] = {s.id: 0 for s in graph.subtasks}
    for s in graph.subtasks:
        for dep in s.dependencies:
            in_degree[s.id] += 1

    q = [sid for sid, deg in in_degree.items() if deg == 0]
    order: list[int] = []

    dependents: dict[int, list[int]] = defaultdict(list)
    for s in graph.subtasks:
        for dep in s.dependencies:
            dependents[dep].append(s.id)

    while q:
        q.sort()
        sid = q.pop(0)
        order.append(sid)
        for child in dependents[sid]:
            in_degree[child] -= 1
            if in_degree[child] == 0:
                q.append(child)
    return order


def _build_context(task: str, subtask_desc: str, dep_ids: list[int],
                   outputs: dict[int, str]) -> str:
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


def _planner_cost(prompt_tokens: int, completion_tokens: int) -> float:
    tier = Tier.VERIFY
    return (
        prompt_tokens * TIER_PRICING_PER_1M_INPUT[tier] / 1_000_000
        + completion_tokens * TIER_PRICING_PER_1M_OUTPUT[tier] / 1_000_000
    )


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


# ---------------------------------------------------------------------------
# Pyrrhus streaming thread
# ---------------------------------------------------------------------------

def _run_pyrrhus(client: genai.Client, task: str, graph: TaskGraph,
                 plan, planner_cost_dollars: float,
                 event_queue: queue.Queue) -> None:
    try:
        alloc_map = {a.subtask_id: a for a in plan.allocations}
        subtask_map = {s.id: s for s in graph.subtasks}
        order = _topological_sort(graph)
        outputs: dict[int, str] = {}
        total_cost = planner_cost_dollars
        total_subtasks = len(order)

        for idx, sid in enumerate(order):
            alloc = alloc_map[sid]
            subtask = subtask_map[sid]

            if alloc.skipped:
                event_queue.put({
                    "type": "pyrrhus_subtask_done",
                    "data": {
                        "subtask_id": sid, "description": subtask.description,
                        "skipped": True, "cost": 0, "tokens": 0, "output": "",
                        "cost_so_far": total_cost,
                        "progress": f"{idx + 1}/{total_subtasks}",
                    },
                })
                continue

            prompt = _build_context(task, subtask.description,
                                    subtask.dependencies, outputs)
            tier = alloc.tier
            output_chunks: list[str] = []
            est_output_tokens = 0
            last_chunk = None

            for chunk in client.models.generate_content_stream(
                model=alloc.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    max_output_tokens=alloc.max_tokens,
                    temperature=0.4,
                ),
            ):
                last_chunk = chunk
                delta = chunk.text or ""
                if delta:
                    output_chunks.append(delta)
                    est_output_tokens += max(1, len(delta) // 4)
                    est_cost = est_output_tokens * TIER_PRICING_PER_1M_OUTPUT[tier] / 1_000_000
                    event_queue.put({
                        "type": "pyrrhus_chunk",
                        "data": {
                            "subtask_id": sid, "delta": delta,
                            "cost_so_far": round(total_cost + est_cost, 8),
                            "progress": f"{idx + 1}/{total_subtasks}",
                        },
                    })

            full_output = "".join(output_chunks)
            outputs[sid] = full_output

            prompt_tokens = 0
            completion_tokens = est_output_tokens
            if last_chunk and hasattr(last_chunk, "usage_metadata") and last_chunk.usage_metadata:
                um = last_chunk.usage_metadata
                prompt_tokens = um.prompt_token_count or 0
                completion_tokens = um.candidates_token_count or est_output_tokens

            cost = (
                prompt_tokens * TIER_PRICING_PER_1M_INPUT[tier] / 1_000_000
                + completion_tokens * TIER_PRICING_PER_1M_OUTPUT[tier] / 1_000_000
            )
            total_cost += cost

            event_queue.put({
                "type": "pyrrhus_subtask_done",
                "data": {
                    "subtask_id": sid, "description": subtask.description,
                    "tier": tier.value, "skipped": False,
                    "tokens": completion_tokens,
                    "cost": round(cost, 8), "cost_so_far": round(total_cost, 8),
                    "output": full_output,
                    "progress": f"{idx + 1}/{total_subtasks}",
                },
            })

        deliverable_parts = [outputs[sid] for sid in order
                             if sid in outputs and outputs[sid]]
        full_deliverable = "\n\n".join(deliverable_parts) if deliverable_parts else ""

        event_queue.put({
            "type": "thread_done", "side": "pyrrhus",
            "deliverable": full_deliverable, "total_cost": round(total_cost, 8),
        })
    except Exception as e:
        logger.error("Pyrrhus thread failed", exc_info=True)
        event_queue.put({"type": "error", "data": {"message": f"Pyrrhus: {e}"}})
        event_queue.put({"type": "thread_done", "side": "pyrrhus",
                         "deliverable": "", "total_cost": 0})


# ---------------------------------------------------------------------------
# Baseline streaming thread
# ---------------------------------------------------------------------------

def _run_baseline(client: genai.Client, task: str, budget_dollars: float,
                  mode: str, event_queue: queue.Queue) -> None:
    try:
        model = TIER_MODELS[Tier.DEEP]
        tier = Tier.DEEP

        config_kwargs: dict = {"temperature": 0.4}
        if mode == "capped":
            price_per_token = TIER_PRICING_PER_1M_OUTPUT[tier] / 1_000_000
            max_tokens = int(budget_dollars / price_per_token) if price_per_token > 0 else 8192
            max_tokens = max(256, min(max_tokens, 65536))
            config_kwargs["max_output_tokens"] = max_tokens

        output_chunks: list[str] = []
        est_output_tokens = 0
        last_chunk = None

        for chunk in client.models.generate_content_stream(
            model=model,
            contents=task,
            config=types.GenerateContentConfig(**config_kwargs),
        ):
            last_chunk = chunk
            delta = chunk.text or ""
            if delta:
                output_chunks.append(delta)
                est_output_tokens += max(1, len(delta) // 4)
                est_cost = est_output_tokens * TIER_PRICING_PER_1M_OUTPUT[tier] / 1_000_000
                event_queue.put({
                    "type": "baseline_chunk",
                    "data": {
                        "delta": delta,
                        "tokens_so_far": est_output_tokens,
                        "cost_so_far": round(est_cost, 8),
                    },
                })

        full_output = "".join(output_chunks)

        prompt_tokens = 0
        completion_tokens = est_output_tokens
        if last_chunk and hasattr(last_chunk, "usage_metadata") and last_chunk.usage_metadata:
            um = last_chunk.usage_metadata
            prompt_tokens = um.prompt_token_count or 0
            completion_tokens = um.candidates_token_count or est_output_tokens

        total_cost = (
            prompt_tokens * TIER_PRICING_PER_1M_INPUT[tier] / 1_000_000
            + completion_tokens * TIER_PRICING_PER_1M_OUTPUT[tier] / 1_000_000
        )

        event_queue.put({
            "type": "baseline_done",
            "data": {
                "tokens": completion_tokens, "prompt_tokens": prompt_tokens,
                "cost": round(total_cost, 8), "output": full_output,
            },
        })
        event_queue.put({
            "type": "thread_done", "side": "baseline",
            "deliverable": full_output, "total_cost": round(total_cost, 8),
        })
    except Exception as e:
        logger.error("Baseline thread failed", exc_info=True)
        event_queue.put({"type": "error", "data": {"message": f"Baseline: {e}"}})
        event_queue.put({"type": "thread_done", "side": "baseline",
                         "deliverable": "", "total_cost": 0})


# ---------------------------------------------------------------------------
# SSE endpoint
# ---------------------------------------------------------------------------

@compare_bp.route("/api/compare/stream")
def compare_stream():
    task = request.args.get("task", "").strip()
    budget = float(request.args.get("budget", "0.08"))
    mode = request.args.get("mode", "capped")

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return Response(_sse("error", {"message": "GOOGLE_API_KEY not set"}),
                        mimetype="text/event-stream")
    if not task:
        return Response(_sse("error", {"message": "task is required"}),
                        mimetype="text/event-stream")

    def generate():
        client = genai.Client(api_key=api_key)

        planner = PlannerAgent(api_key=api_key)
        planner_result = planner.plan(task)
        pc = _planner_cost(
            planner_result.usage.prompt_tokens,
            planner_result.usage.completion_tokens,
        )

        allocator = AllocatorAgent()
        plan = allocator.allocate(
            graph=planner_result.graph,
            budget_dollars=budget,
            spent_dollars=pc,
        )

        subtasks_info = [
            {"id": s.id, "description": s.description,
             "complexity": s.complexity.value, "dependencies": s.dependencies}
            for s in planner_result.graph.subtasks
        ]
        allocations_info = [
            {"subtask_id": a.subtask_id, "tier": a.tier.value,
             "model": a.model, "max_tokens": a.max_tokens, "skipped": a.skipped}
            for a in plan.allocations
        ]

        yield _sse("plan", {
            "subtasks": subtasks_info,
            "allocations": allocations_info,
            "planner_cost": round(pc, 8),
            "total_subtasks": len(subtasks_info),
        })

        event_q: queue.Queue = queue.Queue()

        pyrrhus_thread = threading.Thread(
            target=_run_pyrrhus,
            args=(client, task, planner_result.graph, plan, pc, event_q),
            daemon=True,
        )
        baseline_thread = threading.Thread(
            target=_run_baseline,
            args=(client, task, budget, mode, event_q),
            daemon=True,
        )

        pyrrhus_thread.start()
        baseline_thread.start()

        done_sides: set[str] = set()
        pyrrhus_deliverable = ""
        baseline_deliverable = ""
        pyrrhus_cost = 0.0
        baseline_cost = 0.0

        while len(done_sides) < 2:
            try:
                evt = event_q.get(timeout=120)
            except queue.Empty:
                yield _sse("error", {"message": "Timeout waiting for results"})
                return

            if evt["type"] == "thread_done":
                side = evt["side"]
                done_sides.add(side)
                if side == "pyrrhus":
                    pyrrhus_deliverable = evt.get("deliverable", "")
                    pyrrhus_cost = evt.get("total_cost", 0)
                else:
                    baseline_deliverable = evt.get("deliverable", "")
                    baseline_cost = evt.get("total_cost", 0)
            elif evt["type"] == "error":
                yield _sse("error", evt["data"])
            else:
                yield _sse(evt["type"], evt["data"])

        pyrrhus_q = _evaluate(client, task, pyrrhus_deliverable) if pyrrhus_deliverable else None
        baseline_q = _evaluate(client, task, baseline_deliverable) if baseline_deliverable else None

        yield _sse("quality", {
            "pyrrhus": pyrrhus_q,
            "baseline": baseline_q,
        })

        yield _sse("text_metrics", {
            "pyrrhus": _text_metrics(pyrrhus_deliverable),
            "baseline": _text_metrics(baseline_deliverable),
        })

        yield _sse("done", {
            "pyrrhus_cost": round(pyrrhus_cost, 8),
            "baseline_cost": round(baseline_cost, 8),
            "pyrrhus_quality": pyrrhus_q["overall"] if pyrrhus_q else None,
            "baseline_quality": baseline_q["overall"] if baseline_q else None,
            "mode": mode,
            "budget": budget,
        })

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
