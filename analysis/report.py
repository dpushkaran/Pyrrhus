"""Generate analysis plots and JSON summary from stored traces.

Usage:
    python -m analysis.report                       # all traces
    python -m analysis.report --task "some task"    # filter by task
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from analysis.text_metrics import compute_text_metrics
from analysis.trace_store import load_traces, load_traces_for_task
from models import RunTrace

OUTPUT_DIR = Path("analysis/output")


def _ensure_output_dir() -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUTPUT_DIR


def _extract_budget_series(traces: list[RunTrace]) -> dict:
    """Build parallel arrays keyed by metric name, sorted by budget."""
    traces = sorted(traces, key=lambda t: t.budget_dollars)
    data: dict[str, list] = {
        "budget": [],
        "spent": [],
        "quality": [],
        "ttr": [],
        "compression": [],
        "ngram_rep": [],
        "avg_sent_len": [],
        "filler_count": [],
        "word_count": [],
    }

    for tr in traces:
        dm = compute_text_metrics(tr.deliverable) if tr.deliverable else None
        data["budget"].append(tr.budget_dollars)
        data["spent"].append(tr.total_cost_dollars)
        data["quality"].append(
            tr.deliverable_quality.overall if tr.deliverable_quality else None
        )
        data["ttr"].append(dm.type_token_ratio if dm else None)
        data["compression"].append(dm.compression_ratio if dm else None)
        data["ngram_rep"].append(dm.ngram_repetition_rate if dm else None)
        data["avg_sent_len"].append(dm.avg_sentence_length if dm else None)
        data["filler_count"].append(dm.filler_phrase_count if dm else None)
        data["word_count"].append(dm.word_count if dm else None)

    return data


def _plot_line(
    budgets: list[float],
    values: list,
    ylabel: str,
    title: str,
    filename: str,
    out_dir: Path,
) -> None:
    valid = [(b, v) for b, v in zip(budgets, values) if v is not None]
    if len(valid) < 2:
        return
    x, y = zip(*valid)
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(x, y, "o-", linewidth=2, markersize=6)
    ax.set_xlabel("Budget ($)")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_dir / filename, dpi=150)
    plt.close(fig)


def _plot_tier_roi(traces: list[RunTrace], out_dir: Path) -> None:
    """Per-tier average quality / cost scatter."""
    tier_data: dict[str, list[tuple[float, float]]] = {}
    for tr in traces:
        for st in tr.subtask_traces:
            if st.skipped or not st.quality:
                continue
            tier_data.setdefault(st.tier.value, []).append(
                (st.cost_dollars, st.quality.overall)
            )

    if not tier_data:
        return

    fig, ax = plt.subplots(figsize=(7, 4))
    for tier_name, points in tier_data.items():
        costs, quals = zip(*points)
        ax.scatter(costs, quals, label=tier_name, alpha=0.7, s=40)
    ax.set_xlabel("Cost ($)")
    ax.set_ylabel("Quality (0-10)")
    ax.set_title("Per-Tier Cost vs Quality")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_dir / "tier_roi.png", dpi=150)
    plt.close(fig)


def _build_summary(traces: list[RunTrace], data: dict) -> dict:
    """Build a JSON-serialisable summary of the batch comparison."""
    rows = []
    for i, tr in enumerate(sorted(traces, key=lambda t: t.budget_dollars)):
        rows.append({
            "run_id": tr.run_id,
            "budget": data["budget"][i],
            "spent": data["spent"][i],
            "quality": data["quality"][i],
            "type_token_ratio": data["ttr"][i],
            "compression_ratio": data["compression"][i],
            "ngram_repetition_rate": data["ngram_rep"][i],
            "avg_sentence_length": data["avg_sent_len"][i],
            "filler_phrase_count": data["filler_count"][i],
            "word_count": data["word_count"][i],
            "timestamp": tr.timestamp,
        })
    return {"task": traces[0].task if traces else "", "runs": rows}


def generate_report(
    traces: list[RunTrace],
    out_dir: Path | None = None,
) -> dict:
    """Produce all plots and return the JSON summary dict."""
    if not traces:
        print("No traces to report on.")
        return {"task": "", "runs": []}

    out = out_dir or _ensure_output_dir()
    out.mkdir(parents=True, exist_ok=True)

    data = _extract_budget_series(traces)
    budgets = data["budget"]

    _plot_line(budgets, data["quality"], "Quality (0-10)",
              "Quality vs Budget", "quality_vs_budget.png", out)
    _plot_line(budgets, data["compression"], "Compression Ratio",
              "Redundancy vs Budget", "compression_vs_budget.png", out)
    _plot_line(budgets, data["ngram_rep"], "N-gram Repetition Rate",
              "Repetition vs Budget", "ngram_vs_budget.png", out)
    _plot_line(budgets, data["avg_sent_len"], "Avg Sentence Length (words)",
              "Verbosity vs Budget", "verbosity_vs_budget.png", out)
    _plot_line(budgets, data["filler_count"], "Filler Phrase Count",
              "Filler Phrases vs Budget", "fillers_vs_budget.png", out)
    _plot_line(budgets, data["word_count"], "Word Count",
              "Output Length vs Budget", "words_vs_budget.png", out)
    _plot_line(budgets, data["ttr"], "Type-Token Ratio",
              "Vocabulary Diversity vs Budget", "ttr_vs_budget.png", out)

    _plot_tier_roi(traces, out)

    summary = _build_summary(traces, data)
    with open(out / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    # Console table
    print(f"\n{'Budget':>8}  {'Spent':>10}  {'Qual':>5}  "
          f"{'TTR':>5}  {'Compr':>6}  {'Ngram':>6}  {'Fill':>4}  {'Words':>6}")
    print(f"{'─'*8}  {'─'*10}  {'─'*5}  {'─'*5}  {'─'*6}  {'─'*6}  {'─'*4}  {'─'*6}")
    for row in summary["runs"]:
        parts = [f"${row['budget']:>7.4f}"]
        parts.append(f"  ${row['spent']:>9.6f}" if row['spent'] else "        n/a")
        parts.append(f"  {row['quality']:>5.1f}" if row['quality'] is not None else "    n/a")
        parts.append(f"  {row['type_token_ratio']:>5.3f}" if row['type_token_ratio'] is not None else "    n/a")
        parts.append(f"  {row['compression_ratio']:>6.3f}" if row['compression_ratio'] is not None else "     n/a")
        parts.append(f"  {row['ngram_repetition_rate']:>6.3f}" if row['ngram_repetition_rate'] is not None else "     n/a")
        parts.append(f"  {row['filler_phrase_count']:>4}" if row['filler_phrase_count'] is not None else "   n/a")
        parts.append(f"  {row['word_count']:>6}" if row['word_count'] is not None else "     n/a")
        print("".join(parts))

    print(f"\nPlots saved to {out}/")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate analysis report from traces")
    parser.add_argument("--task", default=None, help="Filter traces by task string")
    parser.add_argument("--traces-dir", default="traces", help="Traces directory")
    parser.add_argument("--output-dir", default=None, help="Output directory for plots")
    args = parser.parse_args()

    if args.task:
        traces = load_traces_for_task(args.task, args.traces_dir)
    else:
        traces = load_traces(args.traces_dir)

    out_dir = Path(args.output_dir) if args.output_dir else None
    generate_report(traces, out_dir)


if __name__ == "__main__":
    main()
