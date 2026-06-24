export interface Project {
  id: string;
  name: string;
  description: string;
  documents: number;
  runs: number;
  created_at: string;
}

export interface Doc {
  id: string;
  title: string;
  source_type: string;
  status: string;
  status_reason: string;
  url: string;
  year: number | null;
  authors: string[];
  abstract_only: boolean;
  full_text_available: boolean;
  created_at: string;
}

export interface Evidence {
  chunk_id: string;
  document_id: string;
  document_title: string;
  section: string;
  page_start: number;
  page_end: number;
  quote: string;
  quote_char_start: number;
  quote_char_end: number;
  nli_label: string;
  nli_score: number;
  abstract_only: boolean;
  source_type: string;
}

export interface Claim {
  id: string;
  text: string;
  evidence: Evidence;
}

export interface TechnicalHit {
  document_id: string;
  document_title: string;
  source_type: string;
  snippet: string;
}

export interface ChatResult {
  answer_id: string;
  refused: boolean;
  refusal_reason: string;
  coverage_note: string;
  claims: Claim[];
  technical_context: TechnicalHit[];
}

export interface ChatTurn {
  question: string;
  result: ChatResult | null;
  error?: string;
}

export interface Run {
  id: string;
  query: string;
  status: string;
  current_node: string;
  report_id: string | null;
  budgets_spent: { llm_calls?: number; seconds?: number };
  created_at: string;
}

export interface RunStatus {
  run_id: string;
  status: string;
  current_node: string;
  error: string;
  report_id: string | null;
  budgets_spent: { llm_calls?: number; seconds?: number };
  live: {
    node?: string;
    status?: string;
    message?: string;
    sections_done?: number;
    sections_total?: number;
    coverage_notes?: string[];
  } | null;
  events: { node: string; status: string; at: number; message?: string }[];
}

export interface EvidenceDetail {
  claim_id: string;
  text: string;
  status: string;
  evidence: {
    chunk_id: string;
    quote: string;
    quote_char_start: number;
    quote_char_end: number;
    nli_label: string;
    nli_score: number;
    chunk_text: string;
    section: string;
    pages: number[];
    document: {
      id?: string;
      title?: string;
      url?: string;
      source_type?: string;
      status: string;
      abstract_only?: boolean;
    };
  }[];
}

export interface ReportSection {
  heading: string;
  sub_question: string;
  status: string;
  gap_note: string;
  track?: string; // academic | technical
  claims: EvidenceDetail[];
}

export interface Report {
  id: string;
  title: string;
  outline: string[];
  confidence: {
    sections_verified?: number;
    sections_total?: number;
    coverage_notes?: string[];
    llm_calls?: number;
  };
  sections: ReportSection[];
  references: {
    document_id: string;
    title: string;
    url: string;
    source_type: string;
    year: number | null;
    authors: string[];
    abstract_only: boolean;
    citations?: number;
  }[];
  created_at: string;
}

export interface MapNode {
  id: string;
  title: string;
  year: number | null;
  authors: string[];
  source_type: string;
  url: string;
  arxiv_id: string | null;
  citations: number;
  abstract_only: boolean;
}
export interface MapEdge { src: string; dst: string; weight: number; kind?: string }
export interface MapData { nodes: MapNode[]; edges: MapEdge[] }

export interface ClarifyResult {
  allowed: boolean;
  reason: string;
  objective: string;
  questions: string[];
}

export interface Note {
  id: string;
  title: string;
  body: string;
  tags: string[];
  source_ref: string;
  claim_id: string | null;
  updated_at: string;
}

export interface Watch {
  id: string;
  query: string;
  active: boolean;
  last_checked: string | null;
}

export interface Alert {
  id: string;
  title: string;
  url: string;
  abstract: string;
  authors: string[];
  year: number | null;
  score: number;
  arxiv_id: string | null;
  has_pdf: boolean;
}

export interface MonitorData {
  watches: Watch[];
  alerts: Alert[];
}

export interface SavedItem {
  id: string;
  claim_id: string;
  text: string;
  note: string;
  source: string;
  page: number;
  quote: string;
  created_at: string;
}

export interface Contradiction {
  score: number;
  a: { claim_id: string; text: string; source: string; page: number };
  b: { claim_id: string; text: string; source: string; page: number };
}

export interface RefindHit {
  chunk_id: string;
  document_id: string;
  document_title: string;
  section: string;
  page_start: number;
  page_end: number;
  snippet: string;
  score: number;
  abstract_only: boolean;
}

export interface GraphData {
  nodes: { id: string; type: string; label: string }[];
  edges: { src: string; dst: string; relation: string; weight: number }[];
}
