# Budget-Aware Multi-Agent Orchestration — Architecture

## One-Line Summary

An orchestration layer that dynamically allocates token budget across LLM agents, stops reasoning when marginal ROI drops, and surfaces cost-vs-quality tradeoffs in a live dashboard.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                      Frontend (Next.js + Shadcn)        │
│                                                         │
│  ┌──────────┐  ┌──────────┐  ┌────────────────────────┐│
│  │ Task     │  │ Strategy │  │ Live Dashboard         ││
│  │ Input    │  │ Selector │  │  - Token spend timeline ││
│  │          │  │          │  │  - ROI per agent        ││
│  │          │  │          │  │  - Quality curve        ││
│  │          │  │          │  │  - Budget remaining     ││
│  └──────────┘  └──────────┘  └────────────────────────┘│
│                                                         │
│  ┌────────────────────────────────────────────────────┐ │
│  │ Results Comparison View (Run A vs Run B)           │ │
│  │  - Side-by-side traces                             │ │
│  │  - Cost vs quality graph                           │ │
│  │  - Agent cutoff events                             │ │
│  └────────────────────────────────────────────────────┘ │
└──────────────────┬──────────────────────────────────────┘
                   │ WebSocket / SSE (live updates)
                   │ REST API (task submission, results)
                   ▼
┌─────────────────────────────────────────────────────────┐
│                   Backend (FastAPI + Python)             │
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │              Orchestrator (main loop)            │    │
│  │                                                  │    │
│  │  1. Receive task + budget + strategy mode        │    │
│  │  2. Run pre-flight check (complexity estimate)   │    │
│  │  3. Allocate initial budget per strategy         │    │
│  │  4. Loop: run agent → track tokens → score ROI   │    │
│  │  5. Reallocate or cut off based on marginal ROI  │    │
│  │  6. Stop when ROI < threshold OR budget ceiling  │    │
│  │  7. Return output + full cost report             │    │
│  └──────┬──────────────┬───────────────┬────────────┘    │
│         │              │               │                │
│         ▼              ▼               ▼                │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐           │
│  │  Planner  │  │ Executor  │  │  Critic   │           │
│  │  Agent    │  │ Agent     │  │  Agent    │           │
│  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘           │
│        └───────────────┴───────────────┘                │
│                        │                                │
│                        ▼                                │
│  ┌─────────────────────────────────────────────────┐    │
│  │              Budget Controller                   │    │
│  │                                                  │    │
│  │  - Global token pool (hard ceiling)              │    │
│  │  - Per-agent soft allocations                    │    │
│  │  - Enforces budget before every LLM call         │    │
│  │  - Tracks: tokens_used, tokens_remaining         │    │
│  └─────────────────────────────────────────────────┘    │
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │              Token Tracker                       │    │
│  │                                                  │    │
│  │  - Wraps every LLM API call                      │    │
│  │  - Reads prompt_tokens + completion_tokens       │    │
│  │    from API response                             │    │
│  │  - Reports usage back to Budget Controller       │    │
│  │  - Emits events for frontend via WebSocket       │    │
│  └─────────────────────────────────────────────────┘    │
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │              ROI Evaluator                       │    │
│  │                                                  │    │
│  │  - After each agent step, scores output quality  │    │
│  │    using proxy metrics:                          │    │
│  │      • Self-eval score (LLM rates own output)    │    │
│  │      • Critique flags resolved                   │    │
│  │      • Structural completeness (checklist)       │    │
│  │  - Computes: quality_delta / tokens_spent        │    │
│  │  - Feeds ROI back to Orchestrator for decisions  │    │
│  └─────────────────────────────────────────────────┘    │
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │              Pre-flight Check                    │    │
│  │                                                  │    │
│  │  - Cheap LLM call (~200 tokens) to classify      │    │
│  │    task complexity: simple / moderate / complex   │    │
│  │  - Maps complexity to minimum viable budget      │    │
│  │  - If user budget < minimum: warn or scope-down  │    │
│  └─────────────────────────────────────────────────┘    │
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │              Run Logger                          │    │
│  │                                                  │    │
│  │  - Persists full traces per run (SQLite/JSON)    │    │
│  │  - Stores: agent, iteration, tokens, quality,    │    │
│  │    ROI, cutoff reason                            │    │
│  │  - Enables side-by-side comparison across runs   │    │
│  └─────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
                   │
                   ▼
         ┌──────────────────┐
         │  LLM API         │
         │  (OpenAI / etc.) │
         └──────────────────┘
