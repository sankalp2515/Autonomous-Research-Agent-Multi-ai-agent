// Documentation diagrams.
//
// These are hand-authored inline SVG rather than a rendering library on
// purpose: they use the same design tokens as the product (`--accent`,
// `--line`, `--ink-2`, the mono face for machine-verified values), they scale
// with the reading column, and they carry no runtime dependency. Every diagram
// describes something that is actually true of the code — if you change the
// graph topology or the gate, change the diagram in the same commit.
//
// Referenced from Markdown with a ```diagram:<name>``` fence.

import type { ReactNode } from "react";

/* ── primitives ─────────────────────────────────────────────────────────── */

type BoxProps = {
  x: number; y: number; w: number; h: number;
  label: string; sub?: string;
  tone?: "plain" | "accent" | "ok" | "warn" | "bad" | "muted";
  mono?: boolean;
};

const TONE: Record<string, { fill: string; stroke: string; ink: string }> = {
  plain:  { fill: "var(--surface)",     stroke: "var(--line)",      ink: "var(--ink)" },
  muted:  { fill: "var(--surface-2)",   stroke: "var(--line)",      ink: "var(--ink-2)" },
  accent: { fill: "var(--accent-tint)", stroke: "var(--accent-2)",  ink: "var(--accent-deep)" },
  ok:     { fill: "var(--ok-soft)",     stroke: "var(--ok)",        ink: "var(--ok)" },
  warn:   { fill: "var(--warn-soft)",   stroke: "var(--warn)",      ink: "var(--warn)" },
  bad:    { fill: "var(--bad-soft)",    stroke: "var(--bad)",       ink: "var(--bad)" },
};

function Box({ x, y, w, h, label, sub, tone = "plain", mono }: BoxProps) {
  const t = TONE[tone];
  const cx = x + w / 2;
  return (
    <g>
      <rect x={x} y={y} width={w} height={h} rx="8" fill={t.fill} stroke={t.stroke} strokeWidth="1" />
      <text
        x={cx} y={sub ? y + h / 2 - 4 : y + h / 2 + 4}
        textAnchor="middle" fill={t.ink}
        fontSize="12.5" fontWeight="600"
        fontFamily={mono ? "var(--mono)" : "var(--ui)"}
      >{label}</text>
      {sub ? (
        <text x={cx} y={y + h / 2 + 12} textAnchor="middle" fill="var(--ink-3)" fontSize="10.5" fontFamily="var(--ui)">
          {sub}
        </text>
      ) : null}
    </g>
  );
}

function Label({ x, y, text, anchor = "start", tone = "var(--ink-3)", size = 10.5, mono }: {
  x: number; y: number; text: string; anchor?: "start" | "middle" | "end"; tone?: string; size?: number; mono?: boolean;
}) {
  return (
    <text x={x} y={y} textAnchor={anchor} fill={tone} fontSize={size}
      fontFamily={mono ? "var(--mono)" : "var(--ui)"} letterSpacing={mono ? "0.02em" : undefined}>
      {text}
    </text>
  );
}

function Caption({ x, y, text }: { x: number; y: number; text: string }) {
  return (
    <text x={x} y={y} fill="var(--ink-3)" fontSize="10" fontFamily="var(--ui)"
      letterSpacing="0.11em" fontWeight="600">{text.toUpperCase()}</text>
  );
}

function Arrow({ x1, y1, x2, y2, dashed, tone = "var(--ink-faint)", label }: {
  x1: number; y1: number; x2: number; y2: number; dashed?: boolean; tone?: string; label?: string;
}) {
  return (
    <g>
      <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={tone} strokeWidth="1.25"
        strokeDasharray={dashed ? "4 4" : undefined} markerEnd="url(#vs-arrow)" />
      {label ? (
        <text x={(x1 + x2) / 2} y={(y1 + y2) / 2 - 6} textAnchor="middle" fill="var(--ink-3)"
          fontSize="10" fontFamily="var(--ui)">{label}</text>
      ) : null}
    </g>
  );
}

function Frame({ title, note, viewBox, height, children }: {
  title: string; note?: string; viewBox: string; height?: number; children: ReactNode;
}) {
  return (
    <figure className="dc-fig">
      <svg viewBox={viewBox} className="dc-svg" style={height ? { maxHeight: height } : undefined}
        role="img" aria-label={title}>
        <defs>
          <marker id="vs-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--ink-faint)" />
          </marker>
        </defs>
        {children}
      </svg>
      <figcaption className="dc-figcap"><span>{title}</span>{note ? <em>{note}</em> : null}</figcaption>
    </figure>
  );
}

