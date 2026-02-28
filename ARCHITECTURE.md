# Budget-Aware Multi-Agent Orchestration — Architecture

## One-Line Summary

An orchestration layer that decomposes tasks into a dependency graph, routes each subtask to a model tier (Fast / Deep / Verify) based on complexity, enforces a hard dollar budget by downgrading tiers when needed, and redistributes surplus tokens from under-budget subtasks to downstream work.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                        User Interface                   │
│                                                         │
│   Task description + Dollar budget                      │
│         │                                               │
│         ▼                                               │
│   Dollar budget → Token budget conversion               │
│   (using per-model pricing rates)                       │
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
│                                                         │
│  Tools available to Executor:                           │
│    @tool track_usage       — log actual tokens per call │
│    @tool reallocate_surplus — return surplus to pool    │
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

Each subtask is assigned to exactly one tier. Tier selection determines both the model used and the token cap for that call.Cr

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

The Executor collects the final deliverable (Subtask 5 output) and packages it with a cost report:

```
Budget:  $0.08
Spent:   $0.06

Breakdown:
  Subtask 1 (Research)    → Fast    → $0.004
  Subtask 2 (Summarize)   → Fast    → $0.008
  Subtask 3 (Trends)      → Deep    → $0.018
  Subtask 4 (Write)       → Deep    → $0.024
  Subtask 5 (Review)      → Verify  → $0.006

Remaining: $0.02 (returned to user)
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


| Component      | Tool           | Why                                              |
| -------------- | -------------- | ------------------------------------------------ |
| Data classes   | **Pydantic**   | Structured task graph and execution plan schemas |
| Env management | **.env files** | API keys only                                    |


### NOT Using


| Tool              | Why Not                                                                                                  |
| ----------------- | -------------------------------------------------------------------------------------------------------- |
| LangChain         | Adds abstraction without value. CAL decorators give us direct control over routing and budget mechanics. |
| Vector DB         | No RAG component. Subtask context is passed directly via FullCompressionMemory.                          |
| FastAPI / Next.js | No web server or dashboard in scope. CLI or notebook interface sufficient.                               |
| Docker            | No multi-service deployment. Single Python process.                                                      |


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
│   └── reallocate_surplus.py # @tool — returns surplus tokens to pool
│
├── models.py                 # Pydantic schemas: SubTask, TaskGraph, ExecutionPlan, CostReport
├── budget.py                 # Token budget pool: conversion, per-subtask caps, surplus tracking
├── memory.py                 # FullCompressionMemory config and helpers
├── main.py                   # Entry point: accept task + budget, run pipeline, print report
│
├── .env.example              # GOOGLE_API_KEY
├── requirements.txt
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

