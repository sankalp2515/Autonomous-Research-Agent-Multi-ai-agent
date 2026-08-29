// Documentation search.
//
// Everything ships in the bundle, so search is local, instant and works
// offline — no index server, no network round-trip, no API key. The corpus is
// small (a few dozen pages), so a scored linear scan is both fast enough and
// far easier to reason about than an inverted index we would have to keep in
// sync with the content.
//
// Scoring is deliberately simple and explainable: a term matched in a title
// outranks the same term matched in a heading, which outranks body text. All
// query terms must appear somewhere in the page, so a two-word query narrows
// rather than widens.

import { PAGES, type ResolvedPage } from "./content";

export type SearchHit = {
  page: ResolvedPage;
  score: number;
  /** Deepest heading that matched, for a direct anchor link. */
  anchor: { id: string; text: string } | null;
  /** Body excerpt around the first match, with `mark` offsets already applied. */
  snippet: { text: string; ranges: Array<[number, number]> } | null;
};

type Indexed = {
  page: ResolvedPage;
  title: string;
  description: string;
  keywords: string;
  group: string;
  headings: Array<{ id: string; text: string; lower: string }>;
  text: string;
  lower: string;
};

const INDEX: Indexed[] = PAGES.map((page) => ({
  page,
  title: page.title.toLowerCase(),
  description: page.description.toLowerCase(),
  keywords: (page.keywords ?? "").toLowerCase(),
  group: page.group.label.toLowerCase(),
  headings: page.headings.map((h) => ({ id: h.id, text: h.text, lower: h.text.toLowerCase() })),
  text: page.text,
  lower: page.text.toLowerCase(),
}));

const WEIGHT = { title: 60, description: 24, keywords: 20, group: 8, heading: 16, body: 1 } as const;

function terms(query: string): string[] {
  return query.toLowerCase().split(/[^a-z0-9_.]+/i).filter((t) => t.length > 1);
}

function occurrences(haystack: string, needle: string): number {
  if (!needle) return 0;
  let n = 0, i = haystack.indexOf(needle);
  while (i !== -1 && n < 50) { n++; i = haystack.indexOf(needle, i + needle.length); }
  return n;
}

export function search(query: string, limit = 12): SearchHit[] {
  const q = query.trim();
  if (q.length < 2) return [];
  const ts = terms(q);
  if (!ts.length) return [];
  const phrase = q.toLowerCase();

  const hits: SearchHit[] = [];

  for (const entry of INDEX) {
    let score = 0;
    let matchedAll = true;
    let bestHeading: { id: string; text: string } | null = null;

    for (const t of ts) {
      let termScore = 0;

      if (entry.title.includes(t)) termScore += WEIGHT.title;
      if (entry.description.includes(t)) termScore += WEIGHT.description;
      if (entry.keywords.includes(t)) termScore += WEIGHT.keywords;
      if (entry.group.includes(t)) termScore += WEIGHT.group;

      for (const h of entry.headings) {
        if (h.lower.includes(t)) {
          termScore += WEIGHT.heading;
          if (!bestHeading) bestHeading = { id: h.id, text: h.text };
        }
      }

      const bodyHits = occurrences(entry.lower, t);
      termScore += Math.min(bodyHits, 8) * WEIGHT.body;

      if (termScore === 0) { matchedAll = false; break; }
      score += termScore;
    }

    if (!matchedAll) continue;

    // exact-phrase and title-prefix bonuses, so "cell states" beats a page that
    // merely mentions both words far apart.
    if (ts.length > 1 && entry.lower.includes(phrase)) score += 40;
    if (entry.title.startsWith(ts[0])) score += 30;

    hits.push({ page: entry.page, score, anchor: bestHeading, snippet: excerpt(entry.text, ts) });
  }

  return hits.sort((a, b) => b.score - a.score || a.page.title.localeCompare(b.page.title)).slice(0, limit);
}

/** A ~150-character window around the first body match, with highlight ranges. */
function excerpt(text: string, ts: string[]): SearchHit["snippet"] {
  const lower = text.toLowerCase();
  let at = -1, hitTerm = "";
  for (const t of ts) {
    const i = lower.indexOf(t);
    if (i !== -1 && (at === -1 || i < at)) { at = i; hitTerm = t; }
  }
  if (at === -1) return null;

  const start = Math.max(0, at - 60);
  const end = Math.min(text.length, at + hitTerm.length + 110);
  let body = text.slice(start, end);
  const offset = start;

  const ranges: Array<[number, number]> = [];
  const bodyLower = body.toLowerCase();
  for (const t of ts) {
    let i = bodyLower.indexOf(t);
    while (i !== -1) { ranges.push([i, i + t.length]); i = bodyLower.indexOf(t, i + t.length); }
  }
  ranges.sort((a, b) => a[0] - b[0]);

  // merge overlaps so highlight spans never nest
  const merged: Array<[number, number]> = [];
  for (const r of ranges) {
    const last = merged[merged.length - 1];
    if (last && r[0] <= last[1]) last[1] = Math.max(last[1], r[1]);
    else merged.push([...r] as [number, number]);
  }

  const prefix = offset > 0 ? "…" : "";
  if (prefix) {
    body = prefix + body;
    for (const r of merged) { r[0] += 1; r[1] += 1; }
  }
  if (end < text.length) body += "…";

  return { text: body, ranges: merged };
}

/** Shown when the search box is open but empty. */
export const SUGGESTED = [
  "start/introduction",
  "start/install",
  "explanation/verification-gate",
  "reference/api",
  "explanation/cell-states",
];
