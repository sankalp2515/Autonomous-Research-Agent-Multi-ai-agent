// Glass skin only: the reference design's right-hand column and bottom action
// dock, built from numbers the report ALREADY carries. Nothing here is
// computed fresh or estimated, and there is deliberately no 0-1 "evidence
// quality" score: evidence strength in Veriscope is a study count, and a
// single blended number would claim a precision nothing measured (CLAUDE.md).
// Rendered by ReportView only when the glass skin is on (src/skin.ts).
import { createPortal } from "react-dom";
import type { Report } from "../types";
import { Icon } from "./icons";

export type DockTarget = "chat" | "compare" | "map" | "monitor" | "documents";

function n(v: number | null | undefined): number {
  return typeof v === "number" && Number.isFinite(v) ? v : 0;
}

export function ReportAside({
  report, onNavigate, onMethod,
}: {
  report: Report;
  onNavigate?: (to: DockTarget) => void;
  onMethod: () => void;
}) {
  const c = report.confidence;
  const f = (c.funnel ?? {}) as Record<string, any>;
  const ladder = (f.ladder ?? {}) as Record<string, number>;
  const included = n(ladder.included_in_synthesis ?? ladder.extracted ?? f.extracted_studies);
  const screened = n(ladder.screened ?? f.screened);
  const excluded = Math.max(0, screened - included);
  const share = screened ? Math.max(2, Math.round((included / screened) * 100)) : 0;
  const comp = (c as any).composition ?? {};
  const verified = n(comp.verified ?? f.claims_verified);
  const derived = n(comp.derived);
  const refused = n(f.claims_refused);
  const grounded = n(c.sections_verified);
  const total = n(c.sections_total);
  const refs = [...(report.references ?? [])]
    .sort((a, b) => n(b.year) - n(a.year))
    .slice(0, 3);
  const open = report.sections.filter((s) => s.status !== "verified").slice(0, 3);

  return (
    <aside className="ga">
      <section className="ga-card">
        <h3 className="ga-h">Research corpus</h3>
        <div className="ga-split">
          <span><i className="ga-dot ok" /> <b>{included}</b> included</span>
          <span><i className="ga-dot bad" /> <b>{excluded}</b> excluded</span>
        </div>
        <div className="ga-bar" role="img" aria-label={`${included} of ${screened} screened papers included`}>
          <span style={{ width: `${share}%` }} />
        </div>
        <div className="ga-row">
          <span className="ga-muted"><b>{screened}</b> screened</span>
          <button className="ga-link" onClick={onMethod}>View screening</button>
        </div>
      </section>

      <section className="ga-card">
        <h3 className="ga-h">What this report is made of</h3>
        <dl className="ga-stats">
          <div><dt>Quote-verified sentences</dt><dd>{verified}</dd></div>
          <div><dt>Derived from study counts</dt><dd>{derived}</dd></div>
          <div><dt>Refused by the gate</dt><dd>{refused}</dd></div>
          <div><dt>Sections grounded</dt><dd>{grounded}/{total}</dd></div>
        </dl>
        <button className="ga-link" onClick={onMethod}>How these are checked</button>
      </section>

      {refs.length > 0 && (
        <section className="ga-card">
          <h3 className="ga-h">Sources</h3>
          <ul className="ga-list">
            {refs.map((r) => (
              <li key={r.document_id}>
                <Icon.report size={14} />
                <div>
                  <span className="ga-meta">
                    {(r.authors?.[0] ?? "Unknown")}{(r.authors?.length ?? 0) > 1 ? " et al." : ""}
                    {r.year ? ` · ${r.year}` : ""}
                  </span>
                  <span className="ga-title">{r.title}</span>
                </div>
              </li>
            ))}
          </ul>
          {onNavigate && (
            <button className="ga-link" onClick={() => onNavigate("documents")}>
              View all {report.references?.length ?? 0} <Icon.arrowRight size={12} />
            </button>
          )}
        </section>
      )}

      {open.length > 0 && (
        <section className="ga-card">
          <h3 className="ga-h">Open questions</h3>
          <ul className="ga-list ga-q">
            {open.map((s) => (
              <li key={s.heading}>
                <Icon.about size={14} />
                <span>{s.sub_question || s.heading}</span>
              </li>
            ))}
          </ul>
          {onNavigate && (
            <button className="ga-link" onClick={() => onNavigate("chat")}>Ask about these</button>
          )}
        </section>
      )}
    </aside>
  );
}

export function ActionDock({
  onNavigate, onMethod,
}: {
  onNavigate?: (to: DockTarget) => void;
  onMethod: () => void;
}) {
  if (!onNavigate) return null;
  // Portalled to <body>: `position: fixed` inside a transformed or
  // backdrop-filtered ancestor (the report's entrance animation, the glass
  // window) is fixed to THAT box, so the dock scrolled away with the report.
  return createPortal(
    <nav className="ga-dock" aria-label="Report actions">
      <button onClick={() => onNavigate("chat")}><Icon.ask size={15} /> Ask follow-up</button>
      <button onClick={() => onNavigate("compare")}><Icon.compare size={15} /> Compare papers</button>
      <button onClick={() => onNavigate("map")}><Icon.map size={15} /> View map</button>
      <button onClick={() => onNavigate("monitor")}><Icon.monitor size={15} /> Check new evidence</button>
      <button onClick={onMethod}><Icon.shieldCheck size={15} /> Open audit trail</button>
    </nav>,
    document.body,
  );
}
