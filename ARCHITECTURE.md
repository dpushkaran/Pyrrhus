# Budget-Aware Multi-Agent Orchestration — Architecture

## One-Line Summary

An orchestration layer that decomposes tasks into a dependency graph, routes each subtask to a model tier (Fast / Deep / Verify) based on complexity, enforces a hard dollar budget by downgrading tiers when needed, and redistributes surplus tokens from under-budget subtasks to downstream work.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────┐
│              User Interface (Next.js + shadcn/ui)       │
│              Deployed on Vercel (static export)         │
│                                                         │
│   Task description + Dollar budget                      │
│         │                                               │
│         ▼                                               │
│   POST /api/run → Flask API (JSON)                      │
│         │                                               │
│         ▼                                               │
│   Dollar budget → Token budget conversion               │
│   (using per-model pricing rates)                       │
│         │                                               │
│         ▼                                               │
│   Dashboard renders CostReport with all 6 metric        │
│   sections + interactive dependency graph (SVG DAG)     │
└───────────────────────┬─────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────┐
│                  Planner Agent                          │
│                                                         │
│  - Takes user prompt                                    │
│  - Decomposes into discrete subtasks                    │
│  - Assigns each subtask a complexity rating             │
│    (Low / Medium / High)                                │
│  - Identifies dependencies between subtasks             │
│  - Outputs a structured task graph (DAG)                │
└───────────────────────┬─────────────────────────────────┘
                        │  task graph (subtasks + complexity + deps)
                        ▼
┌─────────────────────────────────────────────────────────┐
│                  Allocator Agent                        │
│                                                         │
│  - Maps complexity to default tier:                     │
│      Low → Fast  |  Medium → Verify  |  High → Deep     │
│  - Estimates token cost per subtask at assigned tier    │
│  - Checks if total cost fits within token budget        │
│  - If over budget: downgrades least-critical Deep tasks │
│    to Verify or Fast; skips low-stakes Verify subtasks  │
│  - Outputs execution plan: subtask → tier + token cap   │
└───────────────────────┬─────────────────────────────────┘
                        │  execution plan
                        ▼
┌─────────────────────────────────────────────────────────┐
│                  Executor Agent                         │
│                                                         │
│  - Walks task graph respecting dependencies             │
│  - Dispatches each subtask to the assigned tier agent   │
│    via @subagent decorator                              │
│  - Passes prior subtask outputs as context              │
│    via FullCompressionMemory                            │
│  - After each subtask: logs actual tokens consumed      │
│  - Computes surplus (budgeted − actual) and adds it     │
│    back to the remaining token pool                     │
│  - Collects all outputs and assembles final deliverable │
│  - Builds output metrics and cost report                │
│                                                         │
│  Tools available to Executor:                           │
│    @tool track_usage       — log actual tokens per call │
│    @tool reallocate_surplus — return surplus to pool    │
│    @tool build_report      — assemble metrics + output  │
└──────┬──────────────┬───────────────┬───────────────────┘
       │              │               │
       ▼              ▼               ▼
┌───────────┐  ┌───────────┐  ┌───────────┐
│  Fast     │  │  Deep     │  │  Verify   │
│  Agent    │  │  Agent    │  │  Agent    │
│           │  │           │  │           │
│ @subagent │  │ @subagent │  │ @subagent │
│           │  │           │  │           │
│ gemini-   │  │ gemini-   │  │ gemini-   │
│ 2.0-flash │  │ 2.5-pro   │  │ 2.5-flash │
│           │  │           │  │           │
│ max_tokens│  │ max_tokens│  │ max_tokens│
│  = 1024   │  │  = 4096   │  │  = 2048   │
└───────────┘  └───────────┘  └───────────┘
       │              │               │
       └──────────────┴───────────────┘
                        │
                        ▼
              ┌──────────────────┐
              │   Gemini API     │
              │ (Google AI SDK)  │
              └──────────────────┘
