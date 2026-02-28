"use client";

import { useEffect, useRef } from "react";
import type { Dag } from "@/lib/types";

interface DagGraphProps {
  dag: Dag;
}

export function DagGraph({ dag }: DagGraphProps) {
  const svgRef = useRef<SVGSVGElement>(null);

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;

    while (svg.childNodes.length > 1) {
      svg.removeChild(svg.lastChild!);
    }

    const width = svg.getBoundingClientRect().width;
    const height = 260;
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);

    const indegree: Record<number, number> = {};
    dag.nodes.forEach((n) => (indegree[n.id] = 0));
    dag.edges.forEach(
      (e) => (indegree[e.to] = (indegree[e.to] || 0) + 1)
    );

    const queue = dag.nodes
      .filter((n) => indegree[n.id] === 0)
      .map((n) => n.id);
    const depth: Record<number, number> = {};
    queue.forEach((id) => (depth[id] = 0));

    while (queue.length) {
      const cur = queue.shift()!;
      dag.edges
        .filter((e) => e.from === cur)
        .forEach((e) => {
          depth[e.to] = Math.max(depth[e.to] || 0, depth[cur] + 1);
          indegree[e.to]--;
          if (indegree[e.to] === 0) queue.push(e.to);
        });
    }

    const maxDepth = Math.max(...Object.values(depth));
    const levelBuckets: Record<number, typeof dag.nodes> = {};
    dag.nodes.forEach((n) => {
      const d = depth[n.id];
      if (!levelBuckets[d]) levelBuckets[d] = [];
      levelBuckets[d].push(n);
    });

    const r = 36;
    const padX = r + 24;
    const usableW = width - padX * 2;
    const positions: Record<number, { x: number; y: number }> = {};

    Object.keys(levelBuckets).forEach((d) => {
      const nodes = levelBuckets[Number(d)];
      const x = padX + (Number(d) / Math.max(maxDepth, 1)) * usableW;
      const gap = height / (nodes.length + 1);
      nodes.forEach((n, i) => {
        positions[n.id] = { x, y: gap * (i + 1) };
      });
    });

    const ns = "http://www.w3.org/2000/svg";

    dag.edges.forEach((e) => {
      const from = positions[e.from];
      const to = positions[e.to];
      const dx = to.x - from.x;
      const dy = to.y - from.y;
      const dist = Math.sqrt(dx * dx + dy * dy);
      const line = document.createElementNS(ns, "line");
      line.setAttribute("x1", String(from.x + (dx / dist) * r));
      line.setAttribute("y1", String(from.y + (dy / dist) * r));
      line.setAttribute("x2", String(to.x - (dx / dist) * (r + 5)));
      line.setAttribute("y2", String(to.y - (dy / dist) * (r + 5)));
      line.setAttribute("class", "stroke-muted-foreground/30");
      line.setAttribute("stroke-width", "1");
      line.setAttribute("marker-end", "url(#arrowhead)");
      svg.appendChild(line);
    });

    dag.nodes.forEach((n) => {
      const pos = positions[n.id];
      const circle = document.createElementNS(ns, "circle");
      circle.setAttribute("cx", String(pos.x));
      circle.setAttribute("cy", String(pos.y));
      circle.setAttribute("r", String(r));
      circle.setAttribute("fill", "white");
      circle.setAttribute("stroke", "#d4d4d4");
      circle.setAttribute("stroke-width", "1");
      svg.appendChild(circle);

      const text = document.createElementNS(ns, "text");
      text.setAttribute("x", String(pos.x));
      text.setAttribute("y", String(pos.y - 4));
      text.setAttribute("text-anchor", "middle");
      text.setAttribute("dominant-baseline", "central");
      text.setAttribute("fill", "#262626");
      text.setAttribute("font-family", "var(--font-geist-sans)");
      text.setAttribute("font-size", "10");
      text.setAttribute("font-weight", "600");
      text.textContent = n.label;
      svg.appendChild(text);

      const sub = document.createElementNS(ns, "text");
      sub.setAttribute("x", String(pos.x));
      sub.setAttribute("y", String(pos.y + 11));
      sub.setAttribute("text-anchor", "middle");
      sub.setAttribute("dominant-baseline", "central");
      sub.setAttribute("fill", "#a3a3a3");
      sub.setAttribute("font-family", "var(--font-geist-mono)");
      sub.setAttribute("font-size", "8");
      sub.setAttribute("letter-spacing", "0.05em");
      sub.textContent = n.complexity.toUpperCase();
      svg.appendChild(sub);
    });
  }, [dag]);

  return (
    <svg ref={svgRef} className="w-full h-[260px]">
      <defs>
        <marker
          id="arrowhead"
          markerWidth="7"
          markerHeight="5"
          refX="7"
          refY="2.5"
          orient="auto"
        >
          <polygon points="0 0, 7 2.5, 0 5" fill="#a3a3a3" />
        </marker>
      </defs>
    </svg>
  );
}
