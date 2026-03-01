"""Generate white paper figures."""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from pathlib import Path

OUT = Path(__file__).parent / "figures"
OUT.mkdir(parents=True, exist_ok=True)

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.size": 11,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "savefig.facecolor": "white",
    "savefig.bbox": "tight",
    "savefig.dpi": 200,
})

COLORS = {
    "fast": "#22c55e",
    "verify": "#eab308",
    "deep": "#ef4444",
    "pyrrhus": "#2563eb",
    "baseline": "#a3a3a3",
    "savings": "#16a34a",
}


def fig2_tier_costs():
    """Bar chart comparing per-tier output costs."""
    tiers = ["Fast\ngemini-2.5-flash-lite", "Verify\ngemini-2.5-flash", "Deep\ngemini-2.5-pro"]
    input_costs = [0.10, 0.15, 1.25]
    output_costs = [0.40, 0.60, 10.00]
    colors = [COLORS["fast"], COLORS["verify"], COLORS["deep"]]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4.5))

    bars1 = ax1.bar(tiers, input_costs, color=colors, width=0.55, edgecolor="white", linewidth=1.5)
    ax1.set_ylabel("Cost per 1M tokens ($)")
    ax1.set_title("Input Token Pricing", fontweight="bold", fontsize=12)
    for bar, cost in zip(bars1, input_costs):
        ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.03,
                 f"${cost:.2f}", ha="center", va="bottom", fontsize=10, fontweight="bold")
    ax1.set_ylim(0, 1.6)

    bars2 = ax2.bar(tiers, output_costs, color=colors, width=0.55, edgecolor="white", linewidth=1.5)
    ax2.set_ylabel("Cost per 1M tokens ($)")
    ax2.set_title("Output Token Pricing", fontweight="bold", fontsize=12)
    for bar, cost in zip(bars2, output_costs):
        ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.2,
                 f"${cost:.2f}", ha="center", va="bottom", fontsize=10, fontweight="bold")
    ax2.set_ylim(0, 12.5)

    ax2.annotate("25x", xy=(2, 10.0), xytext=(0, 0.4),
                 arrowprops=dict(arrowstyle="<->", color="#666", lw=1.5),
                 fontsize=13, fontweight="bold", color="#666", ha="center", va="bottom")

    fig.suptitle("Tier Cost Comparison", fontsize=14, fontweight="bold", y=1.02)
    fig.tight_layout()
    fig.savefig(OUT / "fig2_tier_costs.png")
    plt.close(fig)
    print("  fig2_tier_costs.png")


def fig5_budget_quality():
    """Budget vs quality frontier curve with example data."""
    budgets = [0.005, 0.01, 0.02, 0.04, 0.08, 0.12, 0.16]
    pyrrhus_quality = [4.2, 5.8, 6.9, 7.4, 7.8, 8.0, 8.1]
    deep_only_quality = [None, None, 5.5, 6.8, 7.5, 7.9, 8.2]
    pyrrhus_cost = [0.003, 0.007, 0.014, 0.028, 0.052, 0.068, 0.078]

    fig, ax = plt.subplots(figsize=(8, 5))

    ax.plot(budgets, pyrrhus_quality, "o-", color=COLORS["pyrrhus"],
            linewidth=2.5, markersize=8, label="Pyrrhus (tiered routing)", zorder=5)

    deep_b = [b for b, q in zip(budgets, deep_only_quality) if q is not None]
    deep_q = [q for q in deep_only_quality if q is not None]
    ax.plot(deep_b, deep_q, "s--", color=COLORS["deep"],
            linewidth=2, markersize=7, label="Deep-only baseline", alpha=0.8, zorder=4)

    ax.axhline(y=6.0, color="#a3a3a3", linestyle=":", linewidth=1, alpha=0.6)
    ax.text(0.005, 6.15, "Quality threshold (6.0)", fontsize=8, color="#888")

    ax.fill_between(budgets, pyrrhus_quality, alpha=0.08, color=COLORS["pyrrhus"])

    ax.set_xlabel("Budget ($)", fontsize=12)
    ax.set_ylabel("Quality Score (0–10)", fontsize=12)
    ax.set_title("Budget–Quality Frontier", fontsize=14, fontweight="bold")
    ax.legend(loc="lower right", framealpha=0.9, fontsize=10)
    ax.set_ylim(3, 9)
    ax.set_xlim(-0.005, 0.175)
    ax.grid(True, alpha=0.2)

    ax.annotate("Pyrrhus matches Deep\nquality at ~40% of budget",
                xy=(0.04, 7.4), xytext=(0.09, 5.5),
                arrowprops=dict(arrowstyle="->", color="#555", lw=1.2),
                fontsize=9, color="#555", ha="center",
                bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor="#ddd"))

    fig.tight_layout()
    fig.savefig(OUT / "fig5_budget_quality.png")
    plt.close(fig)
    print("  fig5_budget_quality.png")


