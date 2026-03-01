"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import {
  LivePipelineGraph,
  type SubtaskNode,
  type CompletedInfo,
  type RoiDecision,
} from "@/components/live-pipeline-graph";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:5001";

const STAGES = [
  {
    id: "planner",
    title: "1. Planner",
    model: "gemini-2.5-flash",
    description:
      "Decomposes the user\u2019s task into a DAG of subtasks with complexity ratings and dependency edges. Simple tasks get 1 subtask. Complex tasks get 3\u20135.",
    detail: "The planner is budget-unaware \u2014 it decomposes based purely on what the task requires.",
  },
  {
    id: "allocator",
    title: "2. Allocator",
    model: "No LLM (pure logic)",
    description:
      "Maps each subtask to a model tier based on complexity, then enforces the dollar budget through a downgrade waterfall.",
    detail: "Low \u2192 Fast ($0.40/1M) \u00b7 Medium \u2192 Verify ($0.60/1M) \u00b7 High \u2192 Deep ($10/1M). If over budget: downgrade tiers, then scale tokens, then skip subtasks.",
  },
  {
    id: "executor",
    title: "3. Executor",
    model: "Per-subtask routing",
    description:
      "Walks the DAG in topological order, dispatches each subtask to its assigned model, and tracks actual token usage and cost.",
    detail: "Surplus tokens from efficient subtasks are redistributed to downstream subtasks that need more capacity.",
  },
  {
    id: "evaluator",
    title: "4. Evaluator",
    model: "gemini-2.5-flash-lite",
    description:
      "Scores the final output on relevance, completeness, coherence, and conciseness (0\u201310 each). Cost tracked separately from task budget.",
    detail: "LLM-as-judge approach using structured output for reliable scoring.",
  },
];

const TIERS = [
  {
    name: "Fast",
    model: "gemini-2.5-flash-lite",
    input: "$0.10/1M",
    output: "$0.40/1M",
    maxTokens: "1,024",
    color: "bg-green-500",
    use: "Simple retrieval, formatting, lookups",
  },
  {
    name: "Verify",
    model: "gemini-2.5-flash",
    input: "$0.15/1M",
    output: "$0.60/1M",
    maxTokens: "2,048",
    color: "bg-yellow-500",
    use: "Synthesis, quality checks, summarization",
  },
  {
    name: "Deep",
    model: "gemini-2.5-pro",
    input: "$1.25/1M",
    output: "$10.00/1M",
    maxTokens: "4,096",
    color: "bg-red-500",
    use: "Creative writing, analysis, long-form reasoning",
  },
];

function StageCard({
  stage,
  isActive,
  onClick,
}: {
  stage: (typeof STAGES)[0];
  isActive: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`text-left w-full rounded-lg border p-4 transition-all ${
        isActive
          ? "border-foreground/30 bg-muted/40 ring-1 ring-foreground/10"
          : "border-border hover:border-foreground/20 hover:bg-muted/20"
      }`}
    >
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-sm font-semibold">{stage.title}</span>
        <Badge variant="outline" className="text-[9px] font-mono">
          {stage.model}
        </Badge>
      </div>
      <p className="text-xs text-muted-foreground leading-relaxed">
        {stage.description}
      </p>
      {isActive && (
        <p className="text-xs text-foreground/70 mt-2 leading-relaxed border-t pt-2">
          {stage.detail}
        </p>
      )}
    </button>
  );
}

