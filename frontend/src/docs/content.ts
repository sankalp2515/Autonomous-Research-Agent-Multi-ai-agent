// The documentation registry.
//
// Page bodies are plain Markdown files under ./pages, pulled in eagerly as raw
// strings by Vite. Keeping them as .md rather than TS template literals means
// no backtick escaping in fenced code blocks, and it keeps prose reviewable as
// prose in a diff.
//
// The nav below is the single source of truth for ordering, URLs, breadcrumbs,
// prev/next, and the search index. A page that is not listed here does not
// exist as far as the app is concerned.

import { headings, plainText, type Heading } from "./md";

const RAW = import.meta.glob("./pages/*.md", { query: "?raw", import: "default", eager: true }) as Record<string, string>;

function body(file: string): string {
  const src = RAW[`./pages/${file}.md`];
  if (src === undefined) throw new Error(`docs: missing page source ./pages/${file}.md`);
  return src;
}

export type DocPage = {
  /** URL slug within its group. */
  slug: string;
  /** File basename under ./pages. */
  file: string;
  title: string;
  /** One line under the title, and the search result subtitle. */
  description: string;
  /** Extra search terms that do not appear in the prose. */
  keywords?: string;
};

export type DocGroup = {
  id: string;
  label: string;
  /** The Diátaxis quadrant this group serves, shown in the sidebar. */
  kind: string;
  pages: DocPage[];
};

