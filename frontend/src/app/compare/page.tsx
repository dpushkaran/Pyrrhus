"use client";

import { Suspense, useRef, useState, useEffect } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:5001";

interface QualityScore {
  relevance: number;
  completeness: number;
  coherence: number;
  conciseness: number;
  overall: number;
  rationale: string;
}

interface TextMetrics {
  word_count: number;
  type_token_ratio: number;
  compression_ratio: number;
  ngram_repetition_rate: number;
  avg_sentence_length: number;
  filler_phrase_count: number;
}

type Phase = "input" | "streaming" | "done";

export default function ComparePage() {
  return (
    <Suspense>
      <ComparePageInner />
    </Suspense>
  );
}

function ComparePageInner() {
  const searchParams = useSearchParams();
  const [task, setTask] = useState("");
  const [budget, setBudget] = useState("0.08");
  const [mode, setMode] = useState<"capped" | "uncapped">("capped");
  const [phase, setPhase] = useState<Phase>("input");

  useEffect(() => {
    const qTask = searchParams.get("task");
    const qBudget = searchParams.get("budget");
    if (qTask) setTask(qTask);
    if (qBudget) setBudget(qBudget);
  }, [searchParams]);

  // Pyrrhus state
  const [pyrrhusOutput, setPyrrhusOutput] = useState("");
  const [pyrrhusCost, setPyrrhusCost] = useState(0);
  const [pyrrhusProgress, setPyrrhusProgress] = useState("");
  const [pyrrhusCurrentSubtask, setPyrrhusCurrentSubtask] = useState<number | null>(null);
  const [pyrrhusDone, setPyrrhusDone] = useState(false);

  // Baseline state
  const [baselineOutput, setBaselineOutput] = useState("");
  const [baselineCost, setBaselineCost] = useState(0);
  const [baselineTokens, setBaselineTokens] = useState(0);
  const [baselineDone, setBaselineDone] = useState(false);

  // Plan info
  const [totalSubtasks, setTotalSubtasks] = useState(0);
  const [subtaskList, setSubtaskList] = useState<
    { id: number; description: string; complexity: string; tier?: string; skipped?: boolean }[]
  >([]);
  const [completedSubtasks, setCompletedSubtasks] = useState<Set<number>>(new Set());

  // ROI decisions (live)
  const [roiDecisions, setRoiDecisions] = useState<
    { subtask_id: number; current_tier: string; current_quality: number; proposed_tier: string; roi: number; decision: string; reason: string }[]
  >([]);

  // Final results
  const [pyrrhusQuality, setPyrrhusQuality] = useState<QualityScore | null>(null);
  const [baselineQuality, setBaselineQuality] = useState<QualityScore | null>(null);
  const [pyrrhusMetrics, setPyrrhusMetrics] = useState<TextMetrics | null>(null);
  const [baselineMetrics, setBaselineMetrics] = useState<TextMetrics | null>(null);
  const [finalPyrrhusCost, setFinalPyrrhusCost] = useState(0);
  const [finalBaselineCost, setFinalBaselineCost] = useState(0);

  const [viewMode, setViewMode] = useState<"raw" | "preview">("preview");
  const esRef = useRef<EventSource | null>(null);

  function handleStart() {
    if (!task.trim()) return;

    setPyrrhusOutput("");
    setPyrrhusCost(0);
    setPyrrhusProgress("");
    setPyrrhusCurrentSubtask(null);
    setPyrrhusDone(false);
    setBaselineOutput("");
    setBaselineCost(0);
    setBaselineTokens(0);
    setBaselineDone(false);
    setTotalSubtasks(0);
    setPyrrhusQuality(null);
    setBaselineQuality(null);
    setPyrrhusMetrics(null);
    setBaselineMetrics(null);
    setFinalPyrrhusCost(0);
    setFinalBaselineCost(0);
    setRoiDecisions([]);
    setSubtaskList([]);
    setCompletedSubtasks(new Set());
    setPhase("streaming");

    const params = new URLSearchParams({
      task: task.trim(),
      budget: budget,
      mode: mode,
    });

    const es = new EventSource(`${API_URL}/api/compare/stream?${params}`);
    esRef.current = es;

    es.addEventListener("plan", (e) => {
      const data = JSON.parse(e.data);
      setTotalSubtasks(data.total_subtasks);
      const allocMap: Record<number, { tier: string; skipped: boolean }> = {};
      for (const a of data.allocations || []) {
        allocMap[a.subtask_id] = { tier: a.tier, skipped: a.skipped };
      }
      setSubtaskList(
        (data.subtasks || []).map((s: { id: number; description: string; complexity: string }) => ({
          id: s.id,
          description: s.description,
          complexity: s.complexity,
          tier: allocMap[s.id]?.tier,
          skipped: allocMap[s.id]?.skipped,
        }))
      );
    });

    es.addEventListener("pyrrhus_chunk", (e) => {
      const data = JSON.parse(e.data);
      setPyrrhusOutput((prev) => prev + data.delta);
      setPyrrhusCost(data.cost_so_far);
      setPyrrhusCurrentSubtask(data.subtask_id);
      setPyrrhusProgress(data.progress);
    });

    es.addEventListener("pyrrhus_subtask_done", (e) => {
      const data = JSON.parse(e.data);
      setPyrrhusCost(data.cost_so_far);
      setPyrrhusProgress(data.progress);
      setCompletedSubtasks((prev) => new Set([...prev, data.subtask_id]));
      if (!data.skipped) {
        setPyrrhusOutput((prev) => prev + "\n\n");
      }
    });

    es.addEventListener("roi_decision", (e) => {
      const data = JSON.parse(e.data);
      setRoiDecisions((prev) => [...prev, data]);
    });

    es.addEventListener("baseline_chunk", (e) => {
      const data = JSON.parse(e.data);
      setBaselineOutput((prev) => prev + data.delta);
      setBaselineCost(data.cost_so_far);
      setBaselineTokens(data.tokens_so_far);
    });

    es.addEventListener("baseline_done", (e) => {
      const data = JSON.parse(e.data);
      setBaselineCost(data.cost);
      setBaselineTokens(data.tokens);
      setBaselineDone(true);
    });

    es.addEventListener("quality", (e) => {
      const data = JSON.parse(e.data);
      if (data.pyrrhus) setPyrrhusQuality(data.pyrrhus);
      if (data.baseline) setBaselineQuality(data.baseline);
    });

    es.addEventListener("text_metrics", (e) => {
      const data = JSON.parse(e.data);
      if (data.pyrrhus) setPyrrhusMetrics(data.pyrrhus);
      if (data.baseline) setBaselineMetrics(data.baseline);
    });

    es.addEventListener("done", (e) => {
      const data = JSON.parse(e.data);
      setFinalPyrrhusCost(data.pyrrhus_cost);
      setFinalBaselineCost(data.baseline_cost);
      setPyrrhusDone(true);
      setBaselineDone(true);
      setPhase("done");
      es.close();
    });

    es.addEventListener("error", () => {
      es.close();
    });
  }

  function handleReset() {
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }
    setPhase("input");
  }

  const showResults = phase === "done" && pyrrhusQuality && baselineQuality;
  const costSavings =
    finalBaselineCost > 0
      ? ((finalBaselineCost - finalPyrrhusCost) / finalBaselineCost) * 100
      : 0;

  return (
    <main className="min-h-screen flex flex-col">
      {/* Nav */}
      <div className="border-b">
        <div className="max-w-7xl mx-auto px-6 py-3 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Link
              href="/"
              className="text-xs font-semibold tracking-[.14em] uppercase text-muted-foreground hover:text-foreground transition-colors"
            >
              Pyrrhus
            </Link>
            <span className="text-xs text-muted-foreground">/</span>
            <span className="text-xs font-semibold tracking-[.14em] uppercase text-muted-foreground">
              Compare
            </span>
          </div>
          <div className="flex items-center gap-4">
            <Link
              href="/traces"
              className="text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              Traces
            </Link>
            {phase !== "input" && (
              <button
                onClick={handleReset}
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                New Comparison
              </button>
            )}
          </div>
        </div>
      </div>

      <div className="flex-1 flex flex-col">
        {/* Input form — always visible at top when in input phase, collapsed otherwise */}
        {phase === "input" && (
          <div className="max-w-2xl mx-auto w-full px-6 py-8">
            <h1 className="text-lg font-semibold tracking-tight">
              Side-by-Side Comparison
            </h1>
            <p className="mt-2 text-sm text-muted-foreground leading-relaxed">
              Watch Pyrrhus&apos;s orchestrated pipeline race against a single
              Deep model in real time. Same task, same budget — different
              strategies.
            </p>

            <Separator className="my-6" />

            <div className="space-y-5">
              <div className="space-y-1.5">
                <label
                  htmlFor="task"
                  className="text-[10px] font-semibold uppercase tracking-[.1em] text-muted-foreground"
                >
                  Task
                </label>
                <Textarea
                  id="task"
                  value={task}
                  onChange={(e) => setTask(e.target.value)}
                  placeholder="e.g. Research and write a blog post about the best AI startups in 2025"
                  rows={3}
                  className="resize-y"
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label
                    htmlFor="budget"
                    className="text-[10px] font-semibold uppercase tracking-[.1em] text-muted-foreground"
                  >
                    Budget (USD)
                  </label>
                  <div className="relative">
                    <span className="absolute left-3 top-1/2 -translate-y-1/2 text-sm text-muted-foreground font-mono">
                      $
                    </span>
                    <Input
                      id="budget"
                      type="number"
                      step="0.01"
                      min="0.01"
                      value={budget}
                      onChange={(e) => setBudget(e.target.value)}
                      className="pl-7 font-mono"
                    />
                  </div>
                </div>

                <div className="space-y-1.5">
                  <label className="text-[10px] font-semibold uppercase tracking-[.1em] text-muted-foreground">
                    Baseline Mode
                  </label>
                  <div className="flex gap-1 p-1 bg-muted rounded-md">
                    <button
                      type="button"
                      onClick={() => setMode("capped")}
                      className={`flex-1 text-xs py-1.5 px-3 rounded transition-colors ${
                        mode === "capped"
                          ? "bg-background shadow-sm font-semibold"
                          : "text-muted-foreground hover:text-foreground"
                      }`}
                    >
                      Capped
                    </button>
                    <button
                      type="button"
                      onClick={() => setMode("uncapped")}
                      className={`flex-1 text-xs py-1.5 px-3 rounded transition-colors ${
                        mode === "uncapped"
                          ? "bg-background shadow-sm font-semibold"
                          : "text-muted-foreground hover:text-foreground"
                      }`}
                    >
                      Uncapped
                    </button>
                  </div>
                  <p className="text-[10px] text-muted-foreground">
                    {mode === "capped"
                      ? "Deep model gets same dollar budget"
                      : "Deep model runs without budget limit"}
                  </p>
                </div>
              </div>

              <Button onClick={handleStart} className="w-full" disabled={!task.trim()}>
                Compare
              </Button>
            </div>
          </div>
        )}

        {/* Streaming / results view */}
        {phase !== "input" && (
          <div className="flex-1 flex flex-col px-6 py-4 max-w-7xl mx-auto w-full">
            {/* Task context bar */}
            <div className="mb-4 flex items-center justify-between">
              <p className="text-sm text-muted-foreground truncate max-w-xl">
                {task}
              </p>
              <div className="flex items-center gap-3">
                <div className="flex gap-0.5 p-0.5 bg-muted rounded-md">
                  <button
                    type="button"
                    onClick={() => setViewMode("preview")}
                    className={`text-[10px] py-1 px-2.5 rounded transition-colors ${
                      viewMode === "preview"
                        ? "bg-background shadow-sm font-semibold"
                        : "text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    Preview
                  </button>
                  <button
                    type="button"
                    onClick={() => setViewMode("raw")}
                    className={`text-[10px] py-1 px-2.5 rounded transition-colors ${
                      viewMode === "raw"
                        ? "bg-background shadow-sm font-semibold"
                        : "text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    Raw
                  </button>
                </div>
                <Badge variant="outline" className="font-mono text-xs">
                  ${parseFloat(budget).toFixed(2)} budget
                </Badge>
                <Badge variant="secondary" className="text-xs">
                  {mode}
                </Badge>
              </div>
            </div>

            {/* Results comparison cards */}
            {showResults && (
              <div className="grid grid-cols-3 gap-3 mb-4">
                <Card>
                  <CardHeader className="pb-1">
                    <CardTitle className="text-xs text-muted-foreground font-medium uppercase tracking-wide">
                      Quality
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="flex items-baseline justify-between">
                      <div className="text-center">
                        <p className="text-2xl font-bold font-mono">
                          {pyrrhusQuality.overall.toFixed(1)}
                        </p>
                        <p className="text-[10px] text-muted-foreground">Pyrrhus</p>
                      </div>
                      <span className="text-muted-foreground text-sm">vs</span>
                      <div className="text-center">
                        <p className="text-2xl font-bold font-mono">
                          {baselineQuality.overall.toFixed(1)}
                        </p>
                        <p className="text-[10px] text-muted-foreground">Deep</p>
                      </div>
                    </div>
                  </CardContent>
                </Card>

                <Card className={costSavings > 0 ? "border-green-200 dark:border-green-900" : ""}>
                  <CardHeader className="pb-1">
                    <CardTitle className="text-xs text-muted-foreground font-medium uppercase tracking-wide">
                      Cost
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="flex items-baseline justify-between">
                      <div className="text-center">
                        <p className="text-2xl font-bold font-mono">
                          ${finalPyrrhusCost.toFixed(4)}
                        </p>
                        <p className="text-[10px] text-muted-foreground">Pyrrhus</p>
                      </div>
                      <span className="text-muted-foreground text-sm">vs</span>
                      <div className="text-center">
                        <p className="text-2xl font-bold font-mono">
                          ${finalBaselineCost.toFixed(4)}
                        </p>
                        <p className="text-[10px] text-muted-foreground">Deep</p>
                      </div>
                    </div>
                    {costSavings > 0 && (
                      <p className="text-xs text-green-600 dark:text-green-400 text-center mt-1 font-semibold">
                        {costSavings.toFixed(0)}% cheaper with Pyrrhus
                      </p>
                    )}
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader className="pb-1">
                    <CardTitle className="text-xs text-muted-foreground font-medium uppercase tracking-wide">
                      Text Analysis
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    {pyrrhusMetrics && baselineMetrics && (
                      <div className="space-y-1.5 text-xs">
                        <div className="flex justify-between">
                          <span className="text-muted-foreground">TTR</span>
                          <span className="font-mono">
                            {pyrrhusMetrics.type_token_ratio.toFixed(3)} vs{" "}
                            {baselineMetrics.type_token_ratio.toFixed(3)}
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-muted-foreground">Compress</span>
                          <span className="font-mono">
                            {pyrrhusMetrics.compression_ratio.toFixed(3)} vs{" "}
                            {baselineMetrics.compression_ratio.toFixed(3)}
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-muted-foreground">Fillers</span>
                          <span className="font-mono">
                            {pyrrhusMetrics.filler_phrase_count} vs{" "}
                            {baselineMetrics.filler_phrase_count}
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-muted-foreground">Words</span>
                          <span className="font-mono">
                            {pyrrhusMetrics.word_count} vs{" "}
                            {baselineMetrics.word_count}
                          </span>
                        </div>
                      </div>
                    )}
                  </CardContent>
                </Card>
              </div>
            )}

            {/* Two-panel streaming area */}
            <div className="flex-1 grid grid-cols-2 gap-0 border rounded-lg overflow-hidden min-h-[400px]">
              {/* Pyrrhus panel */}
              <div className="flex flex-col border-r">
                <div className="px-4 py-2.5 border-b bg-muted/30 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-semibold uppercase tracking-wide">
                      Pyrrhus Pipeline
                    </span>
                    {pyrrhusProgress && !pyrrhusDone && (
                      <Badge variant="secondary" className="text-[10px] font-mono">
                        Subtask {pyrrhusProgress}
                      </Badge>
                    )}
                    {pyrrhusDone && (
                      <Badge variant="outline" className="text-[10px] text-green-600 dark:text-green-400 border-green-300 dark:border-green-800">
                        Done
                      </Badge>
                    )}
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-xs font-mono text-muted-foreground">
                      ${pyrrhusCost.toFixed(6)}
                    </span>
                  </div>
                </div>
                {totalSubtasks > 0 && pyrrhusProgress && (
                  <div className="px-4 py-1 border-b">
                    <Progress
                      value={
                        (parseInt(pyrrhusProgress.split("/")[0]) /
                          parseInt(pyrrhusProgress.split("/")[1])) *
                        100
                      }
                      className="h-1"
                    />
                  </div>
                )}
                {subtaskList.length > 0 && (
                  <div className="px-4 py-2 border-b flex items-center gap-1.5 overflow-x-auto">
                    {subtaskList.map((s, i) => {
                      const isDone = completedSubtasks.has(s.id);
                      const isActive = pyrrhusCurrentSubtask === s.id && !isDone;
                      const isSkipped = s.skipped;

                      const tierColor =
                        s.tier === "fast"
                          ? "bg-green-500"
                          : s.tier === "deep"
                            ? "bg-red-500"
                            : s.tier === "verify"
                              ? "bg-yellow-500"
                              : "bg-muted-foreground";

                      return (
                        <div key={s.id} className="flex items-center gap-1.5">
                          {i > 0 && (
                            <div
                              className={`w-4 h-px ${
                                isDone
                                  ? "bg-foreground/30"
                                  : "bg-muted-foreground/20"
                              }`}
                            />
                          )}
                          <div
                            className={`group relative flex items-center gap-1 px-2 py-1 rounded-md border text-[10px] font-mono transition-all ${
                              isActive
                                ? "border-foreground bg-foreground/5 ring-1 ring-foreground/20"
                                : isDone
                                  ? "border-foreground/20 bg-muted/40"
                                  : isSkipped
                                    ? "border-dashed border-muted-foreground/30 text-muted-foreground/50"
                                    : "border-muted-foreground/20 text-muted-foreground"
                            }`}
                          >
                            <div
                              className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                                isActive
                                  ? `${tierColor} animate-pulse`
                                  : isDone
                                    ? tierColor
                                    : isSkipped
                                      ? "bg-muted-foreground/30"
                                      : "bg-muted-foreground/40"
                              }`}
                            />
                            <span>{s.id}</span>
                            {isDone && (
                              <svg
                                width="10"
                                height="10"
                                viewBox="0 0 24 24"
                                fill="none"
                                stroke="currentColor"
                                strokeWidth="3"
                                className="text-green-600 dark:text-green-400"
                              >
                                <polyline points="20 6 9 17 4 12" />
                              </svg>
                            )}
                            {isSkipped && (
                              <span className="text-[8px]">skip</span>
                            )}
                            <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1.5 hidden group-hover:block z-10">
                              <div className="bg-popover border rounded-md shadow-md px-2.5 py-1.5 text-[10px] max-w-[180px] whitespace-normal">
                                <p className="font-semibold">{s.tier?.toUpperCase()}</p>
                                <p className="text-muted-foreground mt-0.5 leading-snug">
                                  {s.description}
                                </p>
                              </div>
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
                {roiDecisions.length > 0 && (
                  <div className="px-4 py-2 border-b space-y-1 bg-muted/10">
                    {roiDecisions.map((d, i) => (
                      <div key={i} className="flex items-center gap-1.5 text-[10px] font-mono">
                        <span className="text-muted-foreground">#{d.subtask_id}</span>
                        <Badge variant="outline" className="text-[9px] uppercase px-1 py-0">
                          {d.current_tier}
                        </Badge>
                        <span className="text-muted-foreground">{d.current_quality.toFixed(1)}</span>
                        <span className="text-muted-foreground">&rarr;</span>
                        <Badge variant="outline" className="text-[9px] uppercase px-1 py-0">
                          {d.proposed_tier}
                        </Badge>
                        <span className="text-muted-foreground">ROI {d.roi.toFixed(0)}</span>
                        <Badge
                          variant={d.decision === "upgrade" ? "default" : "secondary"}
                          className="text-[9px] px-1 py-0"
                        >
                          {d.decision}
                        </Badge>
                      </div>
                    ))}
                  </div>
                )}
                <div className="flex-1 overflow-y-auto p-4">
                  {!pyrrhusOutput && phase === "streaming" ? (
                    <p className="text-xs text-muted-foreground italic">
                      Waiting for planner...
                    </p>
                  ) : viewMode === "raw" ? (
                    <pre className="text-xs font-mono whitespace-pre-wrap leading-relaxed">
                      {pyrrhusOutput}
                      {phase === "streaming" && !pyrrhusDone && pyrrhusOutput && (
                        <span className="inline-block w-1.5 h-3.5 bg-foreground animate-pulse ml-0.5" />
                      )}
                    </pre>
                  ) : (
                    <div className="prose-output text-sm leading-relaxed">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {pyrrhusOutput}
                      </ReactMarkdown>
                      {phase === "streaming" && !pyrrhusDone && pyrrhusOutput && (
                        <span className="inline-block w-1.5 h-3.5 bg-foreground animate-pulse ml-0.5" />
                      )}
                    </div>
                  )}
                </div>
              </div>

              {/* Baseline panel */}
              <div className="flex flex-col">
                <div className="px-4 py-2.5 border-b bg-muted/30 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-semibold uppercase tracking-wide">
                      Deep Model
                    </span>
                    <Badge variant="outline" className="text-[10px] font-mono">
                      gemini-2.5-pro
                    </Badge>
                    {baselineDone && (
                      <Badge variant="outline" className="text-[10px] text-green-600 dark:text-green-400 border-green-300 dark:border-green-800">
                        Done
                      </Badge>
                    )}
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-xs font-mono text-muted-foreground">
                      {baselineTokens.toLocaleString()} tok
                    </span>
                    <span className="text-xs font-mono text-muted-foreground">
                      ${baselineCost.toFixed(6)}
                    </span>
                  </div>
                </div>
                <div className="flex-1 overflow-y-auto p-4">
                  {!baselineOutput && phase === "streaming" ? (
                    <p className="text-xs text-muted-foreground italic">
                      Generating...
                    </p>
                  ) : viewMode === "raw" ? (
                    <pre className="text-xs font-mono whitespace-pre-wrap leading-relaxed">
                      {baselineOutput}
                      {phase === "streaming" && !baselineDone && baselineOutput && (
                        <span className="inline-block w-1.5 h-3.5 bg-foreground animate-pulse ml-0.5" />
                      )}
                    </pre>
                  ) : (
                    <div className="prose-output text-sm leading-relaxed">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {baselineOutput}
                      </ReactMarkdown>
                      {phase === "streaming" && !baselineDone && baselineOutput && (
                        <span className="inline-block w-1.5 h-3.5 bg-foreground animate-pulse ml-0.5" />
                      )}
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* Quality detail cards — shown after done */}
            {showResults && (
              <div className="grid grid-cols-2 gap-4 mt-4">
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-xs text-muted-foreground font-medium uppercase tracking-wide">
                      Pyrrhus Quality Breakdown
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="space-y-2">
                      {(
                        [
                          ["Relevance", pyrrhusQuality.relevance],
                          ["Completeness", pyrrhusQuality.completeness],
                          ["Coherence", pyrrhusQuality.coherence],
                          ["Conciseness", pyrrhusQuality.conciseness],
                        ] as [string, number][]
                      ).map(([label, val]) => (
                        <div key={label} className="space-y-0.5">
                          <div className="flex items-center justify-between">
                            <span className="text-xs text-muted-foreground">{label}</span>
                            <span className="text-xs font-mono font-semibold">
                              {val.toFixed(1)}
                            </span>
                          </div>
                          <Progress value={val * 10} className="h-1" />
                        </div>
                      ))}
                    </div>
                    {pyrrhusQuality.rationale && (
                      <p className="text-[10px] text-muted-foreground mt-2 italic">
                        &ldquo;{pyrrhusQuality.rationale}&rdquo;
                      </p>
                    )}
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-xs text-muted-foreground font-medium uppercase tracking-wide">
                      Deep Model Quality Breakdown
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="space-y-2">
                      {(
                        [
                          ["Relevance", baselineQuality.relevance],
                          ["Completeness", baselineQuality.completeness],
                          ["Coherence", baselineQuality.coherence],
                          ["Conciseness", baselineQuality.conciseness],
                        ] as [string, number][]
                      ).map(([label, val]) => (
                        <div key={label} className="space-y-0.5">
                          <div className="flex items-center justify-between">
                            <span className="text-xs text-muted-foreground">{label}</span>
                            <span className="text-xs font-mono font-semibold">
                              {val.toFixed(1)}
                            </span>
                          </div>
                          <Progress value={val * 10} className="h-1" />
                        </div>
                      ))}
                    </div>
                    {baselineQuality.rationale && (
                      <p className="text-[10px] text-muted-foreground mt-2 italic">
                        &ldquo;{baselineQuality.rationale}&rdquo;
                      </p>
                    )}
                  </CardContent>
                </Card>
              </div>
            )}
          </div>
        )}
      </div>
    </main>
  );
}