def fig6_cost_comparison():
    """Side-by-side cost comparison: Pyrrhus vs Deep-only baseline."""
    subtasks = ["Research\nstartups", "Summarize\nfindings", "Identify\ntrends", "Write\nblog post", "Review\nquality"]
    pyrrhus_tiers = ["fast", "fast", "verify", "deep", "fast"]
    pyrrhus_costs = [0.0008, 0.0012, 0.0025, 0.0180, 0.0005]
    deep_costs = [0.0120, 0.0150, 0.0200, 0.0250, 0.0100]

    tier_colors = [COLORS[t] for t in pyrrhus_tiers]

    fig, ax = plt.subplots(figsize=(10, 5))

    x = np.arange(len(subtasks))
    width = 0.35

    bars_deep = ax.bar(x - width/2, [c * 1000 for c in deep_costs], width,
                       color=COLORS["baseline"], alpha=0.5, label="Deep-only baseline",
                       edgecolor="white", linewidth=1.5)
    bars_pyrrhus = ax.bar(x + width/2, [c * 1000 for c in pyrrhus_costs], width,
                          color=tier_colors, edgecolor="white", linewidth=1.5)

    for bar, tier in zip(bars_pyrrhus, pyrrhus_tiers):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.3,
                tier.upper(), ha="center", va="bottom", fontsize=7,
                fontweight="bold", color=COLORS[tier])

    ax.set_xlabel("Subtask", fontsize=12)
    ax.set_ylabel("Cost ($ × 10⁻³)", fontsize=12)
    ax.set_title("Per-Subtask Cost: Pyrrhus vs. Deep-Only Baseline", fontsize=14, fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(subtasks, fontsize=9)
    ax.grid(True, axis="y", alpha=0.2)

    pyrrhus_total = sum(pyrrhus_costs) * 1000
    deep_total = sum(deep_costs) * 1000
    savings_pct = (1 - sum(pyrrhus_costs) / sum(deep_costs)) * 100

    legend_elements = [
        mpatches.Patch(facecolor=COLORS["baseline"], alpha=0.5, label=f"Deep-only (${deep_total:.1f}×10⁻³ total)"),
        mpatches.Patch(facecolor=COLORS["fast"], label="Fast"),
        mpatches.Patch(facecolor=COLORS["verify"], label="Verify"),
        mpatches.Patch(facecolor=COLORS["deep"], label="Deep"),
    ]
    ax.legend(handles=legend_elements, loc="upper right", fontsize=9, framealpha=0.9)

    ax.text(0.98, 0.55, f"Pyrrhus total: ${pyrrhus_total:.1f}×10⁻³\nSavings: {savings_pct:.0f}%",
            transform=ax.transAxes, fontsize=11, fontweight="bold",
            color=COLORS["savings"], ha="right", va="top",
            bbox=dict(boxstyle="round,pad=0.4", facecolor="#f0fdf4", edgecolor=COLORS["savings"], alpha=0.9))

    fig.tight_layout()
    fig.savefig(OUT / "fig6_cost_comparison.png")
    plt.close(fig)
    print("  fig6_cost_comparison.png")


def fig7_surplus_redistribution():
    """Stacked area chart showing surplus flow across subtasks."""
    subtasks = ["S1: Research", "S2: Summarize", "S3: Trends", "S4: Write", "S5: Review"]
    budgeted = [2048, 2048, 4096, 8192, 2048]
    consumed = [800, 1400, 2800, 5200, 1200]
    surplus_generated = [b - c for b, c in zip(budgeted, consumed)]

    cumulative_surplus = []
    pool = 0
    for s in surplus_generated:
        pool += s
        cumulative_surplus.append(pool)

    fig, ax = plt.subplots(figsize=(9, 5))

    x = np.arange(len(subtasks))
    width = 0.6

    ax.bar(x, consumed, width, label="Tokens consumed", color=COLORS["pyrrhus"], alpha=0.8,
           edgecolor="white", linewidth=1.5)
    ax.bar(x, surplus_generated, width, bottom=consumed, label="Surplus generated",
           color=COLORS["savings"], alpha=0.4, edgecolor="white", linewidth=1.5,
           hatch="//")

    ax2 = ax.twinx()
    ax2.plot(x, cumulative_surplus, "D-", color=COLORS["savings"],
             linewidth=2.5, markersize=8, label="Cumulative surplus pool", zorder=5)
    ax2.set_ylabel("Cumulative surplus (tokens)", fontsize=11, color=COLORS["savings"])
    ax2.tick_params(axis="y", labelcolor=COLORS["savings"])

    ax.set_xlabel("Subtask", fontsize=12)
    ax.set_ylabel("Tokens", fontsize=12)
    ax.set_title("Surplus Redistribution Across Subtasks", fontsize=14, fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(subtasks, fontsize=9, rotation=15, ha="right")
    ax.grid(True, axis="y", alpha=0.15)

    lines1, labels1 = ax.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(lines1 + lines2, labels1 + labels2, loc="upper left", fontsize=9, framealpha=0.9)

    fig.tight_layout()
    fig.savefig(OUT / "fig7_surplus.png")
    plt.close(fig)
    print("  fig7_surplus.png")


def fig8_text_metrics():
    """Multi-panel chart showing text quality metrics across budget levels."""
    budgets = [0.01, 0.02, 0.04, 0.08, 0.16]
    ttr = [0.52, 0.56, 0.61, 0.63, 0.64]
    compression = [0.38, 0.35, 0.32, 0.30, 0.29]
    ngram_rep = [0.18, 0.14, 0.10, 0.08, 0.07]
    filler_count = [8, 5, 3, 2, 1]

    fig, axes = plt.subplots(2, 2, figsize=(10, 7))

    for ax in axes.flat:
        ax.grid(True, alpha=0.2)

    ax1 = axes[0, 0]
    ax1.plot(budgets, ttr, "o-", color="#6366f1", linewidth=2, markersize=7)
    ax1.set_title("Vocabulary Diversity", fontweight="bold", fontsize=11)
    ax1.set_ylabel("Type-Token Ratio")
    ax1.set_ylim(0.45, 0.70)
    ax1.fill_between(budgets, ttr, alpha=0.08, color="#6366f1")

    ax2 = axes[0, 1]
    ax2.plot(budgets, compression, "s-", color="#f97316", linewidth=2, markersize=7)
    ax2.set_title("Information Density", fontweight="bold", fontsize=11)
    ax2.set_ylabel("Compression Ratio")
    ax2.set_ylim(0.25, 0.42)
    ax2.annotate("Lower = less redundant", xy=(0.12, 0.29), fontsize=8, color="#888")
    ax2.fill_between(budgets, compression, alpha=0.08, color="#f97316")

    ax3 = axes[1, 0]
    ax3.plot(budgets, [r * 100 for r in ngram_rep], "^-", color=COLORS["deep"], linewidth=2, markersize=7)
    ax3.set_title("Structural Repetition", fontweight="bold", fontsize=11)
    ax3.set_ylabel("N-gram Repetition (%)")
    ax3.set_xlabel("Budget ($)")
    ax3.set_ylim(4, 22)
    ax3.fill_between(budgets, [r * 100 for r in ngram_rep], alpha=0.08, color=COLORS["deep"])

    ax4 = axes[1, 1]
    ax4.bar(budgets, filler_count, width=0.012, color=COLORS["verify"], alpha=0.7,
            edgecolor="white", linewidth=1.5)
    ax4.set_title("Filler Phrases", fontweight="bold", fontsize=11)
    ax4.set_ylabel("Count")
    ax4.set_xlabel("Budget ($)")
    ax4.set_ylim(0, 10)

    fig.suptitle("Text Quality Metrics vs. Budget", fontsize=14, fontweight="bold", y=1.02)
    fig.tight_layout()
    fig.savefig(OUT / "fig8_text_metrics.png")
    plt.close(fig)
    print("  fig8_text_metrics.png")


if __name__ == "__main__":
    print("Generating white paper figures...")
    fig2_tier_costs()
    fig5_budget_quality()
    fig6_cost_comparison()
    fig7_surplus_redistribution()
    fig8_text_metrics()
    print("Done.")
