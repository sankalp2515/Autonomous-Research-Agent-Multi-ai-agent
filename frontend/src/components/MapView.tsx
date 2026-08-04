import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import type { MapData, MapNode } from "../types";
import ChatView from "./ChatView";
import { Empty, Spinner } from "./ui";

const W = 920;
const H = 580;
type Pt = { x: number; y: number };

function layout(data: MapData): Map<string, Pt> {
  const { nodes, edges } = data;
  const pos = new Map<string, Pt>();
  nodes.forEach((n, i) => {
    const a = (i / Math.max(nodes.length, 1)) * Math.PI * 2;
    pos.set(n.id, { x: W / 2 + Math.cos(a) * 180 + (i % 7), y: H / 2 + Math.sin(a) * 150 + (i % 5) });
  });
  if (nodes.length < 2) return pos;
  const k = Math.sqrt((W * H) / nodes.length) * 0.55;
  for (let it = 0; it < 260; it++) {
    const disp = new Map(nodes.map((n) => [n.id, { x: 0, y: 0 }]));
    for (let a = 0; a < nodes.length; a++)
      for (let b = a + 1; b < nodes.length; b++) {
        const pa = pos.get(nodes[a].id)!, pb = pos.get(nodes[b].id)!;
        const dx = pa.x - pb.x, dy = pa.y - pb.y, d = Math.hypot(dx, dy) || 0.01;
        const f = (k * k) / d, ux = dx / d, uy = dy / d;
        const da = disp.get(nodes[a].id)!, db = disp.get(nodes[b].id)!;
        da.x += ux * f; da.y += uy * f; db.x -= ux * f; db.y -= uy * f;
      }
    for (const e of edges) {
      const pa = pos.get(e.src), pb = pos.get(e.dst);
      if (!pa || !pb) continue;
      const dx = pa.x - pb.x, dy = pa.y - pb.y, d = Math.hypot(dx, dy) || 0.01;
      const f = ((d * d) / k) * (0.4 + e.weight), ux = dx / d, uy = dy / d;
      const da = disp.get(e.src)!, db = disp.get(e.dst)!;
      da.x -= ux * f; da.y -= uy * f; db.x += ux * f; db.y += uy * f;
    }
    const temp = (1 - it / 260) * (W / 12);
    for (const n of nodes) {
      const dp = disp.get(n.id)!, p = pos.get(n.id)!;
      const dl = Math.hypot(dp.x, dp.y) || 0.01;
      p.x = Math.max(28, Math.min(W - 28, p.x + (dp.x / dl) * Math.min(dl, temp)));
      p.y = Math.max(28, Math.min(H - 28, p.y + (dp.y / dl) * Math.min(dl, temp)));
    }
  }
  return pos;
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
  const drag = useRef<{ kind: "pan" | "node"; id?: string; sx: number; sy: number; otx: number; oty: number } | null>(null);

  useEffect(() => {
    setData(null); setSel(null); setT({ tx: 0, ty: 0, k: 1 });
    api.getMap(projectId).then((d) => { setData(d); setPos(layout(d)); }).catch(() => setData({ nodes: [], edges: [] }));
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
    if (id) { e.stopPropagation(); setSel(id); }
    drag.current = { kind: id ? "node" : "pan", id, sx: e.clientX, sy: e.clientY, otx: t.tx, oty: t.ty };
  }
  function onMove(e: React.MouseEvent) {
    const d = drag.current;
    if (!d) return;
    if (d.kind === "pan") {
      const r = svgRef.current!.getBoundingClientRect();
      setT((p) => ({ ...p, tx: d.otx + ((e.clientX - d.sx) / r.width) * W, ty: d.oty + ((e.clientY - d.sy) / r.height) * H }));
    } else if (d.id) {
      const g = toGraph(e.clientX, e.clientY);
      setPos((m) => new Map(m).set(d.id!, g));
    }
  }
  function onUp() { drag.current = null; }

  async function reload(refresh: boolean) {
    setData(null); setSel(null); setT({ tx: 0, ty: 0, k: 1 });
    try {
      const d = await api.getMap(projectId, refresh);
      setData(d); setPos(layout(d));
    } catch {
      setData({ nodes: [], edges: [] });
    }
  }

  if (!data) return <p><Spinner /> building map…</p>;
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

  return (
    <div>
      <div style={{ display: "flex", alignItems: "flex-start", marginBottom: 12 }}>
        <div>
          <span className="overline">Discovery map · papers only</span>
          <p style={{ margin: "4px 0 0", color: "var(--text-2)", fontSize: 13.5, maxWidth: 600, lineHeight: 1.55 }}>
            Papers connected by content similarity. Drag to pan, scroll to zoom,
            drag a node to reposition, click a paper to highlight its neighbours and act on it.
          </p>
        </div>
        <span style={{ flex: 1 }} />
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn btn-ghost" style={{ fontSize: 12 }}
                  onClick={() => { setPos(layout(data)); setT({ tx: 0, ty: 0, k: 1 }); }}>
            ⟲ Reset view
          </button>
          <button className="btn btn-ghost" style={{ fontSize: 12 }} onClick={() => reload(true)}>
            ↻ Rebuild
          </button>
        </div>
      </div>

      <div className="map-legend">
        <span><span className="leg-line solid" /> cites</span>
        <span><span className="leg-line dashed" /> similar</span>
        <span><span className="leg-dot" /> dot size = citations</span>
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
                      stroke={active ? "var(--primary)" : cite ? "var(--text-3)" : "var(--line-2)"}
                      strokeWidth={(active ? 1.8 : cite ? 1.2 : 0.7) / t.k}
                      strokeDasharray={cite ? undefined : `${3 / t.k} ${3 / t.k}`}
                      opacity={sel ? (active ? 0.95 : 0.1) : cite ? 0.6 : 0.4} />
              );
            })}
            {data.nodes.map((n) => {
              const p = pos.get(n.id)!;
              const dim = sel && n.id !== sel && !neighbors.has(n.id);
              const isSel = n.id === sel;
              const showLabel = isSel || neighbors.has(n.id) || hover === n.id || data.nodes.length <= 16;
              return (
                <g key={n.id} style={{ cursor: "pointer", opacity: dim ? 0.28 : 1 }}
                   onMouseDown={(e) => onDown(e, n.id)}
                   onMouseEnter={() => setHover(n.id)} onMouseLeave={() => setHover(null)}>
                  {picked.has(n.id) && (
                    <circle cx={p.x} cy={p.y} r={r(n) + 4 / t.k} fill="none"
                            stroke="var(--primary)" strokeWidth={2 / t.k} />
                  )}
                  <circle cx={p.x} cy={p.y} r={r(n)}
                          fill={isSel ? "var(--primary)" : neighbors.has(n.id) ? "var(--primary-deep)" : "var(--text-2)"}
                          stroke="#fff" strokeWidth={1.5 / t.k} />
                  {showLabel && (
                    <text x={p.x} y={p.y - r(n) - 4 / t.k} textAnchor="middle"
                          style={{ font: `${10 / t.k}px Inter`, fill: "var(--text-2)", pointerEvents: "none" }}>
                      {n.title.length > 28 ? n.title.slice(0, 26) + "…" : n.title}
                    </text>
                  )}
                </g>
              );
            })}
          </g>
        </svg>

        {selNode && (
          <aside className="map-panel">
            <button className="map-panel-x" onClick={() => setSel(null)}>×</button>
            <span className="overline">{selNode.source_type}</span>
            <h3>{selNode.title}</h3>
            <p className="map-panel-meta">
              {selNode.authors?.slice(0, 3).join(", ")}
              {selNode.year ? ` · ${selNode.year}` : ""}
              {selNode.citations ? ` · cited ${selNode.citations}×` : ""}
            </p>
            <p className="map-panel-near">{neighbors.size} closely-related paper{neighbors.size === 1 ? "" : "s"} highlighted</p>
            <div className="map-panel-actions">
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
          </aside>
        )}
      </div>

      {picked.size > 0 && (
        <div className="map-tray">
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
        </div>
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
