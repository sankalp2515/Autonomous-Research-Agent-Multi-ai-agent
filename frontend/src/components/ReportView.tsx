// Report shell: resolve a report (by id, or by a public share slug) and hand it
// to the single renderer.
//
// There is ONE report view. Classic and Studio were an A/B of the same data in
// two frames; carrying three renderers meant every report change had to be made
// three times and two were always behind. `SystematicReview` is the report now,
// and everything in this file is chrome around it: fetch, share, export.

import { useCallback, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "../api";
import type { Report } from "../types";
import { Empty, Spinner } from "./ui";
import { Icon } from "./icons";
import { SystematicReview } from "./SystematicReview";
import { trackEvent } from "../telemetry";

// ── exports ──────────────────────────────────────────────────────────────

function dl(name: string, content: string, mime: string) {
  const b = new Blob([content], { type: mime });
  const u = URL.createObjectURL(b);
  const a = document.createElement("a");
  a.href = u;
  a.download = name;
  a.click();
  URL.revokeObjectURL(u);
}

const slug = (t: string) => t.slice(0, 60).replace(/[^a-z0-9]+/gi, "_");

/** Reference numbering in citation order — shared by every export format so a
 *  superscript in the Markdown resolves to the same entry as in the reader. */
function buildRefs(report: Report) {
  const order: string[] = [];
  const num = new Map<string, number>();
  const push = (docId?: string) => {
    if (docId && !num.has(docId)) {
      order.push(docId);
      num.set(docId, order.length);
    }
  };
  for (const s of report.sections) {
    for (const c of s.claims ?? []) push(c.evidence?.[0]?.document?.id);
  }
  for (const row of report.confidence.evidence_matrix ?? []) push(row.doc_id);
  const byDoc = new Map(report.references.map((r) => [r.document_id, r]));
  const entries = order
    .map((id) => byDoc.get(id))
    .filter((r): r is Report["references"][number] => !!r);
  return { num, entries };
}

function buildBibtex(r: Report) {
  return r.references
    .map((ref, i) => {
      const type = ref.source_type === "paper" ? "article" : "misc";
      const surname = (ref.authors?.[0] ?? "ref").split(/\s+/).pop() ?? "ref";
      const key = `${surname}${ref.year ?? ""}${i + 1}`.replace(/[^a-z0-9]/gi, "").toLowerCase();
      const f = [`  title={${ref.title}}`];
      if (ref.authors?.length) f.push(`  author={${ref.authors.join(" and ")}}`);
      if (ref.year) f.push(`  year={${ref.year}}`);
      if (ref.url) f.push(`  url={${ref.url}}`);
      return `@${type}{${key},\n${f.join(",\n")}\n}`;
    })
    .join("\n\n");
}

function buildRis(r: Report) {
  return r.references
    .map((ref) => {
      const lines = [`TY  - ${ref.source_type === "paper" ? "JOUR" : "GEN"}`];
      for (const a of ref.authors ?? []) lines.push(`AU  - ${a}`);
      lines.push(`TI  - ${ref.title}`);
      if (ref.year) lines.push(`PY  - ${ref.year}`);
      if (ref.url) lines.push(`UR  - ${ref.url}`);
      lines.push("ER  - ");
      return lines.join("\n");
    })
    .join("\n\n");
}

/** Markdown mirrors what the reader sees, including the verification appendix —
 *  an export that quietly dropped the refusals would misrepresent the method. */
function buildMarkdown(r: Report) {
  const c = r.confidence;
  const { num, entries } = buildRefs(r);
  const out: string[] = [];

  out.push(`# ${c.plan?.objective || r.title}\n`);
  if (c.abstract?.verdict) out.push(`> ${c.abstract.verdict.text}\n`);
  if (c.abstract?.sentences?.length) {
    out.push("## Abstract\n");
    out.push(c.abstract.sentences.map((s) => s.text).join(" ") + "\n");
  }

  for (const s of r.sections) {
    out.push(`## ${s.heading}\n`);
    if (s.sub_question) out.push(`*${s.sub_question}*\n`);
    if (s.status === "gap") {
      out.push(s.gap_kind === "drafting_failed"
        ? `> Veriscope could not draft this section. ${s.gap_note}\n`
        : `> No verifiable evidence. ${s.gap_note}\n`);
      continue;
    }
    for (const cl of s.claims ?? []) {
      const doc = cl.evidence?.[0]?.document?.id;
      const n = doc ? num.get(doc) : undefined;
      out.push(`${cl.text}${n ? ` [${n}]` : ""}`);
    }
    out.push("");
  }

  const refused = c.refused_claims ?? [];
  if (refused.length) {
    out.push("## Verification appendix\n");
    out.push(`${refused.length} statement(s) were drafted, checked against their cited span, and withheld:\n`);
    for (const f of refused) {
      out.push(`- **${f.reason.replace(/_/g, " ")}** — "${f.text}"`);
      if (f.source_span) out.push(`  - source: "${f.source_span}"`);
    }
    out.push("");
  }

  out.push("## References\n");
  entries.forEach((ref, i) => {
    const authors = ref.authors?.length ? `${ref.authors.join(", ")} ` : "";
    out.push(`${i + 1}. ${authors}${ref.year ? `(${ref.year}) ` : ""}${ref.title}. ${ref.url ?? ""}`);
  });
  return out.join("\n");
}

// ── export sheet ─────────────────────────────────────────────────────────

function ExportSheet({
  report, shareUrl, sharing, onShare, onClose,
}: {
  report: Report;
  shareUrl: string;
  sharing: boolean;
  onShare: () => void;
  onClose: () => void;
}) {
  const name = slug(report.title);
  const [copied, setCopied] = useState("");

  // Escape closes, and the page behind must not scroll under the modal —
  // both were free while the backdrop was (wrongly) clipped inside the
  // scrolling column, and both have to be explicit now it covers the viewport.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [onClose]);

  const items: {
    id: string; icon: keyof typeof Icon; title: string; desc: string;
    ext: string; body: () => string; mime: string;
  }[] = [
    {
      id: "md", icon: "report", title: "Full Markdown Report", ext: ".md",
      desc: "Inline citations, NLI scores, and the complete verification appendix.",
      body: () => buildMarkdown(report), mime: "text/markdown",
    },
    {
      id: "bib", icon: "quote", title: "BibTeX Bibliography", ext: ".bib",
      desc: "Formatted entries for LaTeX, Overleaf, and reference managers.",
      body: () => buildBibtex(report), mime: "application/x-bibtex",
    },
    {
      id: "ris", icon: "sources", title: "RIS Reference Citation", ext: ".ris",
      desc: "Compatible with EndNote, RefWorks, and Zotero.",
      body: () => buildRis(report), mime: "application/x-research-info-systems",
    },
  ];

  async function copy(id: string, text: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(id);
      window.setTimeout(() => setCopied(""), 1600);
    } catch {
      /* clipboard unavailable — the download button still works */
    }
  }

  // PORTALLED TO <body> ON PURPOSE.
  //
  // `position: fixed; inset: 0` is fixed to the VIEWPORT only while no ancestor
  // establishes a containing block — any ancestor with a transform, filter, or
  // will-change captures it. The report shell has one, so the backdrop was
  // being clipped to the reading column: the sidebar and the right margin
  // stayed undimmed and the modal looked like it belonged to the page rather
  // than sitting above it. Rendering outside the shell is the only fix that
  // does not depend on knowing which ancestor is responsible.
  return createPortal((
    <div className="rp-sheet-backdrop" onClick={onClose}>
      <div className="rp-sheet" onClick={(e) => e.stopPropagation()} role="dialog"
           aria-label="Export and share research report">
        <div className="rp-sheet-h">
          <span className="rp-sheet-mark"><Icon.download size={15} /></span>
          <span className="rp-sheet-t">
            <b>Export &amp; Share Research Report</b>
            <em>Download citation-grounded formats for Zotero, Mendeley, Obsidian, or publication.</em>
          </span>
          <button className="rp-sheet-x" onClick={onClose} aria-label="Close">×</button>
        </div>

        <div className="rp-sheet-body">
          {items.map((it) => {
            const Ico = Icon[it.icon];
            return (
              <div className="rp-xcard" key={it.id}>
                <span className="rp-xcard-i"><Ico size={16} /></span>
                <span className="rp-xcard-t">
                  <b>{it.title} ({it.ext})</b>
                  <em>{it.desc}</em>
                </span>
                <button className="rp-xcard-copy" title={`Copy ${it.ext} to clipboard`}
                        aria-label={`Copy ${it.title}`}
                        onClick={() => copy(it.id, it.body())}>
                  {copied === it.id ? <Icon.check size={14} /> : <Icon.quote size={14} />}
                </button>
                <button className={`rp-xcard-dl${it.id === "md" ? " is-primary" : ""}`}
                        onClick={() => dl(`${name}${it.ext}`, it.body(), it.mime)}>
                  Download {it.ext}
                </button>
              </div>
            );
          })}
        </div>

        <div className="rp-sheet-foot">
          <button className="rp-xfoot" onClick={() => window.print()}>
            <Icon.report size={14} /> Print / Save as Clean PDF
          </button>
          {shareUrl ? (
            <input className="rp-xlink" readOnly value={shareUrl}
                   onFocus={(e) => e.currentTarget.select()} />
          ) : (
            <button className="rp-xshare" onClick={onShare} disabled={sharing}>
              <Icon.external size={14} />
              {sharing ? "Creating link…" : "Copy Shareable Link"}
            </button>
          )}
        </div>
      </div>
    </div>
  ), document.body);
}