/* ── 1. system architecture ─────────────────────────────────────────────── */

function SystemDiagram() {
  return (
    <Frame title="System architecture" note="Supabase Postgres is the system of record; Qdrant and Redis are rebuildable." viewBox="0 0 880 430">
      <Caption x={16} y={20} text="Client" />
      <Box x={16} y={32} w={196} h={54} label="React 18 + Vite" sub="hash routing · evidence rail" />
      <Box x={16} y={98} w={196} h={44} label="SSE run feed" sub="/api/status/{run_id}/stream" tone="muted" />

      <Caption x={264} y={20} text="Service" />
      <Box x={264} y={32} w={196} h={54} label="FastAPI" sub="auth · tenancy · rate limits" tone="accent" />
      <Box x={264} y={98} w={196} h={54} label="Worker" sub="atomic job claim · N replicas" tone="accent" />
      <Box x={264} y={170} w={196} h={54} label="LangGraph pipeline" sub="9 nodes · checkpointed" tone="accent" />
      <Box x={264} y={242} w={196} h={54} label="Verification gate" sub="quote-match + NLI" tone="ok" />

      <Caption x={520} y={20} text="State" />
      <Box x={520} y={32} w={172} h={54} label="Postgres" sub="durable truth" />
      <Box x={520} y={98} w={172} h={54} label="Qdrant" sub="vectors + BM25" />
      <Box x={520} y={170} w={172} h={54} label="Redis" sub="progress · cache · locks" tone="muted" />
      <Box x={520} y={242} w={172} h={54} label="Blob store" sub="local | S3" tone="muted" />

      <Caption x={732} y={20} text="External" />
      <Box x={732} y={32} w={132} h={44} label="arXiv" tone="muted" />
      <Box x={732} y={88} w={132} h={44} label="Semantic Scholar" tone="muted" />
      <Box x={732} y={144} w={132} h={44} label="CrossRef / OpenAlex" tone="muted" />
      <Box x={732} y={200} w={132} h={44} label="LLM fleet" sub="4 providers, routed" tone="muted" />
      <Box x={732} y={256} w={132} h={44} label="Local ML" sub="embed · rerank · NLI" tone="ok" />

      <Arrow x1={212} y1={59} x2={262} y2={59} />
      <Arrow x1={262} y1={120} x2={214} y2={120} dashed label="events" />
      <Arrow x1={362} y1={86} x2={362} y2={96} />
      <Arrow x1={362} y1={152} x2={362} y2={168} />
      <Arrow x1={362} y1={224} x2={362} y2={240} />
      <Arrow x1={460} y1={59} x2={518} y2={59} />
      <Arrow x1={460} y1={125} x2={518} y2={125} />
      <Arrow x1={460} y1={197} x2={518} y2={197} />
      <Arrow x1={460} y1={269} x2={518} y2={269} />
      <Arrow x1={692} y1={190} x2={730} y2={130} dashed />
      <Arrow x1={692} y1={200} x2={730} y2={222} dashed />
      <Arrow x1={692} y1={269} x2={730} y2={278} />

      <line x1={16} y1={330} x2={864} y2={330} stroke="var(--line)" strokeDasharray="3 5" />
      <Caption x={16} y={354} text="Rule of custody" />
      <Label x={16} y={374} text="Postgres = durable truth · Qdrant = vectors keyed by chunk_id (rebuildable) · Redis = disposable." size={11.5} tone="var(--ink-2)" />
      <Label x={16} y={394} text="Anything in Redis must be reconstructable from Postgres + Qdrant. Nothing renders from Redis alone." size={11.5} tone="var(--ink-2)" />
    </Frame>
  );
}

/* ── 2. pipeline topology ───────────────────────────────────────────────── */

