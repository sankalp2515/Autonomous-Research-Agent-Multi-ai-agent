import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { Contradiction, Report } from "../types";
import EvidenceDrawer from "./EvidenceDrawer";
import { Empty, Spinner } from "./ui";

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

function exportBibtex(r: Report) {
  const out = r.references
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
  dl(`${slug(r.title)}.bib`, out, "application/x-bibtex");
}

function exportRis(r: Report) {
  const out = r.references
    .map((ref) => {
      const ty = ref.source_type === "paper" ? "JOUR" : "ELEC";
      const L = [`TY  - ${ty}`, `TI  - ${ref.title}`];
      (ref.authors ?? []).forEach((a) => L.push(`AU  - ${a}`));
      if (ref.year) L.push(`PY  - ${ref.year}`);
      if (ref.url) L.push(`UR  - ${ref.url}`);
      L.push("ER  - ");
      return L.join("\n");
    })
    .join("\n\n");
  dl(`${slug(r.title)}.ris`, out, "application/x-research-info-systems");
}

type RefEntry = { n: number; title: string; url: string; type: string };

function buildRefs(report: Report) {
  const refs: RefEntry[] = [];
  const byKey = new Map<string, number>();
  const claimRef = new Map<string, number>();
  for (const s of report.sections) {
    if (s.status === "gap") continue;
    for (const c of s.claims) {
      const doc = c.evidence[0]?.document ?? {};
      const key = `${(doc as any).title ?? ""}|${(doc as any).url ?? ""}`;
      let n = byKey.get(key);
      if (!n) {
        n = refs.length + 1;
        byKey.set(key, n);
        refs.push({
          n,
          title: (doc as any).title ?? "(untitled)",
          url: (doc as any).url ?? "",
          type: (doc as any).source_type ?? "source",
        });
      }
      claimRef.set(c.claim_id, n);
    }
  }
  return { refs, claimRef };
}