// ── shell ────────────────────────────────────────────────────────────────

export default function ReportView({
  projectId, reportId, sharedSlug,
}: {
  projectId: string;
  reportId: string | null;
  sharedSlug?: string;
}) {
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState("");
  const [resolving, setResolving] = useState(true);
  const [exportOpen, setExportOpen] = useState(false);
  const [shareUrl, setShareUrl] = useState("");
  const [sharing, setSharing] = useState(false);
  const shared = !!sharedSlug;

  useEffect(() => {
    let alive = true;
    setReport(null);
    setError("");
    setShareUrl("");
    setResolving(true);
    (async () => {
      try {
        if (sharedSlug) {
          const r = await api.getShared(sharedSlug);
          if (alive) setReport(r);
        } else if (reportId) {
          const r = await api.getReport(reportId);
          if (alive) setReport(r);
        } else if (projectId) {
          // No explicit id: fall back to this project's most recent report.
          const runs = await api.listRuns(projectId);
          const latest = runs.find((x) => x.report_id);
          if (latest?.report_id) {
            const r = await api.getReport(latest.report_id);
            if (alive) setReport(r);
          }
        }
      } catch (err: unknown) {
        if (alive) setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (alive) setResolving(false);
      }
    })();
    return () => { alive = false; };
  }, [projectId, reportId, sharedSlug]);

  useEffect(() => {
    if (report) trackEvent("report_view", { report_id: report.id, shared });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [report?.id, shared]);

  const makeShareLink = useCallback(async () => {
    if (!report) return;
    setSharing(true);
    try {
      const { slug: s } = await api.createShare(report.id);
      setShareUrl(`${window.location.origin}/#/s/${s}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSharing(false);
    }
  }, [report]);

  const title = useMemo(
    () => report?.confidence.plan?.objective || report?.title || "",
    [report]
  );

  if (resolving) return <Spinner />;
  if (error) return <Empty glyph="⚠" title="Could not load the report">{error}</Empty>;
  if (!report) {
    return (
      <Empty glyph="◇" title="No report yet">
        Run a research question and the verified review will appear here.
      </Empty>
    );
  }

  return (
    <div className="rp rise-in">
      <div className="rp-body">
        <div className="export-bar">
          <span className="rp-kick">Verified systematic review</span>
          {shared && <span className="rp-shared-badge">🔗 Shared · read-only</span>}
          <span className="spacer" />
          {!shared && (
            <button className="export-open" onClick={() => setExportOpen(true)} title={title}>
              <Icon.download size={14} /> Export
            </button>
          )}
        </div>
        <SystematicReview report={report} />
      </div>
      {exportOpen && (
        <ExportSheet
          report={report}
          shareUrl={shareUrl}
          sharing={sharing}
          onShare={makeShareLink}
          onClose={() => setExportOpen(false)}
        />
      )}
    </div>
  );
}
