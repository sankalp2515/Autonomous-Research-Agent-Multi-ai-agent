import { useEffect, useMemo, useRef, useState } from "react";
import { motion, useReducedMotion } from "framer-motion";
import { api } from "../api";
import type { MapData, MapNode } from "../types";
import ChatView from "./ChatView";
import { Empty, Spinner } from "./ui";
import { AddToChat } from "../chatctx";

const W = 920;
const H = 580;
type Pt = { x: number; y: number };

// Categorical cluster palette — a small, warm-paper set of muted editorial hues
// that sits inside the "Editorial Science" system. Colour here encodes a
// *sub-community of related work* (a data-viz categorical scale, not chrome).
const CLUSTER = [
  "var(--accent)", "#356b4a", "#8a5a1a", "#3d5a80", "#7a4069", "#5a6b2f",
  "#9a6a2a", "#2f6b6b", "#8c4a4a", "#4a4a7a",
];
const clusterColor = (c?: number) => CLUSTER[(c ?? 0) % CLUSTER.length];

// Fallback only: older cached maps may lack server-side x/y. New runs always
// carry precomputed positions, so this seed layout is rarely used.
function seedLayout(data: MapData): Map<string, Pt> {
  const pos = new Map<string, Pt>();
  data.nodes.forEach((n, i) => {
    const a = (i / Math.max(data.nodes.length, 1)) * Math.PI * 2;
    pos.set(n.id, { x: W / 2 + Math.cos(a) * 180, y: H / 2 + Math.sin(a) * 150 });
  });
  return pos;
}

function positions(data: MapData): Map<string, Pt> {
  const hasServer = data.nodes.every((n) => typeof n.x === "number" && typeof n.y === "number");
  if (!hasServer) return seedLayout(data);
  return new Map(data.nodes.map((n) => [n.id, { x: n.x!, y: n.y! }]));
}