function PipelineDiagram() {
  const nodes: Array<[string, string, BoxProps["tone"]]> = [
    ["clarify", "intent guard · sub-questions", "plain"],
    ["plan", "source-specific queries", "plain"],
    ["evidence_schema", "what the question requires", "accent"],
    ["research", "search · screen · ingest", "plain"],
    ["extract_evidence", "one StudyRecord per paper", "accent"],
    ["report_architect", "genre · sections · framing", "plain"],
    ["draft_sections", "claims + GATE", "ok"],
    ["assemble", "deterministic · no LLM", "plain"],
    ["build_graph", "edges + episodic memory", "muted"],
  ];
  return (
    <Frame title="LangGraph pipeline" note="Order is load-bearing: sourcing before drafting, requirements before reading." viewBox="0 0 880 400">
      {nodes.map(([label, sub, tone], i) => {
        const col = i % 3, row = Math.floor(i / 3);
        const x = 30 + col * 288, y = 40 + row * 100;
        return (
          <g key={label}>
            <Box x={x} y={y} w={236} h={56} label={label} sub={sub} tone={tone} mono />
            <circle cx={x + 12} cy={y + 12} r="9" fill="var(--surface-2)" stroke="var(--line)" />
            <text x={x + 12} y={y + 15.5} textAnchor="middle" fontSize="9" fontFamily="var(--mono)" fill="var(--ink-3)">{i + 1}</text>
            {col < 2 && i < nodes.length - 1 ? <Arrow x1={x + 236} y1={y + 28} x2={x + 286} y2={y + 28} /> : null}
            {col === 2 && i < nodes.length - 1 ? (
              <>
                <path d={`M ${x + 118} ${y + 56} v 22 H 148 v 22`} fill="none" stroke="var(--ink-faint)" strokeWidth="1.25" markerEnd="url(#vs-arrow)" />
              </>
            ) : null}
          </g>
        );
      })}
      <path d="M 148 296 v 34 H 640 v -34" fill="none" stroke="var(--accent-2)" strokeWidth="1.25" strokeDasharray="5 4" markerEnd="url(#vs-arrow)" />
      <Label x={394} y={326} text="bounded replan — one failing sub-question, ≤1 time" anchor="middle" tone="var(--accent)" size={11} />
      <Label x={30} y={370} text="Every node checkpoints full state, so an interrupted run resumes where it stopped." size={11.5} tone="var(--ink-2)" />
      <Label x={30} y={388} text="Budgets: run_max_wall_seconds 5400 · run_max_llm_calls 200 · section_max_regens 2 · subquestion_max_replans 1" size={11} tone="var(--ink-3)" mono />
    </Frame>
  );
}

/* ── 3. verification gate ───────────────────────────────────────────────── */

function GateDiagram() {
  return (
    <Frame title="The verification gate" note="Blocking and deterministic — it decides, it does not observe." viewBox="0 0 880 340">
      <Box x={24} y={92} w={150} h={64} label="Drafted claim" sub="text + chunk_id + quote" tone="muted" />
      <Arrow x1={174} y1={124} x2={214} y2={124} />

      <Box x={214} y={80} w={168} h={88} label="1 · Citation" sub="does the chunk exist?" />
      <Arrow x1={382} y1={124} x2={410} y2={124} />
      <Box x={410} y={80} w={168} h={88} label="2 · Quote match" sub="verbatim, char-for-char" />
      <Arrow x1={578} y1={124} x2={606} y2={124} />
      <Box x={606} y={80} w={168} h={88} label="3 · NLI entailment" sub="entailed, not just present" />

      <Arrow x1={774} y1={110} x2={820} y2={70} tone="var(--ok)" />
      <Box x={790} y={30} w={76} h={44} label="ship" tone="ok" />
      <Arrow x1={774} y1={140} x2={820} y2={196} tone="var(--bad)" />
      <Box x={790} y={188} w={76} h={44} label="drop" tone="bad" />

      <path d="M 298 168 v 44 H 690 v -44" fill="none" stroke="var(--warn)" strokeWidth="1.25" strokeDasharray="5 4" markerEnd="url(#vs-arrow)" />
      <Label x={494} y={208} text="regenerate with gate feedback, ≤2 attempts, then honest gap" anchor="middle" tone="var(--warn)" size={11} />

      <line x1={24} y1={248} x2={856} y2={248} stroke="var(--line)" strokeDasharray="3 5" />
      <Caption x={24} y={272} text="Why three layers and not one" />
      <Label x={24} y={292} text="Layer 2 alone passes a real quote lifted out of context. Layer 3 alone passes a paraphrase of a chunk that was never cited." size={11.5} tone="var(--ink-2)" />
      <Label x={24} y={310} text="A contradiction verdict always fails, regardless of score. nli_entailment_threshold 0.60 · quote_fuzzy_threshold 0.92" size={11.5} tone="var(--ink-2)" />
      <Label x={24} y={330} text="NLI is a faithfulness check, never a measure of evidence strength — that is a study count, computed elsewhere." size={11.5} tone="var(--accent)" />
    </Frame>
  );
}

