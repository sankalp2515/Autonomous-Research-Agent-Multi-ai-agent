// Systematic-review report layout: the Elicit document spine (question as
// title, TL;DR, PRISMA flow, published screening criteria, published extraction
// columns, study-characteristics table, per-axis tables with narrative) carrying
// Veriscope's grounding contract (every sentence is a gate-verified Claim, every
// citation opens the exact source span in the evidence rail).
//
// Two things here exist in neither system alone and are the reason this layout
// replaces the old one:
//
//   1. THE PROTOCOL IS PUBLISHED. The screening criteria and the per-column
//      extraction instructions are printed verbatim — and they are the same
//      strings the screen and the extractor were actually given, not a prose
//      description written for the reader. A review is reproducible only if
//      those cannot drift apart, which is why they are read from
//      confidence.evidence_schema rather than restated here.
//
//   2. THE REFUSALS ARE PUBLISHED. Elicit cannot show what it withheld because
//      nothing is withheld; Veriscope used to reduce its refusals to a count.
//      The verification appendix shows each rejected statement beside the span
//      it was checked against. Every one of them reads plausibly and cites a
//      real paper — which is the whole argument for the gate, and it cannot be
//      made with a number.
//
// Rendering rule unchanged from the rest of the product: this component renders
// ONLY gate-verified claim rows. It never authors a sentence.

import { useMemo, useState } from "react";
import type {
  ComparisonRow, ComparisonTable, DerivedStatement, EvidenceRow, Report,
  RefusedClaim, Synthesis,
} from "../types";
import { useEvidence } from "../evidence";
import { ReadAloud } from "./ReadAloud";

// ── citation + NLI stamp ────────────────────────────────────────────────
// The superscript number is the reference; the mono value beside it is the
// MEASURED entailment of that sentence against its cited span. It is shown
// because the gate computed it, and labelled as entailment rather than as
// confidence — it says the sentence is faithful to its source, not that the
// finding is well established.
function Cite({ n, score, claimId }: { n: number; score?: number; claimId?: string }) {
  const { open } = useEvidence();
  return (
    <>
      <button
        className="sr-c"
        onClick={() => claimId && open(claimId)}
        disabled={!claimId}
        title={claimId ? "Open the exact source passage" : "Source unavailable"}
      >
        {n}
      </button>
      {typeof score === "number" && score > 0 ? (
        <span className="sr-nli" title={`NLI entailment ${score.toFixed(2)} against the cited span`}>
          ·{score.toFixed(2)}
        </span>
      ) : null}
    </>
  );
}

/** Reference numbering in citation order, keyed by document id. */
function useRefs(report: Report) {
  return useMemo(() => {
    const order: string[] = [];
    const num = new Map<string, number>();
    for (const s of report.sections) {
      for (const c of s.claims ?? []) {
        const doc = c.evidence?.[0]?.document?.id;
        if (doc && !num.has(doc)) {
          order.push(doc);
          num.set(doc, order.length);
        }
      }
    }
    // Matrix findings extend the numbering so a study cited only in a table
    // still resolves to a reference.
    for (const row of report.confidence.evidence_matrix ?? []) {
      if (row.doc_id && !num.has(row.doc_id)) {
        order.push(row.doc_id);
        num.set(row.doc_id, order.length);
      }
    }
    return { order, num };
  }, [report]);
}