```

---

## Strategy Modes

### Mode A — Frontload Planning
| Agent    | Initial Allocation |
|----------|--------------------|
| Planner  | 50%                |
| Executor | 40%                |
| Critic   | 10%                |

Spend heavily on planning upfront. Minimal critique. Bet that a good plan reduces downstream iteration.

### Mode B — Critique Heavy
| Agent    | Initial Allocation |
|----------|--------------------|
| Planner  | 15%                |
| Executor | 35%                |
| Critic   | 50%                |

Minimal plan, produce a draft fast, then iterate through critique loops. Bet that refinement is cheaper than planning.

### Mode C — Adaptive (Default)
| Agent    | Initial Allocation |
|----------|--------------------|
| Planner  | 30%                |
| Executor | 40%                |
| Critic   | 30%                |

Start balanced. After each iteration, reallocate remaining budget toward whichever agent has the highest marginal ROI. Cut off agents whose ROI drops below threshold.

---

## Inference Flow (Single Run)

```
1. User submits: { task, budget: 20000, strategy: "adaptive" }
2. Pre-flight check: classify complexity → estimate minimum budget
   - If budget < minimum → return warning + suggested minimum
3. Allocate: Planner=6000, Executor=8000, Critic=6000
4. LOOP:
   a. Planner produces plan           → tokens: 2100, quality: 0 → 62
   b. Executor produces draft         → tokens: 3400, quality: 62 → 78
   c. Critic reviews draft            → tokens: 1200, quality_delta: +8
   d. Executor revises                → tokens: 2800, quality: 78 → 88
   e. Critic reviews again            → tokens: 1100, quality_delta: +2
   f. Critic ROI (2/1100 = 0.0018) < threshold (0.005) → STOP CRITIC
   g. Return remaining critic budget to pool
   h. Executor final pass             → tokens: 1900, quality: 90 → 92