```

---

## Tier System

Each subtask is assigned to exactly one tier. Tier selection determines both the model used and the token cap for that call.

### Tier Definitions


| Tier   | Model            | max_tokens | Default for Complexity |
| ------ | ---------------- | ---------- | ---------------------- |
| Fast   | gemini-2.0-flash | 1024       | Low                    |
| Deep   | gemini-2.5-pro   | 4096       | High                   |
| Verify | gemini-2.5-flash | 2048       | Medium                 |


### Complexity-to-Tier Mapping

The Planner tags each subtask with a complexity rating. The Allocator uses this as the starting point:

```
Low    → Fast   (simple lookups, retrieval, formatting)
Medium → Verify (quality checks, moderate synthesis)
High   → Deep   (creative writing, trend analysis, multi-source reasoning)
```

### Budget-Driven Downgrading

After mapping complexity to tiers, the Allocator estimates the total token cost. If the estimate exceeds the budget, it applies downgrades in this order:

1. Push the least critical `Deep` subtasks down to `Verify`
2. Push remaining `Deep` subtasks down to `Fast` if still over budget
3. Skip `Verify` subtasks on low-stakes steps entirely
4. Reduce `max_tokens` caps on remaining calls proportionally

The Allocator never upgrades a tier above its complexity-mapped default.

### Surplus Redistribution

After each subtask completes, the Executor calls `reallocate_surplus`:

```
surplus = budgeted_tokens − actual_tokens_used
remaining_pool += surplus
```

Downstream subtasks with remaining budget headroom may receive a slight token cap increase if the pool has grown.

---

## Inference Flow (Single Run)

Concrete example: `"Research and write a blog post about the best AI startups in 2025"` with a budget of `$0.08`.

### Step 1 — User Input

The user provides a task description and a dollar budget. The system converts dollars to tokens using per-model pricing:

```
gemini-2.0-flash  → $0.10 / 1M tokens
gemini-2.5-flash  → $0.40 / 1M tokens  (estimate)
gemini-2.5-pro    → $1.25 / 1M tokens

$0.08 budget → ~80,000 Fast-equivalent tokens (weighted by expected tier mix)
```

### Step 2 — Planner Decomposes the Task

The Planner outputs a task graph:

```
Subtask 1: "List notable AI startups founded or funded in 2025"
   Complexity: Low   | Dependencies: none

Subtask 2: "For each startup, summarize what they do and why they matter"
   Complexity: Low   | Dependencies: [1]

Subtask 3: "Identify trends and themes across the startups"
   Complexity: High  | Dependencies: [2]

Subtask 4: "Write a cohesive blog post from the research"
   Complexity: High  | Dependencies: [2, 3]

Subtask 5: "Review the blog post for accuracy and quality"
   Complexity: Medium | Dependencies: [4]
```

### Step 3 — Allocator Routes Subtasks to Tiers

Starting from complexity defaults, the Allocator estimates costs and checks budget fit:

```
Subtask 1 → Fast    (~500 tokens)
Subtask 2 → Fast    (~1,000 tokens)
Subtask 3 → Deep    (~2,000 tokens)
Subtask 4 → Deep    (~3,000 tokens)
Subtask 5 → Verify  (~1,000 tokens)

Estimated total: fits within $0.08 → no downgrades needed
```

If budget were `$0.02`, the Allocator would downgrade Subtask 3 to `Fast` and drop Subtask 5 entirely.

### Step 4 — Executor Runs the Plan

The Executor walks the DAG, dispatching subtasks to tier agents:

```
1. Subtask 1 (no deps) → Fast (max_tokens=1024)
   Actual tokens: 400 | Surplus: +100 → returned to pool

2. Subtask 2 (deps: [1]) → Fast (max_tokens=1024)
   Context: Subtask 1 output via FullCompressionMemory
   Actual tokens: 900 | Surplus: +100 → returned to pool

3. Subtask 3 (deps: [2]) → Deep (max_tokens=4096)
   Context: Subtask 2 output
   Actual tokens: 1,800 | Surplus: +200 → returned to pool

4. Subtask 4 (deps: [2, 3]) → Deep (max_tokens=4096)
   Context: Subtasks 2 + 3 output
   Actual tokens: 2,600 | Surplus: +400 → returned to pool

