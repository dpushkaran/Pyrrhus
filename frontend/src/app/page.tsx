"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import {
  Card,
  CardContent,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

function StatCard({
  label,
  value,
  sub,
  accent,
}: {
  label: string;
  value: string;
  sub?: string;
  accent?: boolean;
}) {
  return (
    <Card className={accent ? "border-green-200 dark:border-green-900" : ""}>
      <CardContent className="pt-5 pb-4 text-center">
        <p
          className={`text-2xl font-bold font-mono tracking-tight ${
            accent
              ? "text-green-700 dark:text-green-400"
              : ""
          }`}
        >
          {value}
        </p>
        <p className="text-[10px] uppercase tracking-[.08em] text-muted-foreground mt-1">
          {label}
        </p>
        {sub && (
          <p
            className={`text-[10px] mt-0.5 ${
              accent
                ? "text-green-600/80 dark:text-green-500/80"
                : "text-muted-foreground"
            }`}
          >
            {sub}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

export default function Home() {
  const router = useRouter();
  const [task, setTask] = useState("");
  const [budget, setBudget] = useState("");

  function handleCompare() {
    if (!task.trim()) return;
    const params = new URLSearchParams({
      task: task.trim(),
      ...(budget ? { budget } : {}),
    });
    router.push(`/compare?${params}`);
  }

  return (
    <main className="min-h-screen flex flex-col">
      {/* Nav */}
      <div className="border-b">
        <div className="max-w-5xl mx-auto px-6 py-3 flex items-center justify-between">
          <span className="text-xs font-semibold tracking-[.14em] uppercase text-muted-foreground">
            Pyrrhus
          </span>
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
              Traces
            </Link>
          </div>
        </div>
      </div>

      <div className="flex-1 flex flex-col">
        {/* Hero */}
        <section className="py-16 px-6">
          <div className="max-w-3xl mx-auto text-center">
            <Badge variant="secondary" className="mb-4 text-xs font-mono">
              Budget-Aware AI Orchestration
            </Badge>
            <h1 className="text-3xl sm:text-4xl font-bold tracking-tight leading-tight">
              Same quality.
              <br />
              <span className="text-green-700 dark:text-green-400">
                Fraction of the cost.
              </span>
            </h1>
            <p className="mt-4 text-sm sm:text-base text-muted-foreground max-w-lg mx-auto leading-relaxed">
              Pyrrhus decomposes complex tasks into subtasks, routes each to the
              cheapest model that can handle it, and enforces a hard dollar
              budget — so you never overspend on reasoning.
            </p>
          </div>
        </section>

        {/* How it works — compact pipeline viz */}
        <section className="px-6 pb-10">
          <div className="max-w-3xl mx-auto">
            <div className="flex items-center justify-center gap-2 sm:gap-3 text-xs">
              <div className="flex flex-col items-center gap-1">
                <div className="w-20 sm:w-24 border rounded-md px-2 py-2 text-center bg-muted/30">
                  <p className="font-semibold text-[10px] uppercase tracking-wide">
                    Planner
                  </p>
                  <p className="text-[9px] text-muted-foreground mt-0.5">
                    Decompose task
                  </p>
                </div>
              </div>
              <span className="text-muted-foreground">&#8594;</span>
              <div className="flex flex-col items-center gap-1">
                <div className="w-20 sm:w-24 border rounded-md px-2 py-2 text-center bg-muted/30">
                  <p className="font-semibold text-[10px] uppercase tracking-wide">
                    Allocator
                  </p>
                  <p className="text-[9px] text-muted-foreground mt-0.5">
                    Assign tiers
                  </p>
                </div>
              </div>
              <span className="text-muted-foreground">&#8594;</span>
              <div className="flex flex-col items-center gap-1">
                <div className="w-20 sm:w-24 border rounded-md px-2 py-2 text-center bg-muted/30">
                  <p className="font-semibold text-[10px] uppercase tracking-wide">
                    Executor
                  </p>
                  <p className="text-[9px] text-muted-foreground mt-0.5">
                    Run &amp; track
                  </p>
                </div>
              </div>
              <span className="text-muted-foreground">&#8594;</span>
              <div className="flex flex-col items-center gap-1">
                <div className="w-20 sm:w-24 border rounded-md px-2 py-2 text-center bg-muted/30">
                  <p className="font-semibold text-[10px] uppercase tracking-wide">
                    Evaluator
                  </p>
                  <p className="text-[9px] text-muted-foreground mt-0.5">
                    Score quality
                  </p>
                </div>
              </div>
            </div>

            {/* Tier badges */}
            <div className="flex justify-center gap-4 mt-5">
              <div className="flex items-center gap-1.5">
                <div className="w-2 h-2 rounded-full bg-green-500" />
                <span className="text-[10px] text-muted-foreground font-mono">
                  Fast — $0.40/1M
                </span>
              </div>
              <div className="flex items-center gap-1.5">
                <div className="w-2 h-2 rounded-full bg-yellow-500" />
                <span className="text-[10px] text-muted-foreground font-mono">
                  Verify — $0.60/1M
                </span>
              </div>
              <div className="flex items-center gap-1.5">
                <div className="w-2 h-2 rounded-full bg-red-500" />
                <span className="text-[10px] text-muted-foreground font-mono">
                  Deep — $10.00/1M
                </span>
              </div>
            </div>
          </div>
        </section>

        {/* Sample comparison result */}
        <section className="px-6 pb-10">
          <div className="max-w-3xl mx-auto">
            <p className="text-[10px] font-semibold uppercase tracking-[.12em] text-muted-foreground mb-3 text-center">
              Example: &ldquo;Create a go-to-market plan for a student SaaS&rdquo;
            </p>
            <div className="grid grid-cols-3 gap-3">
              <Card>
                <CardContent className="pt-5 pb-4 text-center">
                  <div className="flex items-baseline justify-center gap-3">
                    <div>
                      <p className="text-xl font-bold font-mono">7.2</p>
                      <p className="text-[9px] text-muted-foreground">Pyrrhus</p>
                    </div>
                    <span className="text-muted-foreground text-xs">vs</span>
                    <div>
                      <p className="text-xl font-bold font-mono">7.5</p>
                      <p className="text-[9px] text-muted-foreground">Deep</p>
                    </div>
                  </div>
                  <p className="text-[10px] uppercase tracking-[.08em] text-muted-foreground mt-2">
                    Quality
                  </p>
                </CardContent>
              </Card>
              <StatCard
                label="Cost Savings"
                value="63%"
                sub="$0.003 vs $0.008"
                accent
              />
              <Card>
                <CardContent className="pt-5 pb-4 text-center">
                  <p className="text-xl font-bold font-mono">3</p>
                  <p className="text-[10px] uppercase tracking-[.08em] text-muted-foreground mt-1">
                    Subtasks Routed
                  </p>
                  <div className="flex justify-center gap-1 mt-2">
                    <Badge variant="outline" className="text-[9px] font-mono px-1.5">
                      2 fast
                    </Badge>
                    <Badge variant="outline" className="text-[9px] font-mono px-1.5">
                      1 deep
                    </Badge>
                  </div>
                </CardContent>
              </Card>
            </div>
          </div>
        </section>

        <Separator className="max-w-3xl mx-auto w-full" />

        {/* Task form */}
        <section className="px-6 py-10">
          <div className="max-w-lg mx-auto">
            <h2 className="text-lg font-semibold tracking-tight text-center">
              Try it yourself
            </h2>
            <p className="mt-2 text-sm text-muted-foreground text-center leading-relaxed">
              Enter a task and budget. Pyrrhus will decompose, route, execute,
              and show you exactly where every token went.
            </p>

            <div className="mt-6 space-y-5">
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
                  placeholder="e.g. Analyze 3 competitor products, draft positioning, and write launch copy for 2 audiences"
                  rows={3}
                  className="resize-y"
                />
              </div>

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
                    placeholder="0.08"
                    className="pl-7 font-mono"
                  />
                </div>
              </div>

              <Button
                onClick={handleCompare}
                className="w-full"
                disabled={!task.trim()}
              >
                Run Comparison
              </Button>
            </div>
          </div>
        </section>

        {/* Footer */}
        <div className="mt-auto border-t">
          <div className="max-w-5xl mx-auto px-6 py-4 flex items-center justify-between">
            <span className="text-[10px] uppercase tracking-[.1em] text-muted-foreground">
              Pyrrhus &mdash; Budget-Aware AI Orchestration
            </span>
            <div className="flex items-center gap-4">
              <Link
                href="/compare"
                className="text-[10px] text-muted-foreground hover:text-foreground transition-colors"
              >
                Compare
              </Link>
              <Link
                href="/traces"
                className="text-[10px] text-muted-foreground hover:text-foreground transition-colors"
              >
                Trace History
              </Link>
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}