5. Total spent: 12,500 / 20,000 (7,500 tokens returned unspent)
6. Return: { output, cost_report, traces }
```

---

## Tech Stack

### Backend
| Component          | Tool                    | Why                                              |
|--------------------|-------------------------|--------------------------------------------------|
| API server         | **FastAPI** (Python)    | Async, fast, WebSocket support, quick to build   |
| LLM calls          | **OpenAI Python SDK**   | Direct, well-documented, usage stats in response |
| Multi-provider     | **LiteLLM** (optional)  | Swap between OpenAI/Anthropic/local without code changes |
| Data persistence   | **SQLite**              | Zero-config, single file, sufficient for demo    |
| Real-time updates  | **WebSocket** (FastAPI) | Push token events to frontend live               |

### Frontend
| Component          | Tool                    | Why                                              |
|--------------------|-------------------------|--------------------------------------------------|
| Framework          | **Next.js 14** (App Router) | Fast, modern, great DX                       |
| UI components      | **Shadcn/ui**           | Polished, accessible, composable                 |
| Charts             | **Recharts**            | Simple, React-native charting for dashboards     |
| Styling            | **Tailwind CSS**        | Comes with Shadcn, fast to iterate               |
| State / real-time  | **React hooks + WebSocket** | Live dashboard updates                       |

### Infrastructure
| Component          | Tool                    | Why                                              |
|--------------------|-------------------------|--------------------------------------------------|
| Containerization   | **Docker + docker-compose** | Teammate environment parity, one-command start |
| Deployment (demo)  | **Railway** or **Vercel + Railway** | Free tier, fast deploy, no GPU needed  |
| Env management     | **.env files**          | API keys only                                    |

### NOT Using
| Tool               | Why Not                                                      |
|--------------------|--------------------------------------------------------------|
| Runpod / Modal     | No GPU workload. All LLM calls go to external APIs.         |
| LangChain          | Adds abstraction without value here. Direct API calls are clearer and easier to wrap with budget tracking. |
| Vector DB          | No RAG component. Not needed.                                |

---

## Project Structure

```
/
├── backend/
│   ├── main.py                  # FastAPI app, routes, WebSocket
│   ├── orchestrator.py          # Main agent loop, strategy logic
│   ├── budget_controller.py     # Global budget pool, per-agent allocations
│   ├── token_tracker.py         # LLM call wrapper, usage extraction
│   ├── roi_evaluator.py         # Quality scoring, ROI computation
│   ├── preflight.py             # Task complexity estimation
│   ├── agents/
│   │   ├── base.py              # Base agent class
│   │   ├── planner.py
│   │   ├── executor.py
│   │   └── critic.py
│   ├── models.py                # Pydantic schemas
│   ├── logger.py                # Run trace persistence
│   └── requirements.txt
│
├── frontend/
│   ├── app/
│   │   ├── page.tsx             # Main page — task input + dashboard
│   │   └── api/                 # Next.js API routes (if needed)
│   ├── components/
│   │   ├── TaskInput.tsx        # Task + budget + strategy form
│   │   ├── Dashboard.tsx        # Live token/ROI/quality dashboard
│   │   ├── AgentTrace.tsx       # Raw trace viewer per agent
│   │   ├── ComparisonView.tsx   # Side-by-side run comparison
│   │   ├── BudgetBar.tsx        # Budget remaining visualizer
│   │   └── ROIChart.tsx         # ROI per agent over time
│   ├── lib/
│   │   └── websocket.ts         # WebSocket client for live updates
│   ├── package.json
│   └── tailwind.config.ts
│
├── docker-compose.yml           # Backend + frontend in one command
├── Dockerfile.backend
├── Dockerfile.frontend
├── .env.example                 # Required API keys
├── ARCHITECTURE.md              # This file
└── README.md
```

---

## Division of Labor

### Teammate A (UI / Frontend)
- Scaffold Next.js + Shadcn
- Build TaskInput, Dashboard, BudgetBar, ROIChart, AgentTrace, ComparisonView
- Connect WebSocket for live updates
- Style the demo to be visually impressive

### Teammate B (Backend / Orchestration)
- Build FastAPI server with WebSocket
- Implement Budget Controller, Token Tracker, ROI Evaluator
- Build Planner/Executor/Critic agents with budget wrapping
- Implement Orchestrator loop with all three strategy modes
- Pre-flight check

### Integration Point
- **Contract**: Backend emits WebSocket events with this shape:

```json
{
  "event": "agent_step",
  "data": {
    "run_id": "uuid",
    "agent": "planner|executor|critic",
    "iteration": 1,
    "tokens_used": 2100,
    "tokens_remaining": 17900,
    "quality_score": 62,
    "quality_delta": 62,
    "roi": 0.0295,
    "cumulative_tokens": 2100,
    "status": "running|cutoff|complete",
    "output_preview": "First 200 chars of agent output..."
  }
}
```

- **REST endpoints**:
  - `POST /run` — submit task, budget, strategy → returns run_id
  - `GET /run/{run_id}` — get full results + traces
  - `GET /runs` — list all runs for comparison view
  - `WS /ws/{run_id}` — live event stream for a run

---

## Key Design Decisions

1. **Budget is a ceiling, not a target.** The system should return unspent tokens. Draining to zero means the early-stopping logic failed.

2. **ROI threshold is configurable.** Default 0.005 (0.5% quality improvement per token). Can be tuned per demo.

3. **Quality scoring uses self-eval.** A cheap LLM call asks "Rate this output 0-100 on completeness, clarity, actionability." Imperfect but sufficient for demonstrating the framework.

4. **Agents are stateless functions.** Each agent call is a single LLM invocation with a prompt template + context from prior steps. No persistent memory or tool use (keeps scope manageable).

5. **No LangChain.** Direct OpenAI SDK calls wrapped with token tracking give us full control and transparency. Frameworks would obscure the budget mechanics we're trying to showcase.