export const GROUPS: DocGroup[] = [
  {
    id: "start",
    label: "Start here",
    kind: "Orientation",
    pages: [
      {
        slug: "introduction",
        file: "introduction",
        title: "Introduction",
        description: "What Veriscope is, the five guarantees, and how these docs are organised.",
        keywords: "overview about diataxis guarantees g1 g2 g3 g4 g5 verifiable",
      },
      {
        slug: "install",
        file: "install",
        title: "Install and run",
        description: "Docker in one command, or from source with the local ML stack.",
        keywords: "setup docker compose venv npm pip quickstart getting started ports",
      },
      {
        slug: "architecture",
        file: "architecture",
        title: "Architecture overview",
        description: "The custody rule, the pipeline, the gate, and the stack — in one page.",
        keywords: "system design postgres qdrant redis langgraph fastapi stack map",
      },
    ],
  },
  {
    id: "tutorials",
    label: "Tutorials",
    kind: "Learning-oriented",
    pages: [
      {
        slug: "first-report",
        file: "first-report",
        title: "Your first verified report",
        description: "End to end: create a project, run a question, and follow one claim to its source.",
        keywords: "walkthrough getting started evidence matrix rail dossier run feed",
      },
      {
        slug: "grounded-chat",
        file: "grounded-chat",
        title: "Ask questions about your corpus",
        description: "Grounded chat, provenance on every sentence, and what a refusal tells you.",
        keywords: "chat qa refusal notebook notes refind answers",
      },
    ],
  },
  {
    id: "features",
    label: "Features",
    kind: "What each surface does",
    pages: [
      {
        slug: "ask",
        file: "feat-ask",
        title: "Ask the corpus",
        description: "Grounded Q&A in three scopes — corpus, one paper, or a selection — all behind the same gate.",
        keywords: "chat grounded qa refusal guardrail pii scoped selection answers practitioner",
      },
      {
        slug: "chat-context",
        file: "feat-chat-context",
        title: "The + Chat button",
        description: "Gather papers, claims and answers from anywhere, then ask a question scoped to exactly that set.",
        keywords: "add to chat tray entity_refs selection seed chunks scope pill",
      },
      {
        slug: "screening",
        file: "feat-screening",
        title: "Screening",
        description: "See every candidate with a keep/drop reason, and approve what enters the corpus — before any download.",
        keywords: "screen candidates keep drop relevance constraints year citations human in the loop",
      },
      {
        slug: "compare",
        file: "feat-compare",
        title: "Compare papers",
        description: "Two to five corpus papers side by side, every cell a gate-verified claim.",
        keywords: "comparison matrix dimensions derive cells recommend related documents grid",
      },
      {
        slug: "map",
        file: "feat-map",
        title: "Map",
        description: "A similarity graph over your corpus — clusters, bridges and outliers you can act on.",
        keywords: "graph nodes edges clusters similarity layout neighbours force ask this paper",
      },
      {
        slug: "monitor",
        file: "feat-monitor",
        title: "Monitor",
        description: "Standing watches over arXiv and Semantic Scholar, deduped against your corpus and scored locally.",
        keywords: "watch alert new papers arxiv semantic scholar threshold dedup seed watches smtp",
      },
      {
        slug: "notebook",
        file: "feat-notebook",
        title: "Notebook",
        description: "Verified claims you have saved across the project, each keeping its quote and source.",
        keywords: "save claims findings export markdown pinned saved",
      },
      {
        slug: "notes",
        file: "feat-notes",
        title: "Notes",
        description: "Your own writing, kept beside the corpus and deliberately outside the verification path.",
        keywords: "note title body tags source_ref autosave export writing",
      },
      {
        slug: "memory",
        file: "feat-memory",
        title: "Memory",
        description: "What the project carries between sessions — orientation for planning, never evidence.",
        keywords: "episodic semantic preference recall embedding cross-session plan",
      },
    ],
  },
  {
    id: "how-to",
    label: "How-to guides",
    kind: "Task-oriented",
    pages: [
      {
        slug: "run-deep-research",
        file: "run-deep-research",
        title: "Run a deep research run",
        description: "Launch, steer sourcing, extraction, recovery and budgets; resume an interrupted run.",
        keywords: "pipeline launch sse budgets screening concurrency resume",
      },
      {
        slug: "bring-your-own-papers",
        file: "bring-your-own-papers",
        title: "Bring your own papers",
        description: "Upload PDFs, import BibTeX, and understand dedup, tombstones and retention.",
        keywords: "upload pdf bibtex import documents dedup doi arxiv retention eviction",
      },
      {
        slug: "configure-providers",
        file: "configure-providers",
        title: "Configure LLM providers",
        description: "The four-provider fleet, complexity routing, rate limits and the local ML stack.",
        keywords: "gemini groq deepseek openrouter nvidia api keys routing temperature cache",
      },
      {
        slug: "tune-retrieval",
        file: "tune-retrieval",
        title: "Tune retrieval",
        description: "Diagnose thin coverage properly, and benchmark before and after every change.",
        keywords: "recall evidence_bench extraction_ab top_k dimension coverage holes",
      },
      {
        slug: "share-and-export",
        file: "share-and-export",
        title: "Share and export a report",
        description: "Public read-only links, Markdown export, and what deliberately does not travel.",
        keywords: "share slug export markdown works cited api metrics contradictions",
      },
      {
        slug: "deploy",
        file: "deploy",
        title: "Deploy to production",
        description: "Auth, CORS, capacity, storage, observability and a pre-flight checklist.",
        keywords: "production supabase jwks cors rate limit otel sentry s3 migrations checklist",
      },
      {
        slug: "troubleshoot",
        file: "troubleshoot",
        title: "Troubleshooting",
        description: "Symptoms, causes and fixes — ordered by how often they actually happen.",
        keywords: "error 503 401 clock frozen budget exhausted uncertain refused arxiv missing",
      },
    ],
  },
  {
    id: "reference",
    label: "Reference",
    kind: "Information-oriented",
    pages: [
      {
        slug: "api",
        file: "api",
        title: "API reference",
        description: "Every endpoint, the SSE event kinds, and what each status code means here.",
        keywords: "rest http endpoints projects runs report chat sse curl status codes",
      },
      {
        slug: "pipeline-nodes",
        file: "pipeline-nodes",
        title: "Pipeline nodes",
        description: "What each of the nine graph nodes does, and which tests pin its behaviour.",
        keywords: "clarify plan evidence_schema research extract_evidence report_architect draft_sections assemble build_graph langgraph",
      },
      {
        slug: "configuration",
        file: "configuration",
        title: "Configuration",
        description: "Every environment variable, its default, and when to change it.",
        keywords: "env settings variables defaults thresholds budgets limits",
      },
      {
        slug: "data-model",
        file: "data-model",
        title: "Data model",
        description: "The tables that carry the grounding chain, retention tiers and invariants.",
        keywords: "postgres schema tables claims chunks citations claim_evidence runs reports",
      },
      {
        slug: "evals",
        file: "evals",
        title: "Evaluation",
        description: "The suites, the evidence-acquisition benchmarks, and the tests that act as spec.",
        keywords: "eval gate pytest ragas calibration golden benchmark regression",
      },
      {
        slug: "glossary",
        file: "glossary",
        title: "Glossary",
        description: "Every term used precisely, in one place.",
        keywords: "definitions terms vocabulary chunk claim citation entailment",
      },
    ],
  },
  {
    id: "explanation",
    label: "Explanation",
    kind: "Understanding-oriented",
    pages: [
      {
        slug: "grounding-contract",
        file: "grounding-contract",
        title: "The grounding contract",
        description: "The five guarantees, the design laws underneath them, and what they do not promise.",
        keywords: "trust fabrication guarantees g1 g2 design laws density prose",
      },
      {
        slug: "verification-gate",
        file: "verification-gate",
        title: "The verification gate",
        description: "Three layers, why one is not enough, and why NLI is not evidence strength.",
        keywords: "quote match entailment nli deberta thresholds regenerate refuse boot check",
      },
      {
        slug: "cell-states",
        file: "cell-states",
        title: "Absence of evidence",
        description: "Four cell states, the evidence-of-search rule, and why fill rate is not the objective.",
        keywords: "not_reported extraction_uncertain not_applicable recovery matrix holes honesty",
      },
      {
        slug: "synthesis",
        file: "synthesis",
        title: "Counting studies, not sentences",
        description: "Comparability, contradictions, evidence strength as a study count, and counted gaps.",
        keywords: "normalize aggregation corroboration contested strongly_supported basis gaps",
      },
      {
        slug: "funnel",
        file: "funnel",
        title: "The research funnel",
        description: "A ladder with named exclusions, and why it is never one percentage.",
        keywords: "discovered screened ingested extracted cited coverage sections grounded methods",
      },
      {
        slug: "retrieval-design",
        file: "retrieval-design",
        title: "Three retrieval problems",
        description: "Corpus, section and per-dimension retrieval — and why the third one exists.",
        keywords: "bm25 dense hybrid rrf rerank dimension round robin screening pools recall",
      },
      {
        slug: "design-system",
        file: "design-system",
        title: "Editorial Science",
        description: "Type roles, tokens, the evidence rail, and why the audit trail is not the lede.",
        keywords: "design tokens css spectral hanken jetbrains mono accent rail dossier motion",
      },
    ],
  },
];

/* ── derived indexes ────────────────────────────────────────────────────── */

export type ResolvedPage = DocPage & {
  group: DocGroup;
  path: string;
  source: string;
  headings: Heading[];
  text: string;
};

export const PAGES: ResolvedPage[] = GROUPS.flatMap((group) =>
  group.pages.map((page) => {
    const source = body(page.file);
    return {
      ...page,
      group,
      path: `${group.id}/${page.slug}`,
      source,
      headings: headings(source),
      text: plainText(source),
    };
  }),
);

const BY_PATH = new Map(PAGES.map((p) => [p.path, p]));

/** The page shown at bare `#/docs`. */
export const HOME_PATH = "start/introduction";

export function pageAt(path: string | null | undefined): ResolvedPage | null {
  if (!path) return BY_PATH.get(HOME_PATH) ?? null;
  return BY_PATH.get(path) ?? null;
}

export function neighbours(path: string): { prev: ResolvedPage | null; next: ResolvedPage | null } {
  const i = PAGES.findIndex((p) => p.path === path);
  if (i < 0) return { prev: null, next: null };
  return { prev: PAGES[i - 1] ?? null, next: PAGES[i + 1] ?? null };
}