5. Subtask 5 (deps: [4]) → Verify (max_tokens=2048)
   Context: Subtask 4 output
   Actual tokens: 800 | Surplus: +200 → returned to pool
```

### Step 5 — Assembly and Output

The Executor collects the final deliverable (Subtask 5 output) and packages it with the full output metrics (see **Output Metrics** below). The user sees the deliverable alongside budget summary, per-subtask breakdown, tier distribution, downgrade report (if applicable), and efficiency stats:

```
Budget:  $0.08
Spent:   $0.06
Remaining: $0.02 (returned to user)
Utilization: 75%

Subtask Breakdown:
  #  Name         Tier     Budgeted  Consumed  Cost     Surplus
  1  Research     Fast     500       400       $0.004   +100
  2  Summarize    Fast     1,000     900       $0.008   +100
  3  Trends       Deep     2,000     1,800     $0.018   +200
  4  Write        Deep     3,000     2,600     $0.024   +400
  5  Review       Verify   1,000     800       $0.006   +200

Tier Distribution:
  Fast: 2 subtasks (40%)  |  Deep: 2 subtasks (40%)  |  Verify: 1 subtask (20%)

Downgrades: none
Subtasks Skipped: none

Efficiency:
  Tokens budgeted: 7,500  |  Tokens consumed: 6,500  |  Efficiency: 86.7%
  Total surplus generated: 1,000 tokens

Task Graph:
  Total subtasks: 5  |  Max depth: 4  |  Parallelizable: 0
  Complexity: 2 Low, 2 High, 1 Medium