/* ── 4. cell states ─────────────────────────────────────────────────────── */

function CellStatesDiagram() {
  return (
    <Frame title="Evidence-matrix cell states" note="Absence of evidence is never rendered as evidence of absence." viewBox="0 0 880 380">
      <Box x={340} y={16} w={200} h={48} label="study × required dimension" tone="muted" />
      <Arrow x1={440} y1={64} x2={440} y2={92} />
      <Box x={330} y={92} w={220} h={48} label="gate-verified finding?" />

      <Arrow x1={330} y1={116} x2={196} y2={116} tone="var(--ok)" label="yes" />
      <Box x={30} y={92} w={164} h={48} label="reported" tone="ok" mono />

      <Arrow x1={440} y1={140} x2={440} y2={168} label="no" />
      <Box x={318} y={168} w={244} h={48} label="axis applicable to this study?" />

      <Arrow x1={562} y1={192} x2={696} y2={192} />
      <Box x={696} y={168} w={164} h={48} label="not_applicable" tone="muted" mono />

      <Arrow x1={440} y1={216} x2={440} y2={244} label="yes" />
      <Box x={286} y={244} w={308} h={52} label="coverage_is_sufficient()?" sub="full text · ≥2 queries · ≥4 passages examined" tone="accent" />

      <Arrow x1={286} y1={270} x2={196} y2={270} label="yes" />
      <Box x={30} y={246} w={164} h={48} label="not_reported" tone="warn" mono />

      <Arrow x1={594} y1={270} x2={696} y2={270} label="no" tone="var(--bad)" />
      <Box x={696} y={246} w={164} h={48} label="extraction_uncertain" tone="bad" mono />

      <line x1={30} y1={320} x2={856} y2={320} stroke="var(--line)" strokeDasharray="3 5" />
      <Label x={30} y={342} text="Three states are facts about the STUDY. extraction_uncertain is a fact about VERISCOPE — we could not establish either way." size={11.5} tone="var(--ink-2)" />
      <Label x={30} y={362} text="Fill rate is not the objective: a mislabeled not_reported is worse than a correctly labeled hole." size={11.5} tone="var(--accent)" />
    </Frame>
  );
}

/* ── 5. research funnel ─────────────────────────────────────────────────── */

function FunnelDiagram() {
  const rungs = [
    ["discovered", "everything the searches returned"],
    ["screened", "ranked within each source pool, then interleaved"],
    ["eligible", "passed citation floor + year window"],
    ["ingested", "downloaded, parsed, chunked, embedded"],
    ["full_text_available", "not abstract-only, not paywalled"],
    ["extracted", "a StudyRecord was produced"],
    ["included_in_synthesis", "contributed a comparable measurement"],
    ["cited", "appears in the finished report"],
  ];
  return (
    <Frame title="The research funnel is a ladder" note="Never collapsed into one percentage — each drop-off is a different fact." viewBox="0 0 880 400">
      {rungs.map(([name, why], i) => {
        const y = 24 + i * 42;
        const w = 340 - i * 18;
        return (
          <g key={name}>
            <rect x={30} y={y} width={w} height={30} rx="6"
              fill={i === rungs.length - 1 ? "var(--accent-tint)" : "var(--surface)"}
              stroke={i === rungs.length - 1 ? "var(--accent-2)" : "var(--line)"} />
            <text x={42} y={y + 20} fontSize="11.5" fontFamily="var(--mono)" fill="var(--ink)">{name}</text>
            <Label x={390} y={y + 20} text={why} size={11.5} tone="var(--ink-2)" />
            {i < rungs.length - 1 ? (
              <line x1={36} y1={y + 30} x2={36} y2={y + 42} stroke="var(--line)" />
            ) : null}
          </g>
        );
      })}
      <line x1={30} y1={378} x2={856} y2={378} stroke="var(--line)" strokeDasharray="3 5" />
      <Label x={30} y={396} text="excluded_by_reason names why every paper left: screened out · citation floor · year window · over ingest cap · no retrievable text · abstract-only · extraction failed." size={11} tone="var(--ink-3)" />
    </Frame>
  );
}