// ── PRISMA-style flow ───────────────────────────────────────────────────
// Real tallies from state["funnel"], never estimates. A stage with no recorded
// count is omitted rather than drawn as zero.
function Flow({ report }: { report: Report }) {
  const f = report.confidence.funnel ?? {};
  const ladder = f.ladder ?? {};
  const byCriterion = f.screen_excluded_by_criterion ?? {};
  const criteria = report.confidence.evidence_schema?.screening_criteria ?? [];
  const refused = report.confidence.refused_claims ?? [];
  const verified = f.claims_verified ?? 0;
  // A report assembled before refusals were captured has NO record of them.
  // That is not the same as zero, and printing "0 refused" would publish a
  // pipeline limitation as a fact about the run — the exact error the cell
  // states exist to prevent, reintroduced one layer up.
  const gateRecorded = report.confidence.refusal_reasons !== undefined;
  const refusedTotal = Object.values(report.confidence.refusal_reasons ?? {})
    .reduce((a, b) => a + b, 0);

  const discovered = ladder.discovered ?? f.found;
  const screened = ladder.screened ?? f.screened;
  const included = ladder.extracted ?? f.extracted_studies;
  const screenedOut = f.screened_out;

  if (!discovered && !screened) return null;

  return (
    <div className="sr-prisma">
      {discovered ? (
        <>
          <div className="sr-prow">
            <div className="sr-pbox" style={{ maxWidth: 250 }}>
              Records from paper search<br />
              <b>n = {discovered}</b>
            </div>
          </div>
          <div className="sr-parrow">↓</div>
        </>
      ) : null}

      <div className="sr-prow">
        <div className="sr-pbox" style={{ maxWidth: 460 }}>
          {criteria.length
            ? <>Screened on abstracts against {criteria.length} criteria:<br />
                {criteria.map((c) => c.name).join(" · ")}<br /></>
            : <>Screened on titles and abstracts<br /></>}
          <b>n = {screened ?? discovered}</b>
        </div>
      </div>
      <div className="sr-parrow">↓</div>

      <div className="sr-split">
        <div className="sr-pbox">
          Included for extraction<br />
          <b>n = {included ?? 0}</b>
        </div>
        {screenedOut ? (
          <div className="sr-pbox">
            Screened out<br />
            <b>n = {screenedOut}</b>
            {Object.keys(byCriterion).length ? (
              <span className="sr-dim">
                <br />
                {Object.entries(byCriterion)
                  .sort((a, b) => b[1] - a[1])
                  .map(([k, v]) => `${k}: ${v}`)
                  .join(" · ")}
              </span>
            ) : null}
          </div>
        ) : null}
      </div>

      {verified || refusedTotal ? (
        <>
          <div className="sr-parrow">↓</div>
          <div className="sr-prow">
            <div className="sr-pbox" style={{ maxWidth: 460 }}>
              <b>Verification gate</b>
              <br />
              {gateRecorded ? (
                <>
                  {verified + refusedTotal} extracted statements checked against their
                  verbatim source span
                  <br />
                  <b>
                    {verified} entailed · {refusedTotal} refused
                  </b>
                  {refused.length && refused.length < refusedTotal ? (
                    <span className="sr-dim">
                      <br />
                      {refused.length} shown in the verification appendix
                    </span>
                  ) : null}
                </>
              ) : (
                <>
                  <b>{verified} statements entailed</b> and published
                  <span className="sr-dim">
                    <br />
                    This report predates refusal capture, so what the gate rejected
                    was not recorded — not zero.
                  </span>
                </>
              )}
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}

// ── study characteristics ───────────────────────────────────────────────
// The sample is described before any conclusion drawn from it. "Full text?" is
// its own column because it is the single most decision-relevant fact about a
// row: an abstract-only study can never support an absence claim.
function StudyTable({ rows, refs }: { rows: EvidenceRow[]; refs: Map<string, number> }) {
  if (!rows.length) return null;
  return (
    <div className="sr-tw">
      <table>
        <caption>
          Table 1. Characteristics of included studies. "Full text" records whether the
          paper's body was read; an abstract-only row cannot support a "not reported" verdict.
        </caption>
        <thead>
          <tr>
            <th>Study</th>
            <th>Full text<br />retrieved?</th>
            <th>Systems evaluated</th>
            <th>Compared against</th>
            <th>Datasets / corpora</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const n = refs.get(r.doc_id);
            const full = (r as EvidenceRow & { full_text?: boolean }).full_text;
            return (
              <tr key={r.doc_id}>
                <td>
                  {r.title || "untitled"}
                  {r.year ? `, ${r.year}` : ""}
                  {n ? <sup className="sr-refn"> {n}</sup> : null}
                </td>
                <td>
                  {full === false ? (
                    <span className="sr-badge b-warn">Abstract only</span>
                  ) : (
                    <span className="sr-badge b-pass">Yes</span>
                  )}
                </td>
                <td>{r.frameworks?.join(", ") || <span className="sr-dim">—</span>}</td>
                <td>{r.baselines?.join(", ") || <span className="sr-dim">—</span>}</td>
                <td>{r.datasets?.join(", ") || <span className="sr-dim">—</span>}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ── the evidence grid ───────────────────────────────────────────────────
// Four cell states, and the two that mean "absent" are only reachable with
// evidence of search. `extraction_uncertain` is a statement about Veriscope,
// never about the paper, and is labelled as such.
const CELL_LABEL: Record<string, { text: string; cls: string; title: string }> = {
  not_reported: {
    text: "not reported",
    cls: "sr-dim",
    title: "The full text was read and several targeted searches found no such measurement — a fact about this study.",
  },
  not_applicable: {
    text: "n/a",
    cls: "sr-dim sr-ital",
    title: "This axis cannot apply to this study's design.",
  },
  extraction_uncertain: {
    text: "unresolved",
    cls: "sr-unres",
    title: "WE could not establish either way. A statement about this pipeline, not about the study.",
  },
};

function Matrix({
  rows,
  dims,
  refs,
}: {
  rows: EvidenceRow[];
  dims: string[];
  refs: Map<string, number>;
}) {
  const { open } = useEvidence();
  if (!rows.length || !dims.length) return null;
  return (
    <div className="sr-tw">
      <table>
        <caption>
          Table 2. Evidence matrix — every study against every required axis. A filled cell
          is a gate-verified finding; click any value for its exact source passage.
        </caption>
        <thead>
          <tr>
            <th>Study</th>
            {dims.map((d) => (
              <th key={d}>{d}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.doc_id}>
              <td>
                {(r.title || "untitled").slice(0, 70)}
                {refs.get(r.doc_id) ? <sup className="sr-refn"> {refs.get(r.doc_id)}</sup> : null}
              </td>
              {dims.map((d) => {
                const cell = r.cells?.[d];
                const found = (r.findings ?? []).filter((f) => f.dimension === d);
                if (found.length) {
                  return (
                    <td key={d}>
                      {found.slice(0, 2).map((f, i) => (
                        <div key={i} className="sr-cellv">
                          {f.value ? <span className="sr-val">{f.value}</span> : null}{" "}
                          <button className="sr-cellbtn" onClick={() => f.claim_id && open(f.claim_id)}>
                            {f.text}
                          </button>
                        </div>
                      ))}
                    </td>
                  );
                }
                const label = CELL_LABEL[cell?.state ?? "extraction_uncertain"];
                return (
                  <td key={d}>
                    <span className={label.cls} title={label.title}>
                      {label.text}
                    </span>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── verification appendix ───────────────────────────────────────────────
const REASON_COPY: Record<string, string> = {
  quote_mismatch:
    "The quoted span is not present verbatim in the cited passage — usually a paraphrase written inside quotation marks.",
  missing_chunk: "The cited passage does not exist in the corpus.",
  unsupported_entity:
    "The statement names a specific system, standard or dataset that the cited passage never mentions.",
  nli_contradiction: "The cited passage contradicts the statement.",
  nli_weak: "The cited passage does not entail the statement — it is about something adjacent.",
};

function Verification({ report }: { report: Report }) {
  const refused = report.confidence.refused_claims ?? [];
  const reasons = report.confidence.refusal_reasons ?? {};
  const verified = report.confidence.funnel?.claims_verified ?? 0;
  const recorded = report.confidence.refusal_reasons !== undefined;
  const total = Object.values(reasons).reduce((a, b) => a + b, 0);
  if (!total && !verified) return null;
  const checked = verified + total;
  const pct = checked ? Math.round((total / checked) * 100) : 0;

  // Older reports carry no refusal record. Say so, rather than rendering a
  // gate-results table whose zeros would read as "nothing was rejected".
  if (!recorded) {
    return (
      <section className="sr-sec">
        <h2>Verification appendix</h2>
        <p>
          Every one of the {verified} statements above passed the entailment gate against its
          cited span — that is what put it in the body.
        </p>
        <div className="sr-note">
          <p>
            <b>What the gate rejected was not recorded for this report.</b> Refusal capture was
            added after this run, so the statements it withheld exist only as the counts in the
            methods figures. That is an absence of record, not an absence of refusals: re-run
            this question to get the full appendix.
          </p>
        </div>
      </section>
    );
  }

  const byStage = refused.reduce<Record<string, RefusedClaim[]>>((acc, r) => {
    (acc[r.stage] ??= []).push(r);
    return acc;
  }, {});

  return (
    <section className="sr-sec">
      <h2>Verification appendix</h2>
      <p>
        Every statement above was paired with the verbatim span it was drawn from, and both were
        passed to the entailment gate — premise = source span, hypothesis = the sentence as
        written. Only entailed statements appear in the report body. This section lists what was
        withheld, rather than reducing it to a count.
      </p>

      <div className="sr-vf">
        <div className="sr-vf-h">Gate results · {checked} statements checked</div>
        <div className="sr-vf-b">
          <div className="sr-tw">
            <table style={{ minWidth: 420 }}>
              <thead>
                <tr>
                  <th>Outcome</th>
                  <th>n</th>
                  <th>Detail</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>Entailed — published</td>
                  <td className="sr-n">{verified}</td>
                  <td>Every sentence in the body above</td>
                </tr>
                <tr>
                  <td>Refused — withheld</td>
                  <td className="sr-n">{total}</td>
                  <td>
                    {Object.entries(reasons)
                      .sort((a, b) => b[1] - a[1])
                      .map(([k, v]) => `${v} ${k.replace(/_/g, " ")}`)
                      .join(" · ")}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          {checked ? (
            <p className="sr-vf-note">
              <b>{pct}% of extracted statements failed.</b> Each one reads plausibly and cites a
              real source in this corpus. In a pipeline without this layer, all {checked} would
              have been published.
            </p>
          ) : null}
        </div>
      </div>

      {refused.length ? (
        <>
          <h3>What the gate caught</h3>
          <p className="sr-dimp">
            Showing {refused.length} of {total} refusals, with the passage each was checked
            against.
          </p>
          {Object.entries(byStage).map(([stage, items]) => (
            <div key={stage}>
              <h4>{stage}</h4>
              {items.map((r, i) => (
                <div className="sr-rej" key={i}>
                  <p className="sr-was">
                    <span className="sr-badge b-fail">
                      {r.nli_label && r.nli_score
                        ? `${r.nli_label} ${r.nli_score.toFixed(3)}`
                        : r.reason.replace(/_/g, " ")}
                    </span>
                    &nbsp;“{r.text}”
                  </p>
                  {r.source_span ? <p className="sr-src">SOURCE: “{r.source_span}”</p> : null}
                  <p className="sr-why">
                    <b>{r.reason.replace(/_/g, " ")}.</b>{" "}
                    {REASON_COPY[r.reason] ?? "The statement was not supported by its cited span."}
                    {r.section ? <span className="sr-dim"> · {r.section}</span> : null}
                  </p>
                </div>
              ))}
            </div>
          ))}
          <div className="sr-note">
            <p>
              <b>How to read this section.</b> A refusal is not proof the statement is false — it
              is proof the cited span does not establish it. The failure mode this layer removes
              is invisible to a citation check, because in every case above the citation is
              correct.
            </p>
            <p>
              The entailment scores are shown because the gate measured them. They are not a
              quality score for the finding: entailment says a sentence is faithful to its
              source, which is a different question from how well established the finding is.
            </p>
          </div>
        </>
      ) : null}
    </section>
  );
}

// ── the document ────────────────────────────────────────────────────────
// ── where the studies disagree ───────────────────────────────────────────
//
// This is the section the pipeline has always been able to write and never
// showed. `synthesis.py` pairs findings that measure THE SAME THING (same
// dimension, metric, dataset, task and unit — anything less is not a
// comparison), flags a gap above the threshold as a contradiction candidate,
// and then checks whether the studies recorded different baselines, models or
// conditions. If they did, the disagreement is explained; if they did not, it
// is a real tension in the literature.
//
// It matters because the alternative is what every other tool does: put both
// numbers in a table and let the reader assume they are comparable. Two studies
// reporting 89.2 are not corroboration when one is F1 on HotpotQA and the other
// Recall@10 on MuSiQue — and no citation check catches that, because both
// numbers are real and correctly quoted. The error would live in the
// aggregation, which is precisely where nobody looks.

function Disagreements({ synthesis }: { synthesis?: Synthesis }) {
  const { open } = useEvidence();
  const all = useMemo(() => {
    const rows = (synthesis?.dimensions ?? []).flatMap((d) => d.contradictions ?? []);
    // Genuine tensions first: an unexplained disagreement is the one a reader
    // has to resolve themselves, so it should never sit below the explained ones.
    return [...rows].sort((a, b) =>
      Number(a.explained) - Number(b.explained) || b.relative_gap - a.relative_gap);
  }, [synthesis]);

  if (!all.length) return null;
  const unexplained = all.filter((c) => !c.explained).length;

  return (
    <section className="sr-sec">
      <h2>Where the studies disagree</h2>
      <p>
        {all.length} pair{all.length === 1 ? "" : "s"} of findings measure the same
        thing and report different numbers
        {unexplained
          ? `, ${unexplained} of which the studies' own recorded conditions do not explain`
          : ", all of which are explained by conditions the studies recorded"}
        . Only findings sharing a metric, dataset, task and unit are compared — two
        numbers measured differently are not a disagreement.
      </p>

      {all.map((c, i) => (
        <div className={c.explained ? "sr-dis explained" : "sr-dis"} key={i}>
          <div className="sr-dis-h">
            <span className="sr-dis-dim">{c.dimension}</span>
            <span className={c.explained ? "sr-badge b-warn" : "sr-badge b-fail"}>
              {c.explained ? "explained by conditions" : "unresolved tension"}
            </span>
            <span className="sr-dis-gap">
              {Math.round(c.relative_gap * 100)}% apart
            </span>
          </div>

          <div className="sr-dis-pair">
            <button className="sr-dis-side" onClick={() => c.a_claim_id && open(c.a_claim_id)}>
              <span className="v">{c.a_value}</span>
              <span className="s">{c.a_study}</span>
              {c.a_context ? <span className="ctx">{c.a_context}</span> : null}
            </button>
            <span className="sr-dis-vs">vs</span>
            <button className="sr-dis-side" onClick={() => c.b_claim_id && open(c.b_claim_id)}>
              <span className="v">{c.b_value}</span>
              <span className="s">{c.b_study}</span>
              {c.b_context ? <span className="ctx">{c.b_context}</span> : null}
            </button>
          </div>

          <p className="sr-dis-why">
            {c.metric || c.dataset || c.task ? (
              <>
                Both measured{" "}
                <b>{[c.metric, c.unit].filter(Boolean).join(" ") || "the same quantity"}</b>
                {c.dataset ? <> on <b>{c.dataset}</b></> : null}
                {c.task ? <> for <b>{c.task}</b></> : null}.{" "}
              </>
            ) : null}
            {c.explained ? (
              <>
                The studies differ in{" "}
                <b>{c.moderators.join(", ")}</b>, which can account for the gap without
                either being wrong.
              </>
            ) : (
              <>
                Nothing in what either study recorded accounts for the gap — treat this
                as an open question, not a settled number.
              </>
            )}
          </p>
        </div>
      ))}
    </section>
  );
}

// ── how well established each axis is ────────────────────────────────────
// Strength is a COUNT OF STUDIES, never a score, and never the entailment
// number: entailment says a sentence is faithful to its source, which is a
// different question from how well established a finding is. Every row carries
// the counts that produced its label.

const STATE_LABEL: Record<string, { text: string; cls: string }> = {
  strongly_supported: { text: "well established", cls: "b-pass" },
  moderately_supported: { text: "moderately supported", cls: "b-pass" },
  emerging: { text: "emerging", cls: "b-warn" },
  contested: { text: "contested", cls: "b-fail" },
  insufficient_evidence: { text: "too little evidence", cls: "b-warn" },
  unknown: { text: "unclassified", cls: "b-warn" },
};

// PHASE 3 — the synthesis, as sentences.
//
// These are D statements: computed from the study counts by template, with no
// LLM in the path. They are rendered as prose because that is what they are —
// readable claims about the BODY of evidence — but deliberately WITHOUT
// footnotes, because a citation to one paper would misrepresent a sentence
// derived from many. The provenance affordance is the row-set instead.
function DerivedProse({
  statements, onRows,
}: {
  statements?: DerivedStatement[];
  onRows?: (dimension: string, docIds: string[]) => void;
}) {
  const byDim = useMemo(() => {
    const out = new Map<string, DerivedStatement[]>();
    for (const s of statements ?? []) {
      const list = out.get(s.dimension) ?? [];
      list.push(s);
      out.set(s.dimension, list);
    }
    return [...out.entries()];
  }, [statements]);

  if (!byDim.length) return null;
  return (
    <section className="sr-sec">
      <h2>What the body of evidence supports</h2>
      <p className="sr-subq">
        Every sentence below is computed from the study counts in the matrix and
        reproducible by recomputation — not quoted from a paper, and not written
        by a model.
      </p>
      {byDim.map(([dimension, items]) => (
        <p className="sr-derived" key={dimension}>
          {items.map((s, i) => (
            // Answer-level sentences (the pooled number, the direction) carry
            // the reader's attention; the corpus-level caveats that qualify
            // them are set quieter rather than cut, because a pooled range
            // without its comparability caveat is the overclaim this system
            // exists to avoid.
            <span key={i}
                  className={s.kind === "direction" || s.kind === "pooled"
                    ? "sr-d-answer" : "sr-d-meta"}>
              {s.text}{" "}
            </span>
          ))}
          <button
            className="sr-derived-rows"
            onClick={() => onRows?.(dimension, items[0]?.doc_ids ?? [])}
            title="Show the studies this was computed from"
          >
            {items[0]?.doc_ids.length ?? 0} studies
          </button>
        </p>
      ))}
    </section>
  );
}

// ── S3: the comparison tables ─────────────────────────────────────────────
//
// The system-indexed view a researcher actually reasons with. One table per
// MEASUREMENT CONTEXT rather than one grid of systems x dimensions, because a
// single grid's columns invite comparing F1-on-HotpotQA against
// Recall@10-on-MuSiQue and no gate would catch it — both numbers are real.
//
// Two things are rendered that a normal comparison table omits, and both are
// the point: the number of STUDIES behind each row, and whether any study
// measured more than one of these systems itself. A table where every system
// comes from a different paper is a juxtaposition, not a comparison, and it is
// labelled as one.

const MAX_TABLES = 6;

function fmtNum(n: number): string {
  if (Number.isInteger(n)) return String(n);
  return String(Number(n.toPrecision(4)));
}

function fmtValue(row: ComparisonRow, unit: string, signed: boolean): string {
  const u = unit && unit !== "%" && unit !== "pp" ? ` ${unit}` : unit || "";
  // In a DELTA table the sign is the finding: "+3.1" and "-0.35" are an
  // improvement and a regression, and dropping the plus makes a table of
  // changes read as a table of scores.
  const n = (v: number) => `${signed && v > 0 ? "+" : ""}${fmtNum(v)}${u}`;
  if (row.min === row.max) return n(row.min);
  return `${n(row.min)} – ${n(row.max)}`;
}

function ComparisonTables({ comparisons }: { comparisons?: ComparisonTable[] }) {
  const { open } = useEvidence();
  const tables = comparisons ?? [];
  if (!tables.length) return null;
  const shown = tables.slice(0, MAX_TABLES);
  const omitted = tables.length - shown.length;

  return (
    <section className="sr-sec">
      <h2>Systems compared</h2>
      <p className="sr-subq">
        One table per measurement context. Every number inside a table shares the
        same metric, dataset, task and unit — which is what makes the rows
        comparable at all. Numbers are never pooled across contexts.
      </p>

      {shown.map((t, i) => {
        const context = [t.metric, t.dataset, t.task].filter(Boolean).join(" · ");
        return (
          <div className="sr-cmp" key={i}>
            <div className="sr-cmp-h">
              <b>
                {t.signed ? "Change in " : ""}
                {context || t.dimension}
              </b>
              {/* The strength of the comparison, not of the evidence: whether
                  anyone actually ran these systems side by side. */}
              {t.within_study === 0 ? (
                <span className="sr-cmp-tag is-weak">
                  no study measured more than one of these — juxtaposed, not compared
                </span>
              ) : (
                <span className="sr-cmp-tag">
                  {t.within_study} of {t.studies}{" "}
                  {t.studies === 1 ? "study" : "studies"} measured two or more of
                  these directly
                </span>
              )}
            </div>
            <div className="sr-tw">
              <table>
                <thead>
                  <tr>
                    <th>System</th>
                    <th>{t.signed ? "Reported change" : "Reported value"}</th>
                    <th>Studies</th>
                    <th>Source</th>
                  </tr>
                </thead>
                <tbody>
                  {t.rows.map((row) => (
                    <tr key={row.key}>
                      <td>
                        {row.system}
                        {row.aliases.length > 1 ? (
                          <span className="sr-cmp-alias"
                                title={`Spellings folded into this row: ${row.aliases.join(", ")}`}>
                            {row.aliases.length} spellings
                          </span>
                        ) : null}
                      </td>
                      <td className="sr-n">{fmtValue(row, t.unit, t.signed)}</td>
                      <td className="sr-n">{row.studies}</td>
                      <td>
                        {/* Every cell stays click-to-source: one control per
                            underlying claim, never a single link standing in
                            for several studies. */}
                        {row.claim_ids.map((id, n) => (
                          <button className="sr-cmp-src" key={id}
                                  onClick={() => open(id)}
                                  title="Open the verified span behind this number">
                            {n + 1}
                          </button>
                        ))}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        );
      })}

      {/* Tables are ordered by how many studies ran these systems side by side,
          so what is dropped is the WEAKEST comparison, not merely the smallest
          — say which, or the reader assumes the stronger thing. */}
      {omitted > 0 ? (
        <p className="sr-cmp-more">
          {omitted} further measurement {omitted === 1 ? "context" : "contexts"}{" "}
          {omitted === 1 ? "is" : "are"} not shown — fewer studies measured these
          systems against each other there.
        </p>
      ) : null}
    </section>
  );
}

function EvidenceStrength({ synthesis }: { synthesis?: Synthesis }) {
  const dims = synthesis?.dimensions ?? [];
  if (!dims.length) return null;
  return (
    <section className="sr-sec">
      <h2>How well established each axis is</h2>
      <p>
        Derived from how many independent studies report each axis and how
        comparably they measured it — not from any model confidence score.
      </p>
      <div className="sr-tw">
        <table>
          <thead>
            <tr>
              <th>Axis</th><th>Standing</th><th>Studies</th><th>On what basis</th>
            </tr>
          </thead>
          <tbody>
            {dims.map((d) => {
              const label = STATE_LABEL[d.state] ?? STATE_LABEL.unknown;
              return (
                <tr key={d.dimension}>
                  <td>{d.dimension}</td>
                  <td><span className={`sr-badge ${label.cls}`}>{label.text}</span></td>
                  <td className="sr-n">{d.studies}</td>
                  <td>{d.basis}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

//
// TWO SURFACES, ONE REPORT. Everything below the fold used to be one scroll:
// flow diagram, screening criteria, extraction instructions and a page of
// refusals sat between the reader and the findings. That apparatus is the
// product's credibility and it is *not* the lede — a researcher opening a
// review wants the answer and the evidence, and wants the method available,
// not imposed. So the document splits: READ carries the argument, METHOD
// carries everything a reviewer needs to reproduce or challenge it. Nothing is
// hidden: the counts stay visible in the strip under the title, and each is a
// link into the method.

type Surface = "read" | "method";

/** Corpus at a glance — the numbers that change how much weight a finding
 *  bears, stated before any finding. Leads with the study count on purpose: a
 *  review built on five papers should say so above the fold. */
function AtAGlance({
  report, studies, onMethod,
}: { report: Report; studies: number; onMethod: () => void }) {
  const c = report.confidence;
  const ladder = c.funnel?.ladder ?? {};
  const sc = c.study_characteristics;
  // Full text among the INCLUDED studies, not among everything ingested.
  // ladder.full_text_available counts papers that reached the corpus (14),
  // which sat next to the study count (5) and read as "14 of 5" — a number
  // that cannot be true. The reader is being told how much of THIS review's
  // evidence was read in full, so it must share the same denominator.
  const rows = c.evidence_matrix ?? [];
  const fullText = rows.length
    ? rows.filter((r) => (r as { full_text?: boolean }).full_text !== false).length
    : null;
  const span = sc?.year_span;
  const discovered = ladder.discovered ?? c.funnel?.found ?? 0;
  const thin = studies > 0 && studies < 8;

  return (
    <div className="sr-glance">
      <div className="sr-glance-row">
        <span className={thin ? "sr-stat thin" : "sr-stat"}>
          <b>{studies}</b> {studies === 1 ? "study" : "studies"}
        </span>
        {typeof fullText === "number" ? (
          <span className="sr-stat">
            <b>{fullText}/{studies}</b> read in full text
          </span>
        ) : null}
        {span ? (
          <span className="sr-stat"><b>{span.min}–{span.max}</b> publication span</span>
        ) : null}
        {discovered ? <span className="sr-stat"><b>{discovered}</b> screened</span> : null}
        <button className="sr-glance-link" onClick={onMethod}>
          How these were chosen →
        </button>
      </div>
      {thin ? (
        <p className="sr-thin-note">
          This is a small evidence base. The findings below describe these {studies}{" "}
          studies — they are not a survey of the field, and one further paper could move
          any conclusion here.
        </p>
      ) : null}
    </div>
  );
}

export function SystematicReview({ report }: { report: Report }) {
  const c = report.confidence;
  const [surface, setSurface] = useState<Surface>("read");
  const { order, num } = useRefs(report);
  const matrix = c.evidence_matrix ?? [];
  const schema = c.evidence_schema;
  const criteria = schema?.screening_criteria ?? [];
  const columns = [
    ...(schema?.required_dimensions ?? []),
    ...(schema?.optional_dimensions ?? []),
  ].filter((d) => d.extraction_instruction);
  const dims = c.funnel?.required_dimensions ?? [];
  const refsByDoc = useMemo(() => {
    const m = new Map<string, Report["references"][number]>();
    for (const r of report.references) m.set(r.document_id, r);
    return m;
  }, [report.references]);

  const abstract = c.abstract;
  // The QUESTION, in the researcher's own words. `title` is generated and
  // `plan.objective` is a purpose statement ("To understand the interplay
  // between…") — neither is what was asked, and a review is titled by its
  // question.
  const question = report.question || report.title || c.plan?.objective || "";
  const gaps = c.synthesis?.gaps ?? [];
  const refusedTotal = Object.values(c.refusal_reasons ?? {}).reduce((a, b) => a + b, 0);

  return (
    <article className="sr-page">
      {/* "verified against sources" was exactly true only while EVERY sentence
          was quote-verified. It stops being true the moment a derived sentence
          ships, so the kicker states the report's composition instead — a claim
          the reader can check against the page rather than take on trust. */}
      <p className="sr-kicker">
        Systematic review ·{" "}
        {c.composition
          ? `${c.composition.verified} verified · ${c.composition.derived} derived`
          : "verified against sources"}{" "}
        ·{" "}
        {new Date(report.created_at).toLocaleDateString(undefined, {
          day: "numeric", month: "long", year: "numeric",
        })}
      </p>

      <h1>{question}</h1>

      {abstract?.verdict ? (
        <p className="sr-tldr">
          {abstract.verdict.text}
          <Cite n={1} score={abstract.verdict.nli_score} />
        </p>
      ) : null}

      <AtAGlance report={report} studies={matrix.length} onMethod={() => setSurface("method")} />

      <div className="sr-tabs" role="tablist">
        <button
          role="tab"
          aria-selected={surface === "read"}
          className={surface === "read" ? "on" : ""}
          onClick={() => setSurface("read")}
        >
          The review
        </button>
        <button
          role="tab"
          aria-selected={surface === "method"}
          className={surface === "method" ? "on" : ""}
          onClick={() => setSurface("method")}
        >
          Method &amp; audit
          {refusedTotal ? <span className="sr-tab-n">{refusedTotal}</span> : null}
        </button>
      </div>

      {surface === "read" ? (
        <>
          {abstract?.sentences?.length ? (
            <section className="sr-sec">
              <h2>Summary</h2>
              <p>
                {abstract.sentences.map((s, i) => (
                  <span key={i}>
                    {s.text}
                    <Cite n={num.get(s.chunk_id) ?? i + 1} score={s.nli_score} />{" "}
                  </span>
                ))}
              </p>
            </section>
          ) : null}

          {/* Below the summary on purpose: the findings are the entrance; a
              spoken briefing is an alternative way in, and putting it first
              made a verification tool look like a podcast app. */}
          <ReadAloud report={report} />

          {report.sections.map((s, i) => (
            <section className="sr-sec" key={i} id={"sec-" + i}>
              <h2>{s.heading}</h2>
              {s.sub_question ? <p className="sr-subq">{s.sub_question}</p> : null}
              {s.status === "gap" ? (
                s.gap_kind === "drafting_failed" ? (
                  // OUR failure, not the corpus's. Rendering this in the
                  // "no verifiable evidence" slot told readers the literature
                  // was silent when a provider had timed out mid-write.
                  <p className="sr-gap sr-gap-fail">
                    <b>Veriscope could not draft this section.</b> {s.gap_note}
                  </p>
                ) : (
                  <p className="sr-gap">
                    <b>No verifiable evidence for this question.</b> {s.gap_note}
                  </p>
                )
              ) : (
                <p>
                  {(s.claims ?? []).map((cl, j) => {
                    const doc = cl.evidence?.[0]?.document?.id;
                    return (
                      <span key={j}>
                        {cl.text}
                        <Cite
                          n={doc ? num.get(doc) ?? j + 1 : j + 1}
                          score={cl.evidence?.[0]?.nli_score}
                          claimId={cl.claim_id}
                        />{" "}
                      </span>
                    );
                  })}
                </p>
              )}
            </section>
          ))}

          {/* The synthesis as PROSE first, the strength table after it as the
              apparatus behind those sentences — the numbers were always the
              product, but a table made them read as furniture. */}
          <DerivedProse statements={c.derived_statements} />
          {/* Prose states the answer; the tables are that answer's detail, so
              they follow immediately rather than sitting below the apparatus. */}
          <ComparisonTables comparisons={c.synthesis?.comparisons} />
          <Disagreements synthesis={c.synthesis} />
          <EvidenceStrength synthesis={c.synthesis} />

          <section className="sr-sec">
            <h2>The studies</h2>
            <StudyTable rows={matrix} refs={num} />
          </section>

          {gaps.length ? (
            <section className="sr-sec">
              <h2>What this review does not establish</h2>
              <p>
                Each gap is derived from the study counts in the matrix, so it describes
                THESE papers — not the field.
              </p>
              <ul>
                {gaps.slice(0, 6).map((g, i) => (
                  <li key={i}><b>{g.dimension}</b> — {g.basis}</li>
                ))}
              </ul>
            </section>
          ) : null}

          {order.length ? (
            <section className="sr-sec">
              <h2>References</h2>
              <ol className="sr-refs">
                {order.map((docId) => {
                  const ref = refsByDoc.get(docId);
                  const row = matrix.find((m) => m.doc_id === docId);
                  const finding = row?.findings?.[0];
                  const title = ref?.title ?? row?.title ?? "untitled";
                  return (
                    <li key={docId}>
                      {ref?.authors?.length ? ref.authors.slice(0, 6).join(", ") + " " : ""}
                      {ref?.year ? "(" + ref.year + ") " : ""}
                      {title}.
                      {ref?.url ? (
                        <> <a href={ref.url} target="_blank" rel="noreferrer">open</a></>
                      ) : null}
                      {ref?.abstract_only ? (
                        <> <span className="sr-badge b-warn">abstract only</span></>
                      ) : null}
                      {finding?.quote ? <span className="sr-q">“{finding.quote}”</span> : null}
                    </li>
                  );
                })}
              </ol>
            </section>
          ) : null}
        </>
      ) : (
        <>
          <p className="sr-method-intro">
            How this review was produced: what was searched, what was let in, what was
            extracted from each paper, and what the verification gate refused. Every
            number here is a real tally.
          </p>

          <section className="sr-sec">
            <h2>Flow</h2>
            <Flow report={report} />
          </section>

          {criteria.length ? (
            <section className="sr-sec">
              <h2>Screening</h2>
              <p>
                Candidates were screened on titles and abstracts against the criteria
                below, considered together as one holistic judgement. These are the
                criteria the screen was given — not a description of them.
              </p>
              <ul>
                {criteria.map((cr) => (
                  <li key={cr.name}><b>{cr.name}</b>: {cr.question}</li>
                ))}
              </ul>
              {c.funnel?.screen_excluded_by_criterion &&
              Object.keys(c.funnel.screen_excluded_by_criterion).length ? (
                <p>
                  Papers excluded, by the criterion they failed:{" "}
                  {Object.entries(c.funnel.screen_excluded_by_criterion)
                    .sort((a, b) => b[1] - a[1])
                    .map(([k, v]) => k + ": n = " + v)
                    .join("; ")}
                  .
                </p>
              ) : null}
            </section>
          ) : null}

          {columns.length ? (
            <section className="sr-sec">
              <h2>Data extraction</h2>
              <p>
                Each paper was read on its own terms and its results extracted into the
                columns below. The instruction shown is the instruction the extractor
                received.
              </p>
              {columns.map((col) => (
                <div key={col.name}>
                  <h4 className="sr-col">{col.name}</h4>
                  <p>{col.extraction_instruction}</p>
                </div>
              ))}
              <h4 className="sr-col">
                Grounding span{" "}
                <span className="sr-dim">(added — not part of the Elicit method)</span>
              </h4>
              <p>
                For every extracted statement, copy the verbatim sentence from the paper
                that supports it, character for character. The statement and this span
                form a premise–hypothesis pair checked by an NLI model before the
                statement may appear in the report.
              </p>
            </section>
          ) : null}

          {dims.length ? (
            <section className="sr-sec">
              <h2>Evidence matrix</h2>
              <Matrix rows={matrix} dims={dims} refs={num} />
            </section>
          ) : null}

          <Verification report={report} />
        </>
      )}

      <footer className="sr-foot">
        {c.funnel?.ladder?.discovered ?? c.funnel?.found ?? 0} records screened ·{" "}
        {matrix.length} studies included · {c.funnel?.claims_verified ?? 0} statements
        verified against their source
        {refusedTotal ? " · " + refusedTotal + " withheld by the gate" : ""}. Superscript
        numbers are references; the value beside them is the measured entailment of that
        sentence against its cited span.
      </footer>
    </article>
  );
}
