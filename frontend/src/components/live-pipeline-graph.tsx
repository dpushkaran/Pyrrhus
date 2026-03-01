"use client";

import { useMemo } from "react";

export interface SubtaskNode {
  id: number;
  description: string;
  complexity: string;
  dependencies: number[];
}

export interface CompletedInfo {
  tier: string;
  quality: number;
}

export interface RoiDecision {
  subtask_id: number;
  current_tier: string;
  proposed_tier: string;
  roi: number;
  decision: string;
}

interface Props {
  subtasks: SubtaskNode[];
  activeSubtaskId: number | null;
  completedSubtasks: Map<number, CompletedInfo>;
  roiDecisions: RoiDecision[];
  skippedIds?: Set<number>;
  finalQuality?: number | null;
}

const R = 26;
const AGENT_R = 30;

function tierColor(tier: string): string {
  switch (tier) {
    case "fast": return "#22c55e";
    case "verify": return "#eab308";
    case "deep": return "#ef4444";
    default: return "#a3a3a3";
  }
}

export function LivePipelineGraph({
  subtasks,
  activeSubtaskId,
  completedSubtasks,
  roiDecisions,
  skippedIds = new Set(),
  finalQuality,
}: Props) {
  const allAgentsDone = subtasks.length > 0 && subtasks.every(
    (s) => completedSubtasks.has(s.id) || skippedIds.has(s.id)
  );

  const roiBySubtask = useMemo(() => {
    const map = new Map<number, RoiDecision>();
    roiDecisions.forEach((d) => map.set(d.subtask_id, d));
    return map;
  }, [roiDecisions]);

  if (!subtasks.length) {
    return (
      <div className="flex items-center justify-center h-[260px] text-sm text-muted-foreground">
        Enter a task and click Visualize to see the pipeline graph
      </div>
    );
  }

  const agentCount = subtasks.length;
  const totalWidth = Math.max(400, agentCount * 140 + 80);
  const height = 340;
  const cx = totalWidth / 2;

  // Fixed positions
  const orchestratorPos = { x: cx, y: 50 };
  const outputPos = { x: cx, y: height - 50 };
  const agentPositions = subtasks.map((_, i) => ({
    x: (totalWidth - (agentCount - 1) * 130) / 2 + i * 130,
    y: height / 2,
  }));

  return (
    <svg
      width="100%"
      viewBox={`0 0 ${totalWidth} ${height}`}
      className="overflow-visible"
    >
      <defs>
        <marker id="pg-arrow" markerWidth="7" markerHeight="5" refX="7" refY="2.5" orient="auto">
          <polygon points="0 0, 7 2.5, 0 5" fill="#d4d4d4" />
        </marker>
        <marker id="pg-arrow-done" markerWidth="7" markerHeight="5" refX="7" refY="2.5" orient="auto">
          <polygon points="0 0, 7 2.5, 0 5" fill="#a3a3a3" />
        </marker>
      </defs>

      {/* Edges: Orchestrator → each agent */}
      {agentPositions.map((ap, i) => {
        const dx = ap.x - orchestratorPos.x;
        const dy = ap.y - orchestratorPos.y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        const nx = dx / dist;
        const ny = dy / dist;
        const x1 = orchestratorPos.x + nx * R;
        const y1 = orchestratorPos.y + ny * R;
        const x2 = ap.x - nx * (AGENT_R + 5);
        const y2 = ap.y - ny * (AGENT_R + 5);
        const done = completedSubtasks.has(subtasks[i].id);

        const roi = roiBySubtask.get(subtasks[i].id);
        const midX = (x1 + x2) / 2;
        const midY = (y1 + y2) / 2;

        return (
          <g key={`edge-orch-${i}`}>
            <line
              x1={x1} y1={y1} x2={x2} y2={y2}
              stroke={done ? "#a3a3a3" : "#e5e5e5"}
              strokeWidth={1.5}
              markerEnd={done ? "url(#pg-arrow-done)" : "url(#pg-arrow)"}
            />
            {roi && (
              <text
                x={midX + 8} y={midY - 2}
                fontSize="8" fontFamily="var(--font-geist-mono)"
                fill={roi.decision === "upgrade" ? "#22c55e" : "#a3a3a3"}
              >
                ROI {roi.roi.toFixed(0)}{roi.decision === "upgrade" ? " ↑" : ""}
              </text>
            )}
          </g>
        );
      })}

      {/* Edges: each agent → Output */}
      {agentPositions.map((ap, i) => {
        const dx = outputPos.x - ap.x;
        const dy = outputPos.y - ap.y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        const nx = dx / dist;
        const ny = dy / dist;
        const x1 = ap.x + nx * AGENT_R;
        const y1 = ap.y + ny * AGENT_R;
        const x2 = outputPos.x - nx * (R + 5);
        const y2 = outputPos.y - ny * (R + 5);
        const done = completedSubtasks.has(subtasks[i].id);

        return (
          <line
            key={`edge-agent-out-${i}`}
            x1={x1} y1={y1} x2={x2} y2={y2}
            stroke={done ? "#a3a3a3" : "#e5e5e5"}
            strokeWidth={1.5}
            markerEnd={done ? "url(#pg-arrow-done)" : "url(#pg-arrow)"}
          />
        );
      })}

      {/* Orchestrator node */}
      <circle cx={orchestratorPos.x} cy={orchestratorPos.y} r={R}
        fill="#f5f5f5" stroke="#d4d4d4" strokeWidth={1.5} />
      <text x={orchestratorPos.x} y={orchestratorPos.y - 1}
        textAnchor="middle" dominantBaseline="central"
        fontSize="8" fontWeight="600" fontFamily="var(--font-geist-mono)"
        letterSpacing="0.06em" fill="#525252">
        ORCH
      </text>
      <text x={orchestratorPos.x} y={orchestratorPos.y + R + 14}
        textAnchor="middle" dominantBaseline="central"
        fontSize="9" fontFamily="var(--font-geist-sans)" fill="#a3a3a3">
        Orchestrator
      </text>

      {/* Agent nodes */}
      {subtasks.map((s, i) => {
        const pos = agentPositions[i];
        const isActive = activeSubtaskId === s.id;
        const completed = completedSubtasks.get(s.id);
        const isSkipped = skippedIds.has(s.id);

        let fillColor = "#fafafa";
        let strokeColor = "#d4d4d4";
        let strokeWidth = 1.5;

        if (completed) {
          strokeColor = tierColor(completed.tier);
          strokeWidth = 2;
        } else if (isSkipped) {
          strokeColor = "#e5e5e5";
        }

        const shortLabel = s.description.split(" ").slice(0, 2).join(" ");

        return (
          <g key={s.id}>
            {/* Subtle blue ring for active node */}
            {isActive && (
              <circle
                cx={pos.x} cy={pos.y} r={AGENT_R + 5}
                fill="none" stroke="#93c5fd" strokeWidth={2} opacity={0.6}
              />
            )}

            {/* Tier-colored ring for completed */}
            {completed && (
              <circle
                cx={pos.x} cy={pos.y} r={AGENT_R + 4}
                fill="none" stroke={tierColor(completed.tier)}
                strokeWidth={2} opacity={0.25}
              />
            )}

            {/* Main circle */}
            <circle
              cx={pos.x} cy={pos.y} r={AGENT_R}
              fill={fillColor} stroke={strokeColor} strokeWidth={strokeWidth}
              strokeDasharray={isSkipped ? "4 3" : "none"}
            />

            {/* Agent label inside */}
            <text x={pos.x} y={pos.y - 1}
              textAnchor="middle" dominantBaseline="central"
              fontSize="9" fontWeight="600" fontFamily="var(--font-geist-mono)"
              fill={completed ? "#262626" : isActive ? "#1d4ed8" : "#737373"}>
              #{s.id}
            </text>

            {/* Tier badge below circle */}
            {completed && (
              <text x={pos.x} y={pos.y + AGENT_R + 12}
                textAnchor="middle" dominantBaseline="central"
                fontSize="8" fontFamily="var(--font-geist-mono)"
                letterSpacing="0.06em" fill={tierColor(completed.tier)}>
                {completed.tier.toUpperCase()}
              </text>
            )}

            {/* Description label */}
            <text x={pos.x} y={pos.y + AGENT_R + (completed ? 24 : 14)}
              textAnchor="middle" dominantBaseline="central"
              fontSize="8" fontFamily="var(--font-geist-sans)" fill="#a3a3a3">
              {shortLabel}{s.description.split(" ").length > 2 ? "…" : ""}
            </text>
          </g>
        );
      })}

      {/* Output node */}
      <circle cx={outputPos.x} cy={outputPos.y} r={R}
        fill={allAgentsDone ? "#f0fdf4" : "#fafafa"}
        stroke={allAgentsDone ? "#22c55e" : "#e5e5e5"}
        strokeWidth={allAgentsDone ? 2 : 1.5}
      />
      {finalQuality != null && allAgentsDone ? (
        <text x={outputPos.x} y={outputPos.y - 1}
          textAnchor="middle" dominantBaseline="central"
          fontSize="12" fontWeight="700" fontFamily="var(--font-geist-mono)"
          fill="#15803d">
          {finalQuality.toFixed(1)}
        </text>
      ) : (
        <text x={outputPos.x} y={outputPos.y - 1}
          textAnchor="middle" dominantBaseline="central"
          fontSize="8" fontWeight="600" fontFamily="var(--font-geist-mono)"
          letterSpacing="0.06em" fill="#a3a3a3">
          OUT
        </text>
      )}
      <text x={outputPos.x} y={outputPos.y + R + 14}
        textAnchor="middle" dominantBaseline="central"
        fontSize="9" fontFamily="var(--font-geist-sans)" fill="#a3a3a3">
        {allAgentsDone ? "Deliverable" : "Output"}
      </text>
    </svg>
  );
}