/* ── 6. per-dimension retrieval ─────────────────────────────────────────── */

function DimensionDiagram() {
  return (
    <Frame title="Per-dimension retrieval inside one paper" note="Round-robin allocation — no axis can starve the others." viewBox="0 0 880 360">
      <Caption x={24} y={22} text="Legacy — one generic query" />
      <rect x={24} y={34} width={380} height={92} rx="8" fill="var(--surface-2)" stroke="var(--line)" />
      <Label x={40} y={58} text="objective query → top-8 of a ~63-chunk paper" size={11.5} tone="var(--ink-2)" />
      {Array.from({ length: 20 }).map((_, i) => (
        <rect key={i} x={40 + i * 17} y={72} width={13} height={20} rx="2"
          fill={i < 5 ? "var(--accent-soft)" : "var(--surface)"} stroke="var(--line)" />
      ))}
      <Label x={40} y={112} text="30 of 100 matrix cells empty while the evidence sat in the corpus" size={11} tone="var(--bad)" />

      <Caption x={452} y={22} text="Now — one search per required axis" />
      <rect x={452} y={34} width={404} height={92} rx="8" fill="var(--accent-tint)" stroke="var(--accent-2)" />
      {["latency", "accuracy", "cost", "dataset"].map((ax, r) => (
        <g key={ax}>
          <text x={468} y={62 + r * 17} fontSize="10" fontFamily="var(--mono)" fill="var(--accent-deep)">{ax}</text>
          {Array.from({ length: 14 }).map((_, i) => (
            <rect key={i} x={534 + i * 22} y={52 + r * 17} width={18} height={11} rx="2"
              fill={i % 4 === r % 4 ? "var(--accent-soft)" : "var(--surface)"} stroke="var(--line-2)" />
          ))}
        </g>
      ))}

      <Box x={24} y={158} w={200} h={52} label="BM25" sub="vocabulary + metric tokens" tone="muted" />
      <Box x={244} y={158} w={200} h={52} label="Document-scoped dense" sub="within this paper only" tone="muted" />
      <Box x={464} y={158} w={200} h={52} label="Numeric / section priors" sub="tables, results sections" tone="muted" />
      <Box x={684} y={158} w={172} h={52} label="Cross-encoder rerank" sub="relevance only" tone="muted" />
      <Arrow x1={440} y1={230} x2={440} y2={252} />
      <Box x={300} y={252} w={280} h={50} label="round-robin window allocation" sub="evidence_max_chunks_per_paper = 24" tone="accent" />

      <line x1={24} y1={322} x2={856} y2={322} stroke="var(--line)" strokeDasharray="3 5" />
      <Label x={24} y={344} text="Measured on the calibration corpus, retrieval recall on those cells goes 36.7% → 86.7%. Raising a global top_k buys more of the same badly-aimed ranking." size={11.5} tone="var(--ink-2)" />
    </Frame>
  );
}

/* ── 7. data model ──────────────────────────────────────────────────────── */