```

---

## Output Metrics

Every completed run returns the deliverable alongside a structured metrics report. Metrics are grouped into six categories, ordered from highest to lowest priority.

### 1. Budget Summary

The headline numbers. Always shown.

| Metric | Source | Example |
|---|---|---|
| Dollar budget | User input | $0.08 |
| Dollar spent | Sum of per-subtask costs | $0.06 |
| Dollar remaining | Budget - spent | $0.02 |
| Budget utilization | Spent / budget | 75% |

### 2. Per-Subtask Breakdown

One row per subtask. Each row is populated by `track_usage` after the subtask completes.

| Field | Description |
|---|---|
| Subtask name | Short label from the Planner (e.g. "Research", "Write") |
| Assigned tier | Fast / Deep / Verify |
| Tokens budgeted | Token cap assigned by the Allocator |
| Tokens consumed | Actual tokens reported by the Gemini API response |
| Subtask cost | Dollar cost computed from consumed tokens at the tier's pricing rate |
| Surplus returned | Budgeted - consumed, added back to pool via `reallocate_surplus` |

### 3. Tier Distribution

Aggregated from the Allocator's execution plan. Shows the quality profile of the run.

| Metric | Description |
|---|---|
| Subtasks per tier | Count and percentage routed to Fast / Deep / Verify |
| Subtasks skipped | Count of subtasks dropped entirely due to budget pressure |
| Subtasks downgraded | Count of subtasks assigned a lower tier than their complexity default |

A budget-constrained run shows more subtasks pushed to Fast and skipped verification steps — the user immediately sees the quality tradeoff their budget imposed.

### 4. Downgrade Report

Shown only when the Allocator applied budget-driven downgrades. Makes the cost-vs-quality tradeoff explicit.

| Metric | Description |
|---|---|
| Original plan cost | Estimated dollar cost before any downgrades |
| Final plan cost | Estimated dollar cost after downgrades |
| Downgrades applied | List of subtasks with their original tier and final tier |
| Subtasks skipped | List of subtasks dropped entirely |

### 5. Efficiency Stats

Derived from token tracking across all subtasks.

| Metric | Description |
|---|---|
| Total tokens budgeted | Sum of all per-subtask token caps |
| Total tokens consumed | Sum of all actual tokens used |
| Total surplus generated | Budgeted - consumed across all subtasks |
| Token efficiency | Consumed / budgeted as a percentage |

### 6. Task Graph Summary

From the Planner's output. Gives the user a sense of how the system decomposed their request.

| Metric | Description |
|---|---|
| Total subtasks | Number of subtasks in the DAG |
| Max dependency depth | Longest path through the DAG |
| Parallelizable subtasks | Subtasks with no shared dependencies that could run concurrently |
| Complexity distribution | Count of Low / Medium / High subtasks |

### Where Each Metric Comes From

```
User Input ──────────────────────► Budget Summary (dollar budget)
Planner ─────────────────────────► Task Graph Summary (subtask count, depth, complexity)
Allocator ───────────────────────► Tier Distribution, Downgrade Report
Executor (track_usage) ──────────► Per-Subtask Breakdown, Efficiency Stats
Executor (reallocate_surplus) ───► Surplus fields in Per-Subtask Breakdown
Executor (build_report) ─────────► Final assembled CostReport with all metrics
```

---

## How It Maps to CAL

Each component maps directly to CAL primitives:


| Component            | CAL Primitive                                                                            |
| -------------------- | ---------------------------------------------------------------------------------------- |
| Planner              | `CAL.Agent` with mid-tier `GeminiLLM` config                                             |
| Allocator            | `CAL.Agent` with logic tools for cost estimation                                         |
| Executor             | `CAL.Agent` whose tools are the three tier agents + `track_usage` + `reallocate_surplus` |
| Fast / Deep / Verify | `CAL.Agent` instances, each decorated with `@subagent`                                   |
| `track_usage`        | `@tool` — logs actual tokens consumed per subtask                                        |
| `reallocate_surplus` | `@tool` — computes surplus and adds it back to pool                                      |
| `build_report`       | `@tool` — assembles CostReport with all six metric categories                            |
| Context passing      | `FullCompressionMemory` — passes relevant prior outputs without exceeding token caps     |


---

## Tech Stack

### Core Framework


| Component       | Tool                                                                                  | Why                                                                                      |
| --------------- | ------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| Agent framework | **CAL** (Python)                                                                      | Native `@subagent`, `@tool`, `FullCompressionMemory` abstractions for this exact pattern |
| LLM calls       | **Google AI Python SDK**                                                              | Direct Gemini API access, usage stats in response                                        |
| Models          | **gemini-2.0-flash** (Fast), **gemini-2.5-pro** (Deep), **gemini-2.5-flash** (Verify) | Tiered capability and cost                                                               |


### Supporting


| Component      | Tool                | Why                                                                        |
| -------------- | ------------------- | -------------------------------------------------------------------------- |
| Data classes   | **Pydantic**        | Structured task graph and execution plan schemas                           |
| Env management | **.env files**      | API keys only                                                              |
| API server     | **Flask + CORS**    | Lightweight JSON API exposing `/api/run` and `/api/report` to the frontend |

### Frontend


| Component       | Tool                   | Why                                                                           |
| --------------- | ---------------------- | ----------------------------------------------------------------------------- |
| Framework       | **Next.js 14**         | App Router, static export for Vercel deployment, TypeScript                   |
| UI components   | **shadcn/ui**          | Pre-built accessible components (Card, Table, Badge, Progress, etc.)          |
| Styling         | **Tailwind CSS**       | Utility-first CSS, monochromatic neutral theme via shadcn/ui                  |
| Fonts           | **Inter + JetBrains Mono** | Clean sans-serif for UI, monospace for data — loaded via `next/font`      |
| Deployment      | **Vercel**             | Zero-config static hosting for the Next.js export                             |


### NOT Using


| Tool              | Why Not                                                                                                  |
| ----------------- | -------------------------------------------------------------------------------------------------------- |
| LangChain         | Adds abstraction without value. CAL decorators give us direct control over routing and budget mechanics. |
| Vector DB         | No RAG component. Subtask context is passed directly via FullCompressionMemory.                          |
| Docker            | No multi-service deployment. Python API + static frontend.                                               |


---

## Project Structure

```
/
├── agents/
│   ├── planner.py            # CAL.Agent — decomposes task into subtask DAG
│   ├── allocator.py          # CAL.Agent — routes subtasks to tiers, enforces budget
│   ├── executor.py           # CAL.Agent — walks DAG, dispatches to tier agents
│   └── tiers/
│       ├── fast.py           # @subagent — gemini-2.0-flash, max_tokens=1024
│       ├── deep.py           # @subagent — gemini-2.5-pro, max_tokens=4096
│       └── verify.py         # @subagent — gemini-2.5-flash, max_tokens=2048
│
├── tools/
│   ├── track_usage.py        # @tool — logs actual tokens consumed per subtask
│   ├── reallocate_surplus.py # @tool — returns surplus tokens to pool
│   └── build_report.py       # @tool — assembles CostReport with all metric categories
│
├── dashboard/
│   ├── __init__.py
│   └── app.py                # Flask API server — JSON-only, CORS-enabled
│                              #   POST /api/run    — accepts task + budget, returns CostReport
│                              #   GET  /api/report — returns latest report
│
├── frontend/                  # Next.js 14 + shadcn/ui (static export → Vercel)
│   ├── src/
│   │   ├── app/
│   │   │   ├── layout.tsx     # Root layout — Inter + JetBrains Mono fonts
│   │   │   ├── page.tsx       # Input page — task textarea + budget field + Run button
│   │   │   └── report/
│   │   │       └── page.tsx   # Dashboard — all 6 metric sections + DAG
│   │   ├── components/
│   │   │   ├── dag-graph.tsx  # SVG dependency graph React component
│   │   │   └── ui/           # shadcn/ui components (card, table, badge, etc.)
│   │   └── lib/
│   │       ├── types.ts       # TypeScript interfaces mirroring Pydantic models
│   │       └── utils.ts       # shadcn/ui utility (cn)
│   ├── next.config.ts         # output: "export" for static generation
│   ├── package.json
│   └── tailwind.config.ts
│
├── models.py                 # Pydantic schemas: SubTask, TaskGraph, ExecutionPlan,
│                              #   CostReport, SubtaskMetrics, TierDistribution,
│                              #   DowngradeReport, EfficiencyStats, TaskGraphSummary
├── budget.py                 # Token budget pool: conversion, per-subtask caps, surplus tracking
├── memory.py                 # FullCompressionMemory config and helpers
├── main.py                   # Entry point: accept task + budget, run pipeline, print report
│
├── .env.example              # GOOGLE_API_KEY
├── requirements.txt          # Python deps (google-genai, pydantic, flask, flask-cors)
└── ARCHITECTURE.md           # This file
```

---

## Key Design Decisions

1. **Budget is a ceiling, not a target.** The system should return unspent tokens. The Allocator intentionally builds in buffer; draining to zero means downgrading logic failed.
2. **Tier selection is the primary lever, not prompt engineering.** Routing a subtask to `Fast` vs `Deep` has a larger cost impact than tweaking the prompt. The Allocator treats tier assignment as the main budget knob.
3. **Downgrading is ordered by criticality.** The Allocator downgrades the subtasks least likely to affect final output quality first (e.g., a retrieval step before a synthesis step). Dependency position in the DAG is a proxy for criticality.
4. **Surplus redistribution is opportunistic, not guaranteed.** Downstream subtasks get a token cap increase only if the pool has grown and the subtask is not already at its tier's max. The Allocator's original plan is not re-run.
5. **FullCompressionMemory prevents context blowup.** Passing all prior subtask outputs verbatim would exhaust token budgets on later subtasks. FullCompressionMemory compresses history to fit within the receiving agent's cap.
6. **Agents are stateless per invocation.** Each tier agent call is a single LLM invocation with a prompt template plus compressed context. No persistent state between calls.
7. **The Executor is itself a CAL agent.** Its tools are the three tier agents (via `@subagent`) plus `track_usage` and `reallocate_surplus` (via `@tool`). This keeps the orchestration logic expressible as a single agent loop rather than imperative orchestration code.
8. **Frontend and backend are decoupled.** The Next.js frontend is a static export deployed to Vercel. The Flask API serves JSON only — no templates, no server-rendered HTML. The frontend communicates via `NEXT_PUBLIC_API_URL`, making the API host configurable per environment. This separation allows independent deployment and scaling of the UI and the orchestration backend.

