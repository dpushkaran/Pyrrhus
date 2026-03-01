"""Batch data collection using MT-Bench prompts from HuggingFace.

Runs Pyrrhus pipeline + baseline Deep model for each (task, budget) pair,
collects quality scores and text metrics, and stores results in Supabase.

Usage:
    python collect_dataset.py --dry-run                    # see what would run
    python collect_dataset.py                              # run all 80 prompts x 4 budgets
    python collect_dataset.py --categories writing,coding  # filter by category
    python collect_dataset.py --max-tasks 10               # limit number of tasks
    python collect_dataset.py --budgets 0.04,0.08          # custom budget levels
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
import time
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "dashboard"))

from google import genai
from google.genai import types
from supabase import create_client

from agents.allocator import AllocatorAgent
from agents.planner import PlannerAgent
from compare import (
    QualityScore,
    _build_context,
    _evaluate,
    _planner_cost,
    _text_metrics,
    _topological_sort,
)
from models import (
    TIER_PRICING_PER_1M_INPUT,
    TIER_PRICING_PER_1M_OUTPUT,
    Tier,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BUDGETS = [0.02, 0.04, 0.08, 0.16]


# ---------------------------------------------------------------------------
# Load MT-Bench prompts from HuggingFace
# ---------------------------------------------------------------------------

def load_mt_bench() -> list[dict]:
    """Load MT-Bench prompts. Returns list of {prompt, category, prompt_id}."""
    from datasets import load_dataset
    ds = load_dataset("HuggingFaceH4/mt_bench_prompts", split="train")
    tasks = []
    for row in ds:
        prompts = row["prompt"]
        tasks.append({
            "prompt": prompts[0],
            "category": row["category"],
            "prompt_id": row["prompt_id"],
        })
    return tasks


# ---------------------------------------------------------------------------
# Run one comparison
# ---------------------------------------------------------------------------

def run_comparison(
    api_key: str,
    task: str,
    budget: float,
    category: str = "",
    prompt_id: int = 0,
    mode: str = "capped",
) -> dict:
    """Run Pyrrhus + baseline for one (task, budget) pair."""
    client = genai.Client(api_key=api_key)
    comparison_id = str(uuid4())

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

    # --- Pyrrhus execution ---
    alloc_map = {a.subtask_id: a for a in plan.allocations}
    subtask_map = {s.id: s for s in planner_result.graph.subtasks}
    order = _topological_sort(planner_result.graph)
    outputs: dict[int, str] = {}
    pyrrhus_total_cost = pc
    subtask_details = []

    for sid in order:
        alloc = alloc_map[sid]
        subtask = subtask_map[sid]

        if alloc.skipped:
            subtask_details.append({
                "subtask_id": sid, "tier": alloc.tier.value,
                "skipped": True, "tokens": 0, "cost": 0,
            })
            continue

        prompt = _build_context(task, subtask.description,
                                subtask.dependencies, outputs)

        response = client.models.generate_content(
            model=alloc.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                max_output_tokens=alloc.max_tokens,
                temperature=0.4,
            ),
        )

        output_text = response.text or ""
        outputs[sid] = output_text

        prompt_tokens = response.usage_metadata.prompt_token_count or 0
        completion_tokens = response.usage_metadata.candidates_token_count or 0
        cost = (
            prompt_tokens * TIER_PRICING_PER_1M_INPUT[alloc.tier] / 1_000_000
            + completion_tokens * TIER_PRICING_PER_1M_OUTPUT[alloc.tier] / 1_000_000
        )
        pyrrhus_total_cost += cost

        subtask_details.append({
            "subtask_id": sid, "tier": alloc.tier.value,
            "skipped": False, "tokens": completion_tokens, "cost": round(cost, 8),
        })

    pyrrhus_deliverable = "\n\n".join(
        outputs[sid] for sid in order if sid in outputs and outputs[sid]
    )

    # --- Baseline execution ---
    config_kwargs: dict = {"temperature": 0.4}
    if mode == "capped":
        price_per_token = TIER_PRICING_PER_1M_OUTPUT[Tier.DEEP] / 1_000_000
        max_tokens = int(budget / price_per_token) if price_per_token > 0 else 8192
        max_tokens = max(256, min(max_tokens, 65536))
        config_kwargs["max_output_tokens"] = max_tokens

    baseline_response = client.models.generate_content(
        model="gemini-2.5-pro",
        contents=task,
        config=types.GenerateContentConfig(**config_kwargs),
    )
    baseline_output = baseline_response.text or ""
    b_prompt = baseline_response.usage_metadata.prompt_token_count or 0
    b_completion = baseline_response.usage_metadata.candidates_token_count or 0
    baseline_cost = (
        b_prompt * TIER_PRICING_PER_1M_INPUT[Tier.DEEP] / 1_000_000
        + b_completion * TIER_PRICING_PER_1M_OUTPUT[Tier.DEEP] / 1_000_000
    )

    # --- Evaluate both ---
    pyrrhus_quality = _evaluate(client, task, pyrrhus_deliverable) if pyrrhus_deliverable else None
    baseline_quality = _evaluate(client, task, baseline_output) if baseline_output else None

    pyrrhus_tm = _text_metrics(pyrrhus_deliverable)
    baseline_tm = _text_metrics(baseline_output)

    tier_counts = {"fast": 0, "verify": 0, "deep": 0}
    for d in subtask_details:
        if not d["skipped"]:
            tier_counts[d["tier"]] = tier_counts.get(d["tier"], 0) + 1

    return {
        "comparison_id": comparison_id,
        "task": task,
        "category": category,
        "prompt_id": prompt_id,
        "budget": budget,
        "mode": mode,
        "num_subtasks": len(order),
        "num_skipped": sum(1 for d in subtask_details if d["skipped"]),
        "tier_fast": tier_counts["fast"],
        "tier_verify": tier_counts["verify"],
        "tier_deep": tier_counts["deep"],
        "planner_cost": round(pc, 8),
        "pyrrhus_cost": round(pyrrhus_total_cost, 8),
        "baseline_cost": round(baseline_cost, 8),
        "pyrrhus_quality": pyrrhus_quality["overall"] if pyrrhus_quality else None,
        "pyrrhus_relevance": pyrrhus_quality["relevance"] if pyrrhus_quality else None,
        "pyrrhus_completeness": pyrrhus_quality["completeness"] if pyrrhus_quality else None,
        "pyrrhus_coherence": pyrrhus_quality["coherence"] if pyrrhus_quality else None,
        "pyrrhus_conciseness": pyrrhus_quality["conciseness"] if pyrrhus_quality else None,
        "baseline_quality": baseline_quality["overall"] if baseline_quality else None,
        "baseline_relevance": baseline_quality["relevance"] if baseline_quality else None,
        "baseline_completeness": baseline_quality["completeness"] if baseline_quality else None,
        "baseline_coherence": baseline_quality["coherence"] if baseline_quality else None,
        "baseline_conciseness": baseline_quality["conciseness"] if baseline_quality else None,
        "pyrrhus_word_count": pyrrhus_tm["word_count"],
        "pyrrhus_ttr": pyrrhus_tm["type_token_ratio"],
        "pyrrhus_compression": pyrrhus_tm["compression_ratio"],
        "pyrrhus_ngram_rep": pyrrhus_tm["ngram_repetition_rate"],
        "pyrrhus_avg_sent_len": pyrrhus_tm["avg_sentence_length"],
        "pyrrhus_fillers": pyrrhus_tm["filler_phrase_count"],
        "baseline_word_count": baseline_tm["word_count"],
        "baseline_ttr": baseline_tm["type_token_ratio"],
        "baseline_compression": baseline_tm["compression_ratio"],
        "baseline_ngram_rep": baseline_tm["ngram_repetition_rate"],
        "baseline_avg_sent_len": baseline_tm["avg_sentence_length"],
        "baseline_fillers": baseline_tm["filler_phrase_count"],
        "cost_savings_pct": round(
            (baseline_cost - pyrrhus_total_cost) / baseline_cost * 100, 2
        ) if baseline_cost > 0 else 0,
        "quality_delta": round(
            (pyrrhus_quality["overall"] if pyrrhus_quality else 0)
            - (baseline_quality["overall"] if baseline_quality else 0), 2
        ),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Collect comparison dataset using MT-Bench")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--delay", type=float, default=2.0, help="Seconds between runs")
    parser.add_argument("--budgets", default=None, help="Comma-separated budgets")
    parser.add_argument("--categories", default=None,
                        help="Comma-separated MT-Bench categories (writing,roleplay,reasoning,math,coding,extraction,stem,humanities)")
    parser.add_argument("--max-tasks", type=int, default=None, help="Limit number of tasks")
    parser.add_argument("--start-from", type=int, default=0, help="Skip first N pairs (resume)")
    args = parser.parse_args()

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        sys.exit("GOOGLE_API_KEY not set")

    budgets = [float(b) for b in args.budgets.split(",")] if args.budgets else BUDGETS

    logger.info("Loading MT-Bench prompts from HuggingFace...")
    mt_bench = load_mt_bench()
    logger.info("Loaded %d prompts across categories: %s",
                len(mt_bench),
                ", ".join(sorted(set(t["category"] for t in mt_bench))))

    if args.categories:
        cats = set(c.strip() for c in args.categories.split(","))
        mt_bench = [t for t in mt_bench if t["category"] in cats]
        logger.info("Filtered to %d prompts in categories: %s", len(mt_bench), cats)

    if args.max_tasks:
        mt_bench = mt_bench[:args.max_tasks]
        logger.info("Limited to first %d tasks", args.max_tasks)

    pairs = [(t, b) for t in mt_bench for b in budgets]
    logger.info("Total: %d tasks x %d budgets = %d comparisons", len(mt_bench), len(budgets), len(pairs))

    if args.start_from > 0:
        pairs = pairs[args.start_from:]
        logger.info("Resuming from index %d (%d remaining)", args.start_from, len(pairs))

    if args.dry_run:
        for i, (t, b) in enumerate(pairs):
            print(f"  [{i:3d}] ${b:.2f}  [{t['category']:<12}] {t['prompt'][:70]}")
        print(f"\nTotal: {len(pairs)} comparisons")
        cat_counts = {}
        for t, _ in pairs:
            cat_counts[t["category"]] = cat_counts.get(t["category"], 0) + 1
        print("By category:", cat_counts)
        return

    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_KEY")
    sb = create_client(supabase_url, supabase_key) if supabase_url and supabase_key else None

    results = []
    for i, (task_info, budget) in enumerate(pairs):
        task = task_info["prompt"]
        category = task_info["category"]
        prompt_id = task_info["prompt_id"]

        logger.info("[%d/%d] [%s] $%.2f  %s",
                    i + 1, len(pairs), category, budget, task[:60])
        try:
            result = run_comparison(
                api_key, task, budget,
                category=category,
                prompt_id=prompt_id,
            )
            results.append(result)

            if sb:
                sb.table("comparisons").insert(result).execute()

            logger.info("  quality %.1f vs %.1f | cost $%.4f vs $%.4f | savings %.0f%%",
                        result["pyrrhus_quality"] or 0,
                        result["baseline_quality"] or 0,
                        result["pyrrhus_cost"],
                        result["baseline_cost"],
                        result["cost_savings_pct"])

        except Exception:
            logger.error("  FAILED", exc_info=True)

        if i < len(pairs) - 1:
            time.sleep(args.delay)

    # CSV backup
    if results:
        csv_path = Path("dataset_mt_bench_comparisons.csv")
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=results[0].keys())
            writer.writeheader()
            writer.writerows(results)
        logger.info("CSV saved to %s (%d rows)", csv_path, len(results))

    # Summary
    print(f"\n{'='*70}")
    print("COLLECTION SUMMARY")
    print(f"{'='*70}")
    print(f"  Completed: {len(results)}/{len(pairs)}")

    if results:
        valid_p = [r for r in results if r["pyrrhus_quality"] is not None]
        valid_b = [r for r in results if r["baseline_quality"] is not None]

        avg_p = sum(r["pyrrhus_quality"] for r in valid_p) / len(valid_p) if valid_p else 0
        avg_b = sum(r["baseline_quality"] for r in valid_b) / len(valid_b) if valid_b else 0
        avg_savings = sum(r["cost_savings_pct"] for r in results) / len(results)

        print(f"  Avg Pyrrhus quality:  {avg_p:.1f}/10")
        print(f"  Avg Baseline quality: {avg_b:.1f}/10")
        print(f"  Avg cost savings:     {avg_savings:.1f}%")

        # Per-category breakdown
        cats = sorted(set(r["category"] for r in results))
        print(f"\n  {'Category':<14} {'P-Qual':>6} {'B-Qual':>6} {'Delta':>6} {'Savings':>8} {'N':>4}")
        print(f"  {'─'*14} {'─'*6} {'─'*6} {'─'*6} {'─'*8} {'─'*4}")
        for cat in cats:
            cat_rows = [r for r in results if r["category"] == cat]
            cp = [r for r in cat_rows if r["pyrrhus_quality"] is not None]
            cb = [r for r in cat_rows if r["baseline_quality"] is not None]
            p_avg = sum(r["pyrrhus_quality"] for r in cp) / len(cp) if cp else 0
            b_avg = sum(r["baseline_quality"] for r in cb) / len(cb) if cb else 0
            s_avg = sum(r["cost_savings_pct"] for r in cat_rows) / len(cat_rows)
            print(f"  {cat:<14} {p_avg:>6.1f} {b_avg:>6.1f} {p_avg - b_avg:>+6.1f} {s_avg:>7.1f}% {len(cat_rows):>4}")


if __name__ == "__main__":
    main()