function DataModelDiagram() {
  return (
    <Frame title="Data model — the grounding chain in tables" note="Every arrow is a foreign key a reader can follow." viewBox="0 0 880 360">
      <Box x={24} y={24} w={168} h={48} label="projects" sub="workspace · RLS per user" mono />
      <Arrow x1={108} y1={72} x2={108} y2={96} />
      <Box x={24} y={96} w={168} h={48} label="documents" sub="paper | repo | blog" mono />
      <Arrow x1={108} y1={144} x2={108} y2={168} />
      <Box x={24} y={168} w={168} h={48} label="chunks" sub="page · char_start/end" mono />

      <Box x={280} y={96} w={168} h={48} label="runs" sub="plan · budgets · checkpoint" mono />
      <Arrow x1={192} y1={120} x2={278} y2={120} />
      <Arrow x1={364} y1={144} x2={364} y2={168} />
      <Box x={280} y={168} w={168} h={48} label="reports" sub="sections · confidence.plan" mono />
      <Arrow x1={364} y1={216} x2={364} y2={240} />
      <Box x={280} y={240} w={168} h={48} label="claims" sub="verified | failed | gap" tone="accent" mono />

      <Arrow x1={448} y1={264} x2={528} y2={264} />
      <Box x={528} y={240} w={196} h={48} label="claim_evidence" sub="quote · quote_match_ok · nli" tone="ok" mono />
      <Arrow x1={626} y1={240} x2={626} y2={216} />
      <Box x={528} y={168} w={196} h={48} label="citations" sub="resolver: crossref|openalex|arxiv|corpus" tone="ok" mono />
      <path d="M 528 192 H 200 v 0" fill="none" stroke="var(--ink-faint)" strokeWidth="1.25" markerEnd="url(#vs-arrow)" />

      <Box x={756} y={96} w={100} h={44} label="answers" tone="muted" mono />
      <Box x={756} y={152} w={100} h={44} label="graph_*" tone="muted" mono />
      <Box x={756} y={208} w={100} h={44} label="audit_log" tone="muted" mono />
      <Box x={756} y={264} w={100} h={44} label="feedback" tone="muted" mono />

      <line x1={24} y1={312} x2={856} y2={312} stroke="var(--line)" strokeDasharray="3 5" />
      <Label x={24} y={334} text="G2 in one sentence: the UI renders references only from resolved citation rows. A fabricated citation has no row, so it cannot render." size={11.5} tone="var(--accent)" />
    </Frame>
  );
}

/* ── 8. deployment ──────────────────────────────────────────────────────── */

function DeploymentDiagram() {
  return (
    <Frame title="Deployment topology" note="docker compose --profile app — one command, one URL." viewBox="0 0 880 300">
      <rect x={20} y={20} width={840} height={200} rx="10" fill="none" stroke="var(--line)" strokeDasharray="4 4" />
      <Caption x={34} y={44} text="docker compose · profile: app" />

      <Box x={40} y={62} w={180} h={60} label="frontend" sub="nginx · :8080 · proxies /api" tone="accent" />
      <Arrow x1={220} y1={92} x2={266} y2={92} />
      <Box x={266} y={62} w={180} h={60} label="api" sub="uvicorn · FastAPI" tone="accent" />
      <Box x={266} y={140} w={180} h={60} label="worker × N" sub="--scale worker=3" tone="accent" />

      <Box x={500} y={40} w={160} h={48} label="postgres:16" sub=":5433" />
      <Box x={500} y={100} w={160} h={48} label="redis:7" sub=":6380" />
      <Box x={500} y={160} w={160} h={48} label="qdrant v1.12" sub=":6333" />

      <Box x={700} y={62} w={144} h={60} label="models" sub="optional GPU profile" tone="muted" />

      <Arrow x1={446} y1={80} x2={498} y2={64} />
      <Arrow x1={446} y1={100} x2={498} y2={124} />
      <Arrow x1={446} y1={170} x2={498} y2={184} />
      <Arrow x1={446} y1={150} x2={498} y2={130} />
      <Arrow x1={660} y1={92} x2={698} y2={92} dashed />

      <Label x={20} y={252} text="Only the LLM keys in backend/.env are required — everything else has a working default." size={11.5} tone="var(--ink-2)" />
      <Label x={20} y={272} text="Run exactly one worker locally; in compose, job claim is atomic so replicas are safe." size={11.5} tone="var(--ink-2)" />
      <Label x={20} y={292} text="AUTH_DISABLED=true is refused at boot when APP_ENV=prod." size={11.5} tone="var(--warn)" />
    </Frame>
  );
}

/* ── 9. report anatomy ──────────────────────────────────────────────────── */

