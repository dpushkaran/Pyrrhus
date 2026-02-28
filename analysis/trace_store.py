"""Persist and load RunTrace records via Supabase (Postgres)."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from supabase import Client, create_client

from models import (
    PlannerTrace,
    QualityScore,
    RunTrace,
    SubTaskTrace,
    TextMetrics,
    Tier,
)

logger = logging.getLogger(__name__)

_client: Client | None = None


def _get_client() -> Client:
    """Lazily create and cache a Supabase client from env vars."""
    global _client
    if _client is None:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")
        if not url or not key:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_KEY must be set in environment"
            )
        _client = create_client(url, key)
    return _client


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


def save_trace(trace: RunTrace, directory: str | Path | None = None) -> str:
    """Persist a RunTrace to Supabase across the runs, planner_traces,
    and subtask_traces tables.  Returns the run_id.

    The *directory* parameter is accepted for backward compatibility but
    ignored — traces are stored in Supabase, not on disk.
    """
    client = _get_client()

    dq = trace.deliverable_quality
    run_row = {
        "run_id": trace.run_id,
        "task": trace.task,
        "budget_dollars": trace.budget_dollars,
        "deliverable": trace.deliverable,
        "total_cost_dollars": trace.total_cost_dollars,
        "evaluation_cost_dollars": trace.evaluation_cost_dollars,
        "dq_relevance": dq.relevance if dq else None,
        "dq_completeness": dq.completeness if dq else None,
        "dq_coherence": dq.coherence if dq else None,
        "dq_conciseness": dq.conciseness if dq else None,
        "dq_overall": dq.overall if dq else None,
        "dq_rationale": dq.rationale if dq else None,
    }
    client.table("runs").insert(run_row).execute()

    pt = trace.planner_trace
    planner_row = {
        "run_id": trace.run_id,
        "task": pt.task,
        "model": pt.model,
        "prompt_tokens": pt.prompt_tokens,
        "completion_tokens": pt.completion_tokens,
        "total_tokens": pt.total_tokens,
        "cost_dollars": pt.cost_dollars,
        "graph_json": json.loads(pt.graph_json) if pt.graph_json else {},
    }
    client.table("planner_traces").insert(planner_row).execute()

    if trace.subtask_traces:
        subtask_rows = []
        for st in trace.subtask_traces:
            q = st.quality
            tm = st.text_metrics
            subtask_rows.append({
                "run_id": trace.run_id,
                "subtask_id": st.subtask_id,
                "description": st.description,
                "tier": st.tier.value,
                "model": st.model,
                "max_tokens": st.max_tokens,
                "prompt": st.prompt,
                "output": st.output,
                "prompt_tokens": st.prompt_tokens,
                "completion_tokens": st.completion_tokens,
                "total_tokens": st.total_tokens,
                "cost_dollars": st.cost_dollars,
                "surplus": st.surplus,
                "skipped": st.skipped,
                "q_relevance": q.relevance if q else None,
                "q_completeness": q.completeness if q else None,
                "q_coherence": q.coherence if q else None,
                "q_conciseness": q.conciseness if q else None,
                "q_overall": q.overall if q else None,
                "q_rationale": q.rationale if q else None,
                "tm_word_count": tm.word_count if tm else None,
                "tm_type_token_ratio": tm.type_token_ratio if tm else None,
                "tm_compression_ratio": tm.compression_ratio if tm else None,
                "tm_ngram_repetition_rate": tm.ngram_repetition_rate if tm else None,
                "tm_avg_sentence_length": tm.avg_sentence_length if tm else None,
                "tm_filler_phrase_count": tm.filler_phrase_count if tm else None,
            })
        client.table("subtask_traces").insert(subtask_rows).execute()

    logger.info("Saved trace %s to Supabase", trace.run_id)
    return trace.run_id


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------


def _build_quality(row: dict, prefix: str) -> QualityScore | None:
    """Reconstruct a QualityScore from flattened DB columns."""
    overall = row.get(f"{prefix}_overall")
    if overall is None:
        return None
    return QualityScore(
        relevance=row[f"{prefix}_relevance"],
        completeness=row[f"{prefix}_completeness"],
        coherence=row[f"{prefix}_coherence"],
        conciseness=row[f"{prefix}_conciseness"],
        overall=overall,
        rationale=row.get(f"{prefix}_rationale", ""),
    )


def _build_text_metrics(row: dict) -> TextMetrics | None:
    """Reconstruct TextMetrics from flattened DB columns."""
    if row.get("tm_word_count") is None:
        return None
    return TextMetrics(
        word_count=row["tm_word_count"],
        type_token_ratio=row["tm_type_token_ratio"],
        compression_ratio=row["tm_compression_ratio"],
        ngram_repetition_rate=row["tm_ngram_repetition_rate"],
        avg_sentence_length=row["tm_avg_sentence_length"],
        filler_phrase_count=row["tm_filler_phrase_count"],
    )


def _rows_to_traces(
    run_rows: list[dict],
    planner_map: dict[str, dict],
    subtask_map: dict[str, list[dict]],
) -> list[RunTrace]:
    """Assemble RunTrace objects from DB rows across all three tables."""
    traces: list[RunTrace] = []
    for r in run_rows:
        run_id = r["run_id"]

        pt_row = planner_map.get(run_id, {})
        graph_json_val = pt_row.get("graph_json", {})
        planner_trace = PlannerTrace(
            task=pt_row.get("task", r["task"]),
            model=pt_row.get("model", ""),
            prompt_tokens=pt_row.get("prompt_tokens", 0),
            completion_tokens=pt_row.get("completion_tokens", 0),
            total_tokens=pt_row.get("total_tokens", 0),
            cost_dollars=pt_row.get("cost_dollars", 0.0),
            graph_json=(
                json.dumps(graph_json_val)
                if isinstance(graph_json_val, dict)
                else str(graph_json_val)
            ),
            timestamp=pt_row.get("created_at", r["created_at"]),
        )

        subtask_traces: list[SubTaskTrace] = []
        for st_row in subtask_map.get(run_id, []):
            subtask_traces.append(SubTaskTrace(
                subtask_id=st_row["subtask_id"],
                description=st_row["description"],
                tier=Tier(st_row["tier"]),
                model=st_row["model"],
                max_tokens=st_row["max_tokens"],
                prompt=st_row.get("prompt", ""),
                output=st_row.get("output", ""),
                prompt_tokens=st_row.get("prompt_tokens", 0),
                completion_tokens=st_row.get("completion_tokens", 0),
                total_tokens=st_row.get("total_tokens", 0),
                cost_dollars=st_row.get("cost_dollars", 0.0),
                surplus=st_row.get("surplus", 0),
                skipped=st_row.get("skipped", False),
                quality=_build_quality(st_row, "q"),
                text_metrics=_build_text_metrics(st_row),
                timestamp=st_row.get("created_at", r["created_at"]),
            ))

        traces.append(RunTrace(
            run_id=run_id,
            task=r["task"],
            budget_dollars=r["budget_dollars"],
            planner_trace=planner_trace,
            subtask_traces=subtask_traces,
            deliverable=r.get("deliverable", ""),
            deliverable_quality=_build_quality(r, "dq"),
            total_cost_dollars=r.get("total_cost_dollars", 0.0),
            evaluation_cost_dollars=r.get("evaluation_cost_dollars", 0.0),
            timestamp=r["created_at"],
        ))
    return traces


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


def load_traces(directory: str | Path | None = None) -> list[RunTrace]:
    """Load all RunTrace records from Supabase.

    The *directory* parameter is accepted for backward compatibility but
    ignored.
    """
    client = _get_client()

    run_rows = (
        client.table("runs")
        .select("*")
        .order("created_at", desc=True)
        .execute()
        .data
    )
    if not run_rows:
        return []

    planner_rows = client.table("planner_traces").select("*").execute().data
    planner_map = {r["run_id"]: r for r in planner_rows}

    subtask_rows = (
        client.table("subtask_traces")
        .select("*")
        .order("subtask_id")
        .execute()
        .data
    )
    subtask_map: dict[str, list[dict]] = {}
    for row in subtask_rows:
        subtask_map.setdefault(row["run_id"], []).append(row)

    return _rows_to_traces(run_rows, planner_map, subtask_map)


def load_traces_for_task(
    task: str, directory: str | Path | None = None
) -> list[RunTrace]:
    """Load RunTrace records filtered by task string.

    Uses a server-side filter instead of loading everything into memory.
    The *directory* parameter is accepted for backward compatibility but
    ignored.
    """
    client = _get_client()

    run_rows = (
        client.table("runs")
        .select("*")
        .eq("task", task)
        .order("created_at", desc=True)
        .execute()
        .data
    )
    if not run_rows:
        return []

    run_ids = [r["run_id"] for r in run_rows]

    planner_rows = (
        client.table("planner_traces")
        .select("*")
        .in_("run_id", run_ids)
        .execute()
        .data
    )
    planner_map = {r["run_id"]: r for r in planner_rows}

    subtask_rows = (
        client.table("subtask_traces")
        .select("*")
        .in_("run_id", run_ids)
        .order("subtask_id")
        .execute()
        .data
    )
    subtask_map: dict[str, list[dict]] = {}
    for row in subtask_rows:
        subtask_map.setdefault(row["run_id"], []).append(row)

    return _rows_to_traces(run_rows, planner_map, subtask_map)
