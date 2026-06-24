import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { GraphData } from "../types";
import { Empty, Spinner } from "./ui";

const TYPE_COLOR: Record<string, string> = {
  paper: "#1c6a52",
  repo: "#5b4a8a",
  blog: "#9a6b14",
};

export default function GraphView({ projectId }: { projectId: string }) {
  const [graph, setGraph] = useState<GraphData | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.getGraph(projectId).then(setGraph).catch((e) => setError(String(e.message ?? e)));
  }, [projectId]);

  const layout = useMemo(() => {
    if (!graph) return null;
    const columns: Record<string, { id: string; label: string; type: string }[]> = {};
    for (const node of graph.nodes) {
      (columns[node.type] ||= []).push(node);
    }
    const types = Object.keys(columns).sort();
    const width = 920;
    const colWidth = width / Math.max(types.length, 1);
    const pos: Record<string, { x: number; y: number }> = {};
    let maxRows = 1;
    types.forEach((type, ci) => {
      columns[type].forEach((node, ri) => {
        pos[node.id] = { x: colWidth * ci + colWidth / 2, y: 70 + ri * 54 };
        maxRows = Math.max(maxRows, ri + 1);
      });
    });
    return { types, columns, pos, width, height: 90 + maxRows * 54 };
  }, [graph]);

  if (error) return <p style={{ color: "var(--failed)" }}>{error}</p>;
  if (!graph) return <p><Spinner /> loading graph…</p>;
  if (!graph.nodes.length)
    return (
      <Empty glyph="◬" title="No graph yet">
        Cross-source edges (papers ↔ repos ↔ blogs) are persisted after each
        deep research run.
      </Empty>
    );

  return (
    <svg
      className="graph-svg"
      viewBox={`0 0 ${layout!.width} ${layout!.height}`}
      role="img"
      aria-label="Cross-source knowledge graph"
    >
      {graph.edges.map((edge, i) => {
        const a = layout!.pos[edge.src];
        const b = layout!.pos[edge.dst];
        if (!a || !b) return null;
        return (
          <line
            key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y}
            stroke="#c9c0ae" strokeWidth={0.8} opacity={0.6}
          />
        );
      })}
      {layout!.types.map((type, ci) => (
        <text
          key={type}
          x={(layout!.width / layout!.types.length) * ci + layout!.width / layout!.types.length / 2}
          y={30}
          textAnchor="middle"
          style={{ font: "10.5px JetBrains Mono", letterSpacing: "0.16em", fill: "#837b6e", textTransform: "uppercase" as const }}
        >
          {type.toUpperCase()}
        </text>
      ))}
      {graph.nodes.map((node) => {
        const p = layout!.pos[node.id];
        if (!p) return null;
        const color = TYPE_COLOR[node.type] ?? "#4b453c";
        return (
          <g key={node.id}>
            <circle cx={p.x} cy={p.y} r={7} fill={color} opacity={0.92} />
            <text
              x={p.x} y={p.y + 22} textAnchor="middle"
              style={{ font: "11px Inter", fill: "#4b453c" }}
            >
              {node.label.slice(0, 34)}{node.label.length > 34 ? "…" : ""}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