export default function HowItWorksPage() {
  const [activeStage, setActiveStage] = useState("planner");

  // Live graph state
  const [vizTask, setVizTask] = useState("");
  const [vizBudget, setVizBudget] = useState("0.08");
  const [vizRunning, setVizRunning] = useState(false);
  const [vizDone, setVizDone] = useState(false);
  const [vizFinalQuality, setVizFinalQuality] = useState<number | null>(null);
  const [subtasks, setSubtasks] = useState<SubtaskNode[]>([]);
  const [activeSubtaskId, setActiveSubtaskId] = useState<number | null>(null);
  const [completedSubtasks, setCompletedSubtasks] = useState<Map<number, CompletedInfo>>(new Map());
  const [skippedIds, setSkippedIds] = useState<Set<number>>(new Set());
  const [roiDecisions, setRoiDecisions] = useState<RoiDecision[]>([]);
  const [vizCost, setVizCost] = useState(0);
  const [vizEventLog, setVizEventLog] = useState<string[]>([]);
  const esRef = useRef<EventSource | null>(null);

  function startVisualization() {
    if (!vizTask.trim()) return;

    setSubtasks([]);
    setActiveSubtaskId(null);
    setCompletedSubtasks(new Map());
    setSkippedIds(new Set());
    setRoiDecisions([]);
    setVizCost(0);
    setVizEventLog([]);
    setVizRunning(true);
    setVizDone(false);
    setVizFinalQuality(null);

    const params = new URLSearchParams({
      task: vizTask.trim(),
      budget: vizBudget,
      mode: "capped",
    });

    const es = new EventSource(`${API_URL}/api/compare/stream?${params}`);
    esRef.current = es;

    es.addEventListener("plan", (e) => {
      const data = JSON.parse(e.data);
      setSubtasks(data.subtasks || []);
      setVizEventLog((prev) => [
        ...prev,
        `Planner decomposed into ${data.total_subtasks} subtasks ($${data.planner_cost?.toFixed(6) ?? "?"})`,
      ]);
    });

    es.addEventListener("pyrrhus_chunk", (e) => {
      const data = JSON.parse(e.data);
      setActiveSubtaskId(data.subtask_id);
      setVizCost(data.cost_so_far);
    });

    es.addEventListener("roi_decision", (e) => {
      const data = JSON.parse(e.data);
      setRoiDecisions((prev) => [...prev, data]);
      setVizEventLog((prev) => [
        ...prev,
        `#${data.subtask_id} ${data.current_tier} → ${data.proposed_tier}: ROI ${data.roi.toFixed(0)} — ${data.decision}`,
      ]);
    });

    es.addEventListener("pyrrhus_subtask_done", (e) => {
      const data = JSON.parse(e.data);
      setVizCost(data.cost_so_far);
      if (data.skipped) {
        setSkippedIds((prev) => new Set([...prev, data.subtask_id]));
        setVizEventLog((prev) => [...prev, `#${data.subtask_id} skipped`]);
      } else {
        setCompletedSubtasks((prev) => {
          const next = new Map(prev);
          next.set(data.subtask_id, {
            tier: data.tier,
            quality: data.quality ?? 0,
          });
          return next;
        });
        setVizEventLog((prev) => [
          ...prev,
          `#${data.subtask_id} done — ${data.tier} tier, quality ${data.quality?.toFixed(1) ?? "?"}, $${data.cost?.toFixed(6) ?? "?"}`,
        ]);
      }
      setActiveSubtaskId(null);
    });

    es.addEventListener("done", (e) => {
      const data = JSON.parse(e.data);
      setVizCost(data.pyrrhus_cost);
      setVizFinalQuality(data.pyrrhus_quality ?? null);
      setVizRunning(false);
      setVizDone(true);
      setVizEventLog((prev) => [
        ...prev,
        `Done — total cost $${data.pyrrhus_cost?.toFixed(6) ?? "?"}, quality ${data.pyrrhus_quality?.toFixed(1) ?? "?"}`,
      ]);
      es.close();
    });

    es.addEventListener("error", () => {
      setVizRunning(false);
      es.close();
    });
  }

  function resetVisualization() {
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }
    setSubtasks([]);
    setVizRunning(false);
    setVizDone(false);
    setVizEventLog([]);
  }

  return (
    <main className="min-h-screen">
      {/* Nav */}
      <div className="border-b">
        <div className="max-w-5xl mx-auto px-6 py-3 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Link
              href="/"
              className="text-xs font-semibold tracking-[.14em] uppercase text-muted-foreground hover:text-foreground transition-colors"
            >
              Pyrrhus
            </Link>
            <span className="text-xs text-muted-foreground">/</span>
            <span className="text-xs font-semibold tracking-[.14em] uppercase text-muted-foreground">
              How It Works
            </span>
          </div>
          <div className="flex items-center gap-4">
            <Link
              href="/compare"
              className="text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              Compare
            </Link>
            <Link
              href="/traces"
              className="text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              Analysis
            </Link>
          </div>
        </div>
      </div>

      <div className="max-w-5xl mx-auto px-6 py-10 space-y-12">
        {/* Hero */}
        <section className="text-center max-w-2xl mx-auto">
          <h1 className="text-2xl font-bold tracking-tight">
            How Pyrrhus Works
          </h1>
          <p className="text-sm text-muted-foreground mt-3 leading-relaxed">
            Pyrrhus treats tokens like money. It decomposes tasks, routes each
            piece to the cheapest model that can handle it, and enforces a hard
            dollar ceiling &mdash; so you get maximum quality per token spent.
          </p>
        </section>

        {/* Pipeline flow */}
        <section>
          <h2 className="text-[10px] font-semibold uppercase tracking-[.12em] text-muted-foreground mb-4">
            The Pipeline
          </h2>

          {/* Visual pipeline arrow */}
          <div className="flex items-center justify-center gap-2 mb-6">
            {STAGES.map((stage, i) => (
              <div key={stage.id} className="flex items-center gap-2">
                <button
                  onClick={() => setActiveStage(stage.id)}
                  className={`px-3 py-2 rounded-md border text-xs font-semibold transition-all ${
                    activeStage === stage.id
                      ? "border-foreground/30 bg-muted/50"
                      : "border-border text-muted-foreground hover:border-foreground/20"
                  }`}
                >
                  {stage.title}
                </button>
                {i < STAGES.length - 1 && (
                  <span className="text-muted-foreground/40 text-lg">&rarr;</span>
                )}
              </div>
            ))}
          </div>

          {/* Detail cards */}
          <div className="grid md:grid-cols-2 gap-3">
            {STAGES.map((stage) => (
              <StageCard
                key={stage.id}
                stage={stage}
                isActive={activeStage === stage.id}
                onClick={() => setActiveStage(stage.id)}
              />
            ))}
          </div>
        </section>

        <Separator />

        {/* Model Tiers */}
        <section>
          <h2 className="text-[10px] font-semibold uppercase tracking-[.12em] text-muted-foreground mb-4">
            Model Tiers
          </h2>
          <p className="text-xs text-muted-foreground mb-4">
            The allocator routes each subtask to the cheapest tier that matches
            its complexity. The price difference between Fast and Deep is{" "}
            <strong>25x</strong> &mdash; that&apos;s where the savings come
            from.
          </p>
          <div className="grid md:grid-cols-3 gap-3">
            {TIERS.map((tier) => (
              <Card key={tier.name}>
                <CardHeader className="pb-2">
                  <CardTitle className="flex items-center gap-2">
                    <div className={`w-2.5 h-2.5 rounded-full ${tier.color}`} />
                    <span className="text-sm font-semibold">{tier.name}</span>
                    <Badge variant="outline" className="text-[9px] font-mono ml-auto">
                      {tier.model}
                    </Badge>
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <dl className="space-y-1.5 text-xs">
                    <div className="flex justify-between">
                      <dt className="text-muted-foreground">Input</dt>
                      <dd className="font-mono font-semibold">{tier.input}</dd>
                    </div>
                    <div className="flex justify-between">
                      <dt className="text-muted-foreground">Output</dt>
                      <dd className="font-mono font-semibold">{tier.output}</dd>
                    </div>
                    <div className="flex justify-between">
                      <dt className="text-muted-foreground">Max tokens</dt>
                      <dd className="font-mono">{tier.maxTokens}</dd>
                    </div>
                  </dl>
                  <p className="text-[10px] text-muted-foreground mt-2 border-t pt-2">
                    {tier.use}
                  </p>
                </CardContent>
              </Card>
            ))}
          </div>
        </section>

        <Separator />

        {/* Live Pipeline Visualization */}
        <section>
          <h2 className="text-[10px] font-semibold uppercase tracking-[.12em] text-muted-foreground mb-4">
            Live Pipeline Visualization
          </h2>
          <p className="text-xs text-muted-foreground mb-4">
            Enter a task to watch Pyrrhus decompose, allocate, and execute in
            real time. Nodes light up as subtasks are processed, colored by
            their assigned tier.
          </p>

          {/* Compact input form */}
          <div className="flex gap-3 mb-4">
            <Textarea
              value={vizTask}
              onChange={(e) => setVizTask(e.target.value)}
              placeholder="e.g. Compare 3 cloud providers and recommend one for a startup"
              rows={1}
              className="resize-none flex-1 text-sm"
              disabled={vizRunning}
            />
            <div className="relative w-24 shrink-0">
              <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-xs text-muted-foreground font-mono">
                $
              </span>
              <Input
                type="number"
                step="0.01"
                min="0.01"
                value={vizBudget}
                onChange={(e) => setVizBudget(e.target.value)}
                className="pl-6 font-mono text-sm h-full"
                disabled={vizRunning}
              />
            </div>
            {!vizRunning && !vizDone ? (
              <Button
                onClick={startVisualization}
                disabled={!vizTask.trim()}
                className="shrink-0"
              >
                Visualize
              </Button>
            ) : vizDone ? (
              <Button
                onClick={resetVisualization}
                variant="outline"
                className="shrink-0"
              >
                Reset
              </Button>
            ) : (
              <Button disabled className="shrink-0">
                Running...
              </Button>
            )}
          </div>

          {/* Graph + event log side by side */}
          {subtasks.length > 0 && (
            <div className="grid md:grid-cols-3 gap-4">
              {/* Graph — takes 2/3 */}
              <Card className="md:col-span-2">
                <CardContent className="pt-6 pb-4">
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-3">
                      <div className="flex items-center gap-1.5">
                        <div className="w-2 h-2 rounded-full bg-[#dbeafe] border border-[#3b82f6]" />
                        <span className="text-[9px] text-muted-foreground">Active</span>
                      </div>
                      <div className="flex items-center gap-1.5">
                        <div className="w-2 h-2 rounded-full bg-green-500" />
                        <span className="text-[9px] text-muted-foreground">Fast</span>
                      </div>
                      <div className="flex items-center gap-1.5">
                        <div className="w-2 h-2 rounded-full bg-yellow-500" />
                        <span className="text-[9px] text-muted-foreground">Verify</span>
                      </div>
                      <div className="flex items-center gap-1.5">
                        <div className="w-2 h-2 rounded-full bg-red-500" />
                        <span className="text-[9px] text-muted-foreground">Deep</span>
                      </div>
                    </div>
                    <span className="text-xs font-mono text-muted-foreground">
                      ${vizCost.toFixed(6)}
                    </span>
                  </div>
                  <LivePipelineGraph
                    subtasks={subtasks}
                    activeSubtaskId={activeSubtaskId}
                    completedSubtasks={completedSubtasks}
                    roiDecisions={roiDecisions}
                    skippedIds={skippedIds}
                    finalQuality={vizFinalQuality}
                  />
                </CardContent>
              </Card>

              {/* Event log — takes 1/3 */}
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-xs text-muted-foreground font-medium uppercase tracking-wide">
                    Event Log
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="space-y-1.5 max-h-[350px] overflow-y-auto">
                    {vizEventLog.length === 0 ? (
                      <p className="text-xs text-muted-foreground italic">
                        Waiting for events...
                      </p>
                    ) : (
                      vizEventLog.map((entry, i) => (
                        <div
                          key={i}
                          className="text-[10px] font-mono text-muted-foreground leading-snug border-l-2 border-muted pl-2"
                        >
                          {entry}
                        </div>
                      ))
                    )}
                    {vizRunning && (
                      <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground">
                        <span className="inline-block w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />
                        Processing...
                      </div>
                    )}
                  </div>
                </CardContent>
              </Card>
            </div>
          )}
        </section>

        <Separator />

        {/* Budget enforcement */}
        <section>
          <h2 className="text-[10px] font-semibold uppercase tracking-[.12em] text-muted-foreground mb-4">
            Budget Enforcement
          </h2>
          <div className="grid md:grid-cols-2 gap-4">
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Downgrade Waterfall</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-xs text-muted-foreground mb-3">
                  When the initial allocation exceeds the budget, the allocator
                  applies downgrades in priority order:
                </p>
                <ol className="space-y-2 text-xs">
                  {[
                    "Deep \u2192 Verify (least critical subtasks first)",
                    "Deep \u2192 Fast (if still over budget)",
                    "Skip least-critical Verify subtasks",
                    "Scale all max_tokens proportionally (min 128)",
                  ].map((step, i) => (
                    <li key={i} className="flex items-start gap-2">
                      <span className="shrink-0 w-4 h-4 rounded-full bg-muted flex items-center justify-center text-[9px] font-mono font-semibold">
                        {i + 1}
                      </span>
                      <span className="text-muted-foreground">{step}</span>
                    </li>
                  ))}
                </ol>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Surplus Redistribution</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-xs text-muted-foreground mb-3">
                  When a subtask finishes under its token budget, the unused
                  tokens are returned to a surplus pool and redistributed to
                  downstream subtasks.
                </p>
                <div className="bg-muted/30 rounded-md p-3 font-mono text-[10px] leading-relaxed">
                  <p className="text-muted-foreground">Subtask 1: budgeted 1024, used 412</p>
                  <p className="text-green-700 dark:text-green-400">
                    &rarr; surplus +612 tokens returned to pool
                  </p>
                  <p className="text-muted-foreground mt-1">Subtask 3: budgeted 1024</p>
                  <p className="text-green-700 dark:text-green-400">
                    &rarr; boosted to 1636 from surplus pool
                  </p>
                </div>
              </CardContent>
            </Card>
          </div>
        </section>

        <Separator />

        {/* CTA */}
        <section className="text-center py-4">
          <p className="text-sm text-muted-foreground mb-4">
            See it in action &mdash; watch Pyrrhus race against a single Deep
            model in real time.
          </p>
          <Link
            href="/compare"
            className="inline-flex items-center justify-center px-6 py-2.5 rounded-md bg-foreground text-background text-sm font-semibold hover:bg-foreground/90 transition-colors"
          >
            Try Side-by-Side Comparison
          </Link>
        </section>

        <footer className="text-right text-[10px] uppercase tracking-[.1em] text-muted-foreground pb-8">
          Pyrrhus &mdash; Budget-Aware AI Orchestration
        </footer>
      </div>
    </main>
  );
}