function exportMarkdown(r: Report, refs: RefEntry[], claimRef: Map<string, number>) {
  const L: string[] = [`# ${r.title}`, ""];
  L.push(
    `*Verified research report — ${r.confidence.sections_verified}/${r.confidence.sections_total} ` +
      `sections grounded. Every sentence is quote-checked against a cited source.*`,
    ""
  );
  const findings = r.sections.filter((s) => s.status !== "gap" && s.claims.length);
  if (findings.length) {
    L.push("## Key findings", "");
    for (const s of findings) {
      const c = s.claims[0];
      L.push(`- **${s.heading}.** ${c.text} [${claimRef.get(c.claim_id)}]`);
    }
    L.push("");
  }
  r.sections.forEach((s, i) => {
    const tag = s.track === "technical" ? "practitioner sources" : "scholarly evidence";
    L.push(`## ${i + 1}. ${s.heading}`, `*${s.sub_question}  ·  ${tag}*`, "");
    if (s.status === "gap") {
      L.push(`> **Evidence gap.** ${s.gap_note || "No verifiable support was found."}`, "");
      return;
    }
    L.push(
      s.claims.map((c) => `${c.text.trim()} [${claimRef.get(c.claim_id)}]`).join(" "),
      ""
    );
  });
  if (refs.length) {
    L.push("## References", "");
    refs.forEach((r2) => L.push(`${r2.n}. ${r2.title} — ${r2.type}${r2.url ? ` <${r2.url}>` : ""}`));
  }
  const blob = new Blob([L.join("\n")], { type: "text/markdown" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${r.title.slice(0, 60).replace(/[^a-z0-9]+/gi, "_")}.md`;
  a.click();
  URL.revokeObjectURL(url);
}

function Prose({
  claims,
  claimRef,
  onCite,
}: {
  claims: Report["sections"][0]["claims"];
  claimRef: Map<string, number>;
  onCite: (id: string) => void;
}) {
  return (
    <p className="rp-prose">
      {claims.map((c) => {
        const n = claimRef.get(c.claim_id);
        const ev = c.evidence[0];
        const src = ev?.document;
        // Confidence from the NLI gate: strong entailment vs merely
        // quote-matched. Colors the citation so readers see evidence strength.
        const strong = ev?.nli_label === "entailment" && (ev?.nli_score ?? 0) >= 0.8;
        const cls = ev?.nli_label === "entailment" || ev?.nli_label === "skipped"
          ? (strong ? "strong" : "moderate")
          : "moderate";
        return (
          <span key={c.claim_id} className="rp-claim">
            {c.text.trim()}{" "}
            <sup
              className={`rp-cite ${cls}`}
              title={`${(src as any)?.title ?? "source"} — ${strong ? "strong" : "moderate"} support · click to see the exact quote`}
              onClick={() => onCite(c.claim_id)}
            >
              {n}
            </sup>{" "}
          </span>
        );
      })}
    </p>
  );
}

// Adaptive comparison table. The backend chose this layout for the section and
// assigned each VERIFIED claim (by index) to a cell — so every cell is still
// quote-checked and click-to-source, exactly like the prose citations.
function ClaimTable({
  section,
  claimRef,
  onCite,
}: {
  section: Report["sections"][0];
  claimRef: Map<string, number>;
  onCite: (id: string) => void;
}) {
  const layout = section.layout!;
  const claims = section.claims;
  const cell = (idxs: number[] | undefined) => {
    if (!idxs?.length) return <span className="rp-td-empty">—</span>;
    return idxs.map((i) => {
      const c = claims[i];
      if (!c) return null;
      const ev = c.evidence[0];
      const strong = ev?.nli_label === "entailment" && (ev?.nli_score ?? 0) >= 0.8;
      const cls = ev?.nli_label === "contradiction" ? "moderate" : strong ? "strong" : "moderate";
      return (
        <span key={c.claim_id} className="rp-td-claim">
          {c.text.trim()}{" "}
          <sup className={`rp-cite ${cls}`} onClick={() => onCite(c.claim_id)}
               title="click to see the exact quote">
            {claimRef.get(c.claim_id)}
          </sup>{" "}
        </span>
      );
    });
  };
  return (
    <div className="rp-table-wrap">
      <table className="rp-table">
        <thead>
          <tr>
            <th />
            {layout.columns.map((col) => <th key={col}>{col}</th>)}
          </tr>
        </thead>
        <tbody>
          {layout.rows.map((row, ri) => (
            <tr key={ri}>
              <th scope="row">{row.label}</th>
              {layout.columns.map((col) => (
                <td key={col}>{cell(row.cells[col])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="rp-table-note">Every cell is a quote-verified claim — click any ¹ for its source.</p>
    </div>
  );
}

export default function ReportView({
  projectId,
  reportId,
}: {
  projectId: string;
  reportId: string | null;
}) {
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState("");
  const [openClaim, setOpenClaim] = useState<string | null>(null);
  const [resolving, setResolving] = useState(true);
  const [tensions, setTensions] = useState<Contradiction[]>([]);
  const [tensionsLoading, setTensionsLoading] = useState(false);
  const [tab, setTab] = useState<"scholarly" | "practitioner">("scholarly");

  useEffect(() => {
    if (!report) return;
    let alive = true;
    setTensions([]);
    setTensionsLoading(true);
    api
      .getContradictions(report.id)
      .then((r) => alive && setTensions(r.contradictions))
      .catch(() => {})
      .finally(() => alive && setTensionsLoading(false));
    return () => {
      alive = false;
    };
  }, [report?.id]);

  useEffect(() => {
    let alive = true;
    setReport(null);
    setError("");
    setResolving(true);
    (async () => {
      try {
        let id = reportId;
        if (!id) {
          const runs = await api.listRuns(projectId);
          id = runs.find((r) => r.report_id)?.report_id ?? null;
        }
        if (!id) {
          if (alive) setResolving(false);
          return;
        }
        const r = await api.getReport(id);
        if (alive) {
          setReport(r);
          setResolving(false);
        }
      } catch (e: any) {
        if (alive) {
          setError(String(e.message ?? e));
          setResolving(false);
        }
      }
    })();
    return () => {
      alive = false;
    };
  }, [projectId, reportId]);

  const { refs, claimRef } = useMemo(
    () => (report ? buildRefs(report) : { refs: [], claimRef: new Map<string, number>() }),
    [report]
  );

  if (error) return <p style={{ color: "var(--bad)" }}>{error}</p>;
  if (resolving) return <p><Spinner /> loading report…</p>;
  if (!report)
    return (
      <Empty glyph="¶" title="No report yet">
        Go to <strong>Research</strong> and run a question. The verified report
        appears here — only gate-checked claims, with gaps stated honestly.
      </Empty>
    );

  const conf = report.confidence;
  const scholarlySections = report.sections.filter((s) => s.track !== "technical");
  const practitionerSections = report.sections.filter((s) => s.track === "technical");
  const hasPractitioner = practitionerSections.length > 0;
  const shownSections = tab === "scholarly" ? scholarlySections : practitionerSections;
  // Key findings, tensions and references belong to the scholarly report only.
  const findings = scholarlySections.filter((s) => s.status !== "gap" && s.claims.length);
  const readMins = Math.max(1, Math.round(refs.length * 0.6));
  const onScholarly = tab === "scholarly";
  // Transparency: the actual time period the cited sources span, so the
  // recency claim is verifiable, not a promise.
  const years = report.references.map((r) => r.year).filter((y): y is number => !!y);
  const recentCutoff = new Date().getFullYear() - 4;
  const yearSpan = years.length
    ? {
        min: Math.min(...years),
        max: Math.max(...years),
        recent: years.filter((y) => y >= recentCutoff).length,
        total: years.length,
      }
    : null;
  // References are numbered in citation order (so superscripts match). Show
  // each tab only its own evidence class — practitioner sources must not
  // appear in the scholarly reference list.
  const isPractitioner = (t: string) => t === "repo" || t === "blog";
  const shownRefs = onScholarly
    ? refs.filter((r) => !isPractitioner(r.type))
    : refs.filter((r) => isPractitioner(r.type));

  return (
    <div className="rp">
      <header className="rp-hero">
        <div className="export-bar">
          <span className="overline">Verified research report</span>
          <span style={{ flex: 1 }} />
          <div className="export-menu">
            <span className="export-label">Export</span>
            <button className="export-opt" onClick={() => exportMarkdown(report, refs, claimRef)}>Markdown</button>
            <button className="export-opt" onClick={() => exportBibtex(report)}>BibTeX</button>
            <button className="export-opt" onClick={() => exportRis(report)}>RIS</button>
            <button className="export-opt" onClick={() => window.print()}>Print / PDF</button>
          </div>
        </div>
        <h1 className="rp-title">{report.title}</h1>
        <div className="rp-meta">
          <span className={conf.sections_verified === conf.sections_total ? "rp-pill ok" : "rp-pill warn"}>
            {conf.sections_verified}/{conf.sections_total} sections grounded
          </span>
          <span className="rp-pill">{refs.length} sources</span>
          {yearSpan && (
            <span
              className="rp-pill"
              title={`Ranking is recency-weighted, but relevance still wins — older foundational work can rank high. ${yearSpan.recent} of ${yearSpan.total} dated sources are from ${recentCutoff} or later.`}
            >
              sources {yearSpan.min === yearSpan.max ? yearSpan.min : `${yearSpan.min}–${yearSpan.max}`}
              {" · "}{yearSpan.recent}/{yearSpan.total} since {recentCutoff}
            </span>
          )}
          <span className="rp-pill">~{readMins} min read</span>
          <span className="rp-meta-note">Every sentence is quote-verified · click any ¹ to see the source</span>
        </div>
      </header>

      {hasPractitioner && (
        <div className="rp-tabs">
          <button className={`rp-tab ${onScholarly ? "active" : ""}`} onClick={() => setTab("scholarly")}>
            Scholarly report <span className="rp-tab-n">{scholarlySections.length}</span>
          </button>
          <button className={`rp-tab ${!onScholarly ? "active" : ""}`} onClick={() => setTab("practitioner")}>
            Practitioner sources <span className="rp-tab-n">{practitionerSections.length}</span>
          </button>
        </div>
      )}

      {!onScholarly && (
        <div className="rp-practitioner-banner">
          These are <strong>practitioner sources</strong> — engineering write-ups, blog posts and code.
          They are <strong>not peer-reviewed</strong> and are kept entirely separate from the scholarly
          report above. Treat them as implementation signal, not evidence.
        </div>
      )}

      {onScholarly && findings.length > 0 && (
        <section className="rp-keyfindings">
          <h2>Key findings</h2>
          <ul>
            {findings.map((s) => {
              const c = s.claims[0];
              return (
                <li key={s.heading} onClick={() => setOpenClaim(c.claim_id)}>
                  <span className="rp-kf-tag">{s.heading}</span>
                  {c.text.trim()}
                  <sup className="rp-cite">{claimRef.get(c.claim_id)}</sup>
                </li>
              );
            })}
          </ul>
        </section>
      )}

      {onScholarly && (tensions.length > 0 || tensionsLoading) && (
        <section className="rp-tensions">
          <h2>
            Tensions in the evidence
            {tensionsLoading && <Spinner />}
          </h2>
          <p className="rp-refs-note">
            Where two sources disagree. Both claims are individually quote-verified,
            so these are real disagreements between sources — worth weighing.
          </p>
          {tensions.map((c, i) => (
            <div className="tension" key={i}>
              <div className="tension-side" onClick={() => setOpenClaim(c.a.claim_id)}>
                <p>{c.a.text}</p>
                <span className="tension-src">
                  {c.a.source}{c.a.page > 0 ? ` · p.${c.a.page}` : ""}
                </span>
              </div>
              <div className="tension-vs">vs</div>
              <div className="tension-side" onClick={() => setOpenClaim(c.b.claim_id)}>
                <p>{c.b.text}</p>
                <span className="tension-src">
                  {c.b.source}{c.b.page > 0 ? ` · p.${c.b.page}` : ""}
                </span>
              </div>
            </div>
          ))}
        </section>
      )}

      {shownSections.map((section, si) => {
        return (
          <article className="rp-sec" key={si} id={`sec-${si}`}>
            <div className="rp-sec-head">
              <span className="rp-sec-num">{si + 1}</span>
              <div>
                <h2>{section.heading}</h2>
                <p className="rp-kicker">{section.sub_question}</p>
              </div>
            </div>
            {section.status === "gap" ? (
              <div className="rp-gap">
                <strong>Evidence gap.</strong>{" "}
                {section.gap_note || "The corpus could not support verifiable claims here."}
              </div>
            ) : section.layout?.kind === "table" && section.layout.rows?.length ? (
              <ClaimTable section={section} claimRef={claimRef} onCite={setOpenClaim} />
            ) : (
              <Prose claims={section.claims} claimRef={claimRef} onCite={setOpenClaim} />
            )}
          </article>
        );
      })}

      {shownRefs.length > 0 && (
        <section className="rp-refs">
          <h2>References</h2>
          <p className="rp-refs-note">
            {onScholarly
              ? "Scholarly sources only — practitioner references are listed under their own tab. Every reference resolved against the corpus, so fabricated citations are structurally impossible."
              : "Practitioner sources — not peer-reviewed, listed separately from the scholarly references."}
          </p>
          <ol>
            {shownRefs.map((r) => (
              <li key={r.n} id={`ref-${r.n}`}>
                <span className="rp-ref-num">{r.n}</span>
                <span className="rp-ref-body">
                  {r.title}
                  {(() => {
                    const m = report.references.find((x) => x.title === r.title);
                    const bits: string[] = [];
                    if (m?.authors?.length)
                      bits.push(m.authors[0] + (m.authors.length > 1 ? " et al." : ""));
                    if (m?.year) bits.push(String(m.year));
                    if (m?.citations) bits.push(`cited ${m.citations}×`);
                    return bits.length ? (
                      <span className="rp-ref-meta"> · {bits.join(" · ")}</span>
                    ) : null;
                  })()}
                  <span className="rp-ref-type">{r.type}</span>
                  {r.url && (
                    <a href={r.url} target="_blank" rel="noreferrer" className="rp-ref-link">
                      open ↗
                    </a>
                  )}
                </span>
              </li>
            ))}
          </ol>
        </section>
      )}

      {openClaim && (
        <EvidenceDrawer claimId={openClaim} projectId={projectId} onClose={() => setOpenClaim(null)} />
      )}
    </div>
  );
}