function ReportAnatomyDiagram() {
  return (
    <Frame title="Anatomy of a report" note="The audit trail is the product — but it is not the lede." viewBox="0 0 880 400">
      <rect x={24} y={20} width={560} height={356} rx="10" fill="var(--surface)" stroke="var(--line)" />
      <rect x={604} y={20} width={252} height={356} rx="10" fill="var(--surface-2)" stroke="var(--line)" />

      <Label x={620} y={44} text="PERSISTENT EVIDENCE RAIL" size={10} tone="var(--ink-3)" />
      <rect x={620} y={56} width={220} height={78} rx="6" fill="var(--surface)" stroke="var(--line)" />
      <Label x={632} y={76} text="verbatim span" size={10.5} tone="var(--ink-2)" mono />
      <rect x={632} y={84} width={180} height={12} rx="3" fill="var(--mark)" />
      <rect x={632} y={102} width={140} height={12} rx="3" fill="var(--mark)" />
      <Label x={632} y={128} text="nli 0.93 · p. 4–5 · arXiv" size={10} tone="var(--ok)" mono />
      <rect x={620} y={148} width={220} height={92} rx="6" fill="var(--surface)" stroke="var(--line)" />
      <Label x={632} y={168} text="source passage" size={10.5} tone="var(--ink-3)" />
      {[0, 1, 2, 3].map((i) => <rect key={i} x={632} y={178 + i * 14} width={196 - i * 22} height={7} rx="3" fill="var(--line-2)" />)}
      <Label x={620} y={264} text="sentence → verdict → span → passage → document" size={10} tone="var(--accent)" />
      <rect x={620} y={276} width={220} height={80} rx="6" fill="var(--surface)" stroke="var(--line)" />
      <Label x={632} y={296} text="provenance chain" size={10.5} tone="var(--ink-3)" />
      {[0, 1, 2].map((i) => (
        <g key={i}>
          <circle cx={640} cy={314 + i * 16} r="3.5" fill="var(--accent)" />
          <rect x={652} y={310 + i * 16} width={150 - i * 18} height={7} rx="3" fill="var(--line-2)" />
        </g>
      ))}

      <Label x={40} y={44} text="TITLE" size={10} tone="var(--ink-3)" />
      <rect x={40} y={52} width={300} height={16} rx="4" fill="var(--ink-faint)" />
      <rect x={40} y={78} width={528} height={40} rx="6" fill="var(--accent-tint)" stroke="var(--accent-2)" />
      <Label x={52} y={102} text="analysis plan — objective, sub-questions, section mapping" size={11} tone="var(--accent-deep)" />

      <rect x={40} y={128} width={528} height={72} rx="6" fill="var(--surface-2)" stroke="var(--line)" />
      <Label x={52} y={148} text="EVIDENCE MATRIX — studies before anyone's synthesis of them" size={10} tone="var(--ink-3)" />
      {Array.from({ length: 4 }).map((_, r) =>
        Array.from({ length: 6 }).map((__, c) => (
          <rect key={`${r}-${c}`} x={52 + c * 84} y={158 + r * 10} width={78} height={7} rx="2"
            fill={(r + c) % 5 === 0 ? "var(--surface)" : (r * c) % 3 === 0 ? "var(--ok-soft)" : "var(--accent-soft)"}
            stroke="var(--line-2)" />
        )),
      )}

      <rect x={40} y={212} width={528} height={44} rx="6" fill="var(--surface-2)" stroke="var(--line)" />
      <Label x={52} y={232} text="DOSSIER — Sample · Evidence · Gaps · Methods, in one four-face panel" size={10.5} tone="var(--ink-2)" />

      <Label x={40} y={278} text="01  SECTION" size={10} tone="var(--accent)" />
      {[0, 1].map((i) => <rect key={i} x={40} y={288 + i * 14} width={520 - i * 60} height={7} rx="3" fill="var(--line-2)" />)}
      <rect x={40} y={320} width={528} height={30} rx="6" fill="var(--accent-tint)" stroke="var(--accent-2)" />
      <Label x={52} y={340} text="metric callout — a quantity with NLI ≥ 0.85, pulled out of the prose" size={10.5} tone="var(--accent-deep)" />
      <Label x={40} y={366} text="Works Cited — numbered in citation order, each with its grounding span" size={10.5} tone="var(--ink-3)" />
    </Frame>
  );
}

/* ── registry ───────────────────────────────────────────────────────────── */

const REGISTRY: Record<string, () => JSX.Element> = {
  system: SystemDiagram,
  pipeline: PipelineDiagram,
  gate: GateDiagram,
  "cell-states": CellStatesDiagram,
  funnel: FunnelDiagram,
  dimension: DimensionDiagram,
  "data-model": DataModelDiagram,
  deployment: DeploymentDiagram,
  "report-anatomy": ReportAnatomyDiagram,
};

export function Diagram({ name }: { name: string }) {
  const D = REGISTRY[name];
  if (!D) return null;
  return <D />;
}
