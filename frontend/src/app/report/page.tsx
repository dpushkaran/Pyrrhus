"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";
import { DagGraph } from "@/components/dag-graph";
import type { CostReport } from "@/lib/types";

function dollars(n: number) {
  return `$${n.toFixed(4)}`;
}

function pct(n: number) {
  return `${n.toFixed(1)}%`;
}

function num(n: number) {
  return n.toLocaleString();
}

function SectionHeading({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-[10px] font-semibold uppercase tracking-[.12em] text-muted-foreground mb-3">
      {children}
    </h2>
  );
}

export default function ReportPage() {
  const router = useRouter();
  const [report, setReport] = useState<CostReport | null>(null);

  useEffect(() => {
    const raw = sessionStorage.getItem("pyrrhus_report");
    if (!raw) {
      router.replace("/");
      return;
    }
    setReport(JSON.parse(raw));
  }, [router]);

  if (!report) return null;

  const { budget_summary: budget, subtask_metrics: subtasks, tier_distribution: tiers, downgrade_report: downgrades, efficiency_stats: efficiency, task_graph_summary: graphSummary, dag } = report;

  const hasDowngrades =
    downgrades &&
    (downgrades.downgrades.length > 0 ||
      downgrades.subtasks_skipped.length > 0);

  return (
    <main className="min-h-screen">
      {/* Top bar */}
      <div className="border-b">
        <div className="max-w-5xl mx-auto px-6 py-3 flex items-center justify-between">
          <span className="text-xs font-semibold tracking-[.14em] uppercase text-muted-foreground">
            Pyrrhus &mdash; Orchestration Report
          </span>
          <span className="text-xs font-mono text-muted-foreground">
            {new Date().toISOString().slice(0, 16).replace("T", " ")} UTC
          </span>
        </div>
      </div>

      <div className="max-w-5xl mx-auto px-6 py-8 space-y-10">
        {/* Task context */}
        {report.task_input && (
          <div>
            <SectionHeading>Task</SectionHeading>
            <p className="text-sm leading-relaxed">{report.task_input}</p>
          </div>
        )}

        {/* 1. Budget Summary */}
        <section>
          <SectionHeading>Budget Summary</SectionHeading>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <Card>
              <CardHeader className="pb-0">
                <CardTitle className="text-xs text-muted-foreground font-medium uppercase tracking-wide">
                  Budget
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-2xl font-bold font-mono tracking-tight">
                  {dollars(budget.dollar_budget)}
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-0">
                <CardTitle className="text-xs text-muted-foreground font-medium uppercase tracking-wide">
                  Spent
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-2xl font-bold font-mono tracking-tight">
                  {dollars(budget.dollar_spent)}
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-0">
                <CardTitle className="text-xs text-muted-foreground font-medium uppercase tracking-wide">
                  Remaining
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-2xl font-bold font-mono tracking-tight">
                  {dollars(budget.dollar_remaining)}
                </p>
                <p className="text-xs text-muted-foreground mt-1">
                  returned to caller
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-0">
                <CardTitle className="text-xs text-muted-foreground font-medium uppercase tracking-wide">
                  Utilization
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-2xl font-bold font-mono tracking-tight">
                  {Math.round(budget.budget_utilization * 100)}%
                </p>
                <Progress
                  value={budget.budget_utilization * 100}
                  className="mt-2 h-1.5"
                />
              </CardContent>
            </Card>
          </div>
        </section>

        {/* 2. Per-Subtask Breakdown */}
        <section>
          <SectionHeading>Per-Subtask Breakdown</SectionHeading>
          <div className="border rounded-lg overflow-hidden">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-12">#</TableHead>
                  <TableHead>Subtask</TableHead>
                  <TableHead>Tier</TableHead>
                  <TableHead className="text-right">Budgeted</TableHead>
                  <TableHead className="text-right">Consumed</TableHead>
                  <TableHead className="text-right">Cost</TableHead>
                  <TableHead className="text-right">Surplus</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {subtasks.map((s) => (
                  <TableRow key={s.subtask_id}>
                    <TableCell className="font-mono text-muted-foreground">
                      {s.subtask_id}
                    </TableCell>
                    <TableCell className="font-medium">
                      {s.name}
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline" className="font-mono text-xs uppercase">
                        {s.tier}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right font-mono">
                      {num(s.tokens_budgeted)}
                    </TableCell>
                    <TableCell className="text-right font-mono">
                      {num(s.tokens_consumed)}
                    </TableCell>
                    <TableCell className="text-right font-mono">
                      {dollars(s.cost_dollars)}
                    </TableCell>
                    <TableCell className="text-right font-mono text-muted-foreground">
                      +{num(s.surplus_returned)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </section>

        {/* 3 & 5. Tier Distribution + Efficiency */}
        <section>
          <div className="grid md:grid-cols-2 gap-6">
            <div>
              <SectionHeading>Tier Distribution</SectionHeading>
              <Card>
                <CardContent className="space-y-4 pt-6">
                  {tiers.map((t) => (
                    <div key={t.tier} className="space-y-1.5">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-mono uppercase text-muted-foreground">
                          {t.tier}
                        </span>
                        <span className="text-xs font-mono text-muted-foreground">
                          {t.count} &middot; {Math.round(t.percentage)}%
                        </span>
                      </div>
                      <Progress value={t.percentage} className="h-1" />
                    </div>
                  ))}
                </CardContent>
              </Card>
            </div>
            <div>
              <SectionHeading>Efficiency Stats</SectionHeading>
              <Card>
                <CardContent className="pt-6">
                  <dl className="space-y-3">
                    {[
                      ["Tokens budgeted", num(efficiency.total_tokens_budgeted)],
                      ["Tokens consumed", num(efficiency.total_tokens_consumed)],
                      ["Surplus generated", num(efficiency.total_surplus_generated)],
                      ["Token efficiency", pct(efficiency.token_efficiency)],
                    ].map(([label, value]) => (
                      <div
                        key={label}
                        className="flex items-center justify-between border-b last:border-0 pb-2 last:pb-0"
                      >
                        <dt className="text-sm text-muted-foreground">
                          {label}
                        </dt>
                        <dd className="text-sm font-semibold font-mono">
                          {value}
                        </dd>
                      </div>
                    ))}
                  </dl>
                </CardContent>
              </Card>
            </div>
          </div>
        </section>

        {/* 4. Downgrade Report */}
        <section>
          <SectionHeading>Downgrade Report</SectionHeading>
          <Card>
            <CardContent className="pt-6">
              {hasDowngrades ? (
                <div className="space-y-3">
                  <div className="flex justify-between border-b pb-2">
                    <span className="text-sm text-muted-foreground">
                      Original plan cost
                    </span>
                    <span className="text-sm font-semibold font-mono">
                      {dollars(downgrades!.original_plan_cost)}
                    </span>
                  </div>
                  <div className="flex justify-between border-b pb-2">
                    <span className="text-sm text-muted-foreground">
                      Final plan cost
                    </span>
                    <span className="text-sm font-semibold font-mono">
                      {dollars(downgrades!.final_plan_cost)}
                    </span>
                  </div>
                  {downgrades!.downgrades.map((d) => (
                    <div
                      key={d.subtask_id}
                      className="flex items-center gap-2 text-sm"
                    >
                      <span>{d.name}</span>
                      <Badge variant="outline" className="font-mono text-xs uppercase">
                        {d.original_tier}
                      </Badge>
                      <span className="text-muted-foreground">&rarr;</span>
                      <Badge variant="outline" className="font-mono text-xs uppercase">
                        {d.final_tier}
                      </Badge>
                    </div>
                  ))}
                  {downgrades!.subtasks_skipped.map((sk) => (
                    <div
                      key={sk}
                      className="flex items-center gap-2 text-sm"
                    >
                      <span>{sk}</span>
                      <span className="text-muted-foreground font-mono">
                        skipped
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-muted-foreground text-center py-4">
                  No downgrades applied &mdash; budget was sufficient for
                  the full execution plan.
                </p>
              )}
            </CardContent>
          </Card>
        </section>

        {/* 6. Task Graph Summary + DAG */}
        <section>
          <SectionHeading>Task Graph</SectionHeading>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
            <Card>
              <CardContent className="pt-6 text-center">
                <p className="text-xl font-bold font-mono">
                  {graphSummary.total_subtasks}
                </p>
                <p className="text-[10px] uppercase tracking-[.08em] text-muted-foreground mt-1">
                  Subtasks
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6 text-center">
                <p className="text-xl font-bold font-mono">
                  {graphSummary.max_depth}
                </p>
                <p className="text-[10px] uppercase tracking-[.08em] text-muted-foreground mt-1">
                  Max Depth
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6 text-center">
                <p className="text-xl font-bold font-mono">
                  {graphSummary.parallelizable_subtasks}
                </p>
                <p className="text-[10px] uppercase tracking-[.08em] text-muted-foreground mt-1">
                  Parallelizable
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6 text-center">
                <div className="flex gap-1.5 justify-center flex-wrap">
                  {Object.entries(
                    graphSummary.complexity_distribution
                  ).map(([level, cnt]) => (
                    <Badge
                      key={level}
                      variant="outline"
                      className="font-mono text-xs"
                    >
                      {level} {cnt}
                    </Badge>
                  ))}
                </div>
                <p className="text-[10px] uppercase tracking-[.08em] text-muted-foreground mt-2">
                  Complexity
                </p>
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardContent className="pt-6">
              <DagGraph dag={dag} />
            </CardContent>
          </Card>
        </section>

        <Separator />
        <footer className="text-right text-[10px] uppercase tracking-[.1em] text-muted-foreground pb-8">
          Pyrrhus Orchestration Report
        </footer>
      </div>
    </main>
  );
}