export default function MapView({
  projectId,
  onCompare,
}: {
  projectId: string;
  onCompare?: (documentIds: string[]) => void;
}) {
  const [data, setData] = useState<MapData | null>(null);
  const [pos, setPos] = useState<Map<string, Pt>>(new Map());
  const [sel, setSel] = useState<string | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  const [asking, setAsking] = useState<MapNode | null>(null);
  const [why, setWhy] = useState(false);
  const reduce = useReducedMotion();
  // Multi-select for cross-paper comparison: the map is the visual entry point
  // to the Compare view — pick nodes here, compare them there.
  const [picked, setPicked] = useState<Set<string>>(new Set());

  function togglePick(id: string) {
    setPicked((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else if (n.size < 5) n.add(id);
      return n;
    });
  }

  function pickNeighbors() {
    if (!sel || !data) return;
    setPicked((s) => {
      const n = new Set(s);
      n.add(sel);
      for (const e of data.edges) {
        if (n.size >= 5) break;
        if (e.src === sel) n.add(e.dst);
        else if (e.dst === sel) n.add(e.src);
      }
      return n;
    });
  }
  const [t, setT] = useState({ tx: 0, ty: 0, k: 1 });
  const svgRef = useRef<SVGSVGElement>(null);
  const drag = useRef<{ kind: "pan" | "node"; id?: string; sx: number; sy: number; otx: number; oty: number; moved: boolean } | null>(null);

  useEffect(() => {
    setData(null); setSel(null); setT({ tx: 0, ty: 0, k: 1 });
    api.getMap(projectId).then((d) => { setData(d); setPos(positions(d)); }).catch(() => setData({ nodes: [], edges: [] }));
  }, [projectId]);

  const neighbors = useMemo(() => {
    const m = new Set<string>();
    if (sel && data) for (const e of data.edges) {
      if (e.src === sel) m.add(e.dst);
      if (e.dst === sel) m.add(e.src);
    }
    return m;
  }, [sel, data]);

  function toGraph(clientX: number, clientY: number): Pt {
    const r = svgRef.current!.getBoundingClientRect();
    const sx = ((clientX - r.left) / r.width) * W;
    const sy = ((clientY - r.top) / r.height) * H;
    return { x: (sx - t.tx) / t.k, y: (sy - t.ty) / t.k };
  }

  function onWheel(e: React.WheelEvent) {
    e.preventDefault();
    const r = svgRef.current!.getBoundingClientRect();
    const px = ((e.clientX - r.left) / r.width) * W;
    const py = ((e.clientY - r.top) / r.height) * H;
    const factor = e.deltaY < 0 ? 1.12 : 0.89;
    const nk = Math.max(0.4, Math.min(4, t.k * factor));
    setT({ k: nk, tx: px - ((px - t.tx) / t.k) * nk, ty: py - ((py - t.ty) / t.k) * nk });
  }

  function onDown(e: React.MouseEvent, id?: string) {
    if (id) e.stopPropagation();
    drag.current = { kind: id ? "node" : "pan", id, sx: e.clientX, sy: e.clientY, otx: t.tx, oty: t.ty, moved: false };
  }
  function onMove(e: React.MouseEvent) {
    const d = drag.current;
    if (!d) return;
    if (Math.abs(e.clientX - d.sx) + Math.abs(e.clientY - d.sy) > 3) d.moved = true;
    if (d.kind === "pan") {
      const r = svgRef.current!.getBoundingClientRect();
      setT((p) => ({ ...p, tx: d.otx + ((e.clientX - d.sx) / r.width) * W, ty: d.oty + ((e.clientY - d.sy) / r.height) * H }));
    } else if (d.id) {
      const g = toGraph(e.clientX, e.clientY);
      setPos((m) => new Map(m).set(d.id!, g));
    }
  }
  function onUp() {
    const d = drag.current;
    // Click (not drag) on a node selects it — separates "reposition" from "select".
    if (d?.kind === "node" && d.id && !d.moved) setSel(d.id);
    drag.current = null;
  }

  async function reload(refresh: boolean) {
    setData(null); setSel(null); setT({ tx: 0, ty: 0, k: 1 });
    try {
      const d = await api.getMap(projectId, refresh);
      setData(d); setPos(positions(d));
    } catch {
      setData({ nodes: [], edges: [] });
    }
  }

  if (!data) return <p><Spinner /> opening map…</p>;
  if (data.nodes.length < 2)
    return (
      <Empty glyph="◬" title="Not enough papers to map yet">
        The map connects the <strong>papers</strong> in your corpus by similarity.
        Run deep research or add a few papers, then come back to explore.
      </Empty>
    );

  const selNode = data.nodes.find((n) => n.id === sel) || null;
  const r = (n: MapNode) => 6 + Math.min(Math.log1p(n.citations) * 2.2, 12);
  const tf = `translate(${t.tx} ${t.ty}) scale(${t.k})`;
  const clusterCount = data.clusters ?? 0;

  return (
    <div>
      <div style={{ display: "flex", alignItems: "flex-start", marginBottom: 12 }}>
        <div>
          <span className="overline">Discovery map · papers only</span>
          <p style={{ margin: "4px 0 0", color: "var(--ink-3)", fontSize: 13.5, maxWidth: 640, lineHeight: 1.55 }}>
            Every paper in this project’s corpus, positioned by content similarity and
            coloured by <strong>sub-community</strong>. Use it to see how the literature
            clusters, spot the bridges between groups, find outliers — then compare or
            interrogate any paper without leaving the view.{" "}
            <button className="map-why-toggle" onClick={() => setWhy((v) => !v)}>
              {why ? "Hide" : "Why this view?"}
            </button>
          </p>
        </div>
        <span style={{ flex: 1 }} />
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn btn-ghost" style={{ fontSize: 12 }}
                  onClick={() => { setPos(positions(data)); setT({ tx: 0, ty: 0, k: 1 }); }}>
            ⟲ Reset view
          </button>
          <button className="btn btn-ghost" style={{ fontSize: 12 }} onClick={() => reload(true)}>
            ↻ Rebuild
          </button>
        </div>
      </div>

      {why && (
        <motion.div className="map-why"
          initial={reduce ? false : { opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: "auto" }}
          transition={{ duration: 0.2, ease: "easeOut" }}>
          <p><strong>What problem it solves.</strong> A verified report answers your question,
            but it doesn’t show you the <em>shape</em> of the evidence. The map does: which
            papers form a tight school of thought, which one paper connects two otherwise
            separate clusters (often the most cited / most pivotal), and which papers sit
            alone — candidate gaps or fringe ideas worth a closer read.</p>
          <p><strong>How to use it.</strong> Clusters (colour) = related work. Dot size =
            citation weight. Click a paper to highlight what it’s closest to, then{" "}
            <em>Add to compare</em> to run a side-by-side, or <em>Ask this paper</em> to chat
            with its full text. It’s the fastest way to go from “here’s a report” to “here’s
            the landscape, and here’s where to dig next.”</p>
        </motion.div>
      )}

      <div className="map-legend">
        <span><span className="leg-line dashed" /> similar content</span>
        <span><span className="leg-line solid" /> cites</span>
        <span><span className="leg-dot" /> dot size = citations</span>
        {clusterCount > 1 && <span className="mono" style={{ color: "var(--ink-3)" }}>{clusterCount} sub-communities</span>}
      </div>

      <div className="map-wrap">
        <svg ref={svgRef} className="map-svg" viewBox={`0 0 ${W} ${H}`} role="img"
             onWheel={onWheel} onMouseDown={(e) => onDown(e)} onMouseMove={onMove}
             onMouseUp={onUp} onMouseLeave={onUp}
             style={{ cursor: drag.current?.kind === "pan" ? "grabbing" : "grab" }}>
          <g transform={tf}>
            {data.edges.map((e, i) => {
              const a = pos.get(e.src), b = pos.get(e.dst);
              if (!a || !b) return null;
              const active = sel && (e.src === sel || e.dst === sel);
              const cite = e.kind === "cites";
              return (
                <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                      stroke={active ? "var(--accent)" : cite ? "var(--ink-3)" : "var(--line-2)"}
                      strokeWidth={(active ? 1.8 : cite ? 1.2 : 0.7) / t.k}
                      strokeDasharray={cite ? undefined : `${3 / t.k} ${3 / t.k}`}
                      opacity={sel ? (active ? 0.95 : 0.08) : cite ? 0.55 : 0.32} />
              );
            })}
            {data.nodes.map((n, i) => {
              const p = pos.get(n.id)!;
              const dim = sel && n.id !== sel && !neighbors.has(n.id);
              const isSel = n.id === sel;
              const showLabel = isSel || neighbors.has(n.id) || hover === n.id || data.nodes.length <= 16;
              const col = clusterColor(n.cluster);
              return (
                <motion.g key={n.id} style={{ cursor: "pointer" }}
                   initial={reduce ? false : { opacity: 0, scale: 0.5 }}
                   animate={{ opacity: dim ? 0.26 : 1, scale: 1 }}
                   transition={reduce ? { duration: 0 } : { delay: Math.min(i * 0.012, 0.6), duration: 0.35, ease: "easeOut" }}
                   onMouseDown={(e) => onDown(e as unknown as React.MouseEvent, n.id)}
                   onMouseEnter={() => setHover(n.id)} onMouseLeave={() => setHover(null)}>
                  {picked.has(n.id) && (
                    <circle cx={p.x} cy={p.y} r={r(n) + 4 / t.k} fill="none"
                            stroke="var(--accent)" strokeWidth={2 / t.k} />
                  )}
                  <circle cx={p.x} cy={p.y} r={r(n)}
                          fill={col}
                          fillOpacity={isSel ? 1 : neighbors.has(n.id) ? 0.9 : 0.72}
                          stroke={isSel ? "var(--ink)" : "var(--surface)"}
                          strokeWidth={(isSel ? 2 : 1.5) / t.k} />
                  {showLabel && (
                    <text x={p.x} y={p.y - r(n) - 4 / t.k} textAnchor="middle"
                          style={{ font: `${10 / t.k}px "Hanken Grotesk"`, fill: "var(--ink-2)", pointerEvents: "none" }}>
                      {n.title.length > 28 ? n.title.slice(0, 26) + "…" : n.title}
                    </text>
                  )}
                </motion.g>
              );
            })}
          </g>
        </svg>

        {selNode && (
          <motion.aside className="map-panel"
            initial={reduce ? false : { opacity: 0, x: 12 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.18, ease: "easeOut" }}>
            <button className="map-panel-x" onClick={() => setSel(null)}>×</button>
            <span className="overline" style={{ color: clusterColor(selNode.cluster) }}>
              {selNode.source_type}{typeof selNode.cluster === "number" ? ` · cluster ${selNode.cluster + 1}` : ""}
            </span>
            <h3>{selNode.title}</h3>
            <p className="map-panel-meta">
              {selNode.authors?.slice(0, 3).join(", ")}
              {selNode.year ? ` · ${selNode.year}` : ""}
              {selNode.citations ? ` · cited ${selNode.citations}×` : ""}
            </p>
            <p className="map-panel-near">{neighbors.size} closely-related paper{neighbors.size === 1 ? "" : "s"} highlighted</p>
            <div className="map-panel-actions">
              <AddToChat item={{ kind: "document", id: selNode.id, label: `paper · ${selNode.title}` }} />
              <button className={`btn ${picked.has(selNode.id) ? "" : "btn-ghost"}`} style={{ fontSize: 12.5 }}
                      onClick={() => togglePick(selNode.id)}>
                {picked.has(selNode.id) ? "✓ In comparison" : "⊞ Add to compare"}
              </button>
              {neighbors.size > 0 && (
                <button className="btn btn-ghost" style={{ fontSize: 12.5 }} onClick={pickNeighbors}>
                  ✦ Add neighbours
                </button>
              )}
              {!selNode.abstract_only && (
                <button className="btn btn-ghost" style={{ fontSize: 12.5 }} onClick={() => setAsking(selNode)}>Ask this paper</button>
              )}
              {selNode.url && (
                <a className="btn btn-ghost" style={{ fontSize: 12.5 }} href={selNode.url} target="_blank" rel="noreferrer">Open ↗</a>
              )}
            </div>
          </motion.aside>
        )}
      </div>

      {picked.size > 0 && (
        <motion.div className="map-tray"
          initial={reduce ? false : { opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.18, ease: "easeOut" }}>
          <span className="map-tray-count mono">{picked.size} selected</span>
          <span className="map-tray-hint">for comparison</span>
          <span style={{ flex: 1 }} />
          <button className="btn btn-ghost" style={{ fontSize: 12 }} onClick={() => setPicked(new Set())}>
            Clear
          </button>
          <button className="btn" style={{ fontSize: 12 }}
                  disabled={picked.size < 2 || !onCompare}
                  onClick={() => onCompare?.([...picked])}>
            ⊞ Compare {picked.size} papers →
          </button>
        </motion.div>
      )}

      {asking && (
        <>
          <div className="drawer-veil" onClick={() => setAsking(null)} />
          <aside className="drawer" role="dialog" aria-label="Ask this paper">
            <div className="drawer-head">
              <div>
                <span className="overline">Ask this paper</span>
                <h3>{asking.title}</h3>
              </div>
              <button className="drawer-close" onClick={() => setAsking(null)}>×</button>
            </div>
            <div className="drawer-body">
              <ChatView projectId={projectId} documentId={asking.id} documentKind={asking.source_type} />
            </div>
          </aside>
        </>
      )}
    </div>
  );
}
