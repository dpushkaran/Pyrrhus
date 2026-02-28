"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:5001";

export default function Home() {
  const router = useRouter();
  const [task, setTask] = useState("");
  const [budget, setBudget] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);

    try {
      const res = await fetch(`${API_URL}/api/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ task, budget: parseFloat(budget) }),
      });
      const data = await res.json();
      sessionStorage.setItem("pyrrhus_report", JSON.stringify(data));
      router.push("/report");
    } catch {
      setLoading(false);
    }
  }

  return (
    <main className="min-h-screen flex flex-col">
      <div className="border-b">
        <div className="max-w-3xl mx-auto px-6 py-3 flex items-center justify-between">
          <span className="text-xs font-semibold tracking-[.14em] uppercase text-muted-foreground">
            Pyrrhus
          </span>
          <Link
            href="/traces"
            className="text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            Trace History
          </Link>
        </div>
      </div>

      <div className="flex-1 flex items-center justify-center px-6">
        <div className="w-full max-w-lg">
          <h1 className="text-lg font-semibold tracking-tight">
            New orchestration run
          </h1>
          <p className="mt-2 text-sm text-muted-foreground leading-relaxed">
            Describe the task and set a dollar budget. The system will
            decompose it into subtasks, route each to the appropriate model
            tier, and enforce the budget ceiling.
          </p>

          <Separator className="my-6" />

          <form onSubmit={handleSubmit} className="space-y-5">
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
                rows={4}
                required
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
                  required
                  className="pl-7 font-mono"
                />
              </div>
            </div>

            <Button
              type="submit"
              className="w-full"
              disabled={loading}
            >
              {loading ? "Running\u2026" : "Run"}
            </Button>
          </form>
        </div>
      </div>
    </main>
  );
}
