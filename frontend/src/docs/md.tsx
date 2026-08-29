// A small, dependency-free Markdown renderer for the documentation screen.
//
// Why not a library: the docs ship inside the app bundle, and the block set we
// actually use is small and closed (headings, prose, lists, tables, code,
// callouts, diagrams). A 40-line parser we own keeps the bundle flat and lets
// the renderer emit our own design-system classes instead of fighting a
// third-party theme. It also gives search a clean plain-text projection of
// every page for free — see `plainText()` below.
//
// Supported block syntax:
//   ## / ### / ####   headings (auto-slugged, anchor-linked, feed the page TOC)
//   - / 1.            lists
//   | a | b |         tables (second row is the --- separator)
//   ```lang           fenced code
//   ```diagram:name   renders <Diagram name="name" /> instead of code
//   > text            blockquote
//   :::note Title     callout (note | tip | warn | danger), closed with :::
//   ---               rule
// Inline: **bold**, `code`, [text](href), *em*.

import { Fragment, type ReactNode } from "react";
import { Diagram } from "./diagrams";

export type Heading = { id: string; text: string; level: 2 | 3 };

export function slug(text: string): string {
  return text
    .toLowerCase()
    .replace(/[`*_[\]()]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}

/* ── inline ─────────────────────────────────────────────────────────────── */

const INLINE = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\)|\*[^*]+\*)/g;

function inline(text: string, keyPrefix = ""): ReactNode[] {
  const out: ReactNode[] = [];
  const parts = text.split(INLINE);
  parts.forEach((part, i) => {
    if (!part) return;
    const k = `${keyPrefix}i${i}`;
    if (part.startsWith("**") && part.endsWith("**"))
      out.push(<strong key={k}>{part.slice(2, -2)}</strong>);
    else if (part.startsWith("`") && part.endsWith("`"))
      out.push(<code key={k} className="dc-code">{part.slice(1, -1)}</code>);
    else if (part.startsWith("[")) {
      const m = part.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
      if (!m) { out.push(<Fragment key={k}>{part}</Fragment>); return; }
      const [, label, href] = m;
      const external = /^https?:/.test(href);
      out.push(
        <a key={k} href={href} {...(external ? { target: "_blank", rel: "noreferrer" } : {})}>
          {label}{external ? <span className="dc-ext" aria-hidden="true">↗</span> : null}
        </a>,
      );
    } else if (part.startsWith("*") && part.endsWith("*") && part.length > 2)
      out.push(<em key={k}>{part.slice(1, -1)}</em>);
    else out.push(<Fragment key={k}>{part}</Fragment>);
  });
  return out;
}

/* ── blocks ─────────────────────────────────────────────────────────────── */

type Block =
  | { t: "h"; level: 2 | 3 | 4; text: string; id: string }
  | { t: "p"; text: string }
  | { t: "ul" | "ol"; items: string[] }
  | { t: "table"; head: string[]; rows: string[][] }
  | { t: "code"; lang: string; body: string }
  | { t: "diagram"; name: string }
  | { t: "quote"; text: string }
  | { t: "callout"; kind: string; title: string; body: string[] }
  | { t: "hr" };

const CALLOUT_KINDS = new Set(["note", "tip", "warn", "danger"]);

function parse(src: string): Block[] {
  const lines = src.replace(/\r\n/g, "\n").split("\n");
  const blocks: Block[] = [];
  let i = 0;

  const cells = (row: string) =>
    row.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());

  while (i < lines.length) {
    const line = lines[i];

    if (!line.trim()) { i++; continue; }

    // fenced code / diagram
    if (line.startsWith("```")) {
      const tag = line.slice(3).trim();
      const body: string[] = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) body.push(lines[i++]);
      i++; // closing fence
      if (tag.startsWith("diagram:")) blocks.push({ t: "diagram", name: tag.slice(8) });
      else blocks.push({ t: "code", lang: tag || "text", body: body.join("\n") });
      continue;
    }

    // callout
    if (line.startsWith(":::")) {
      const [kindRaw, ...titleWords] = line.slice(3).trim().split(" ");
      const kind = CALLOUT_KINDS.has(kindRaw) ? kindRaw : "note";
      const body: string[] = [];
      i++;
      while (i < lines.length && !lines[i].startsWith(":::")) body.push(lines[i++]);
      i++;
      blocks.push({ t: "callout", kind, title: titleWords.join(" "), body });
      continue;
    }

    // heading
    const h = line.match(/^(#{2,4})\s+(.*)$/);
    if (h) {
      const text = h[2].trim();
      blocks.push({ t: "h", level: h[1].length as 2 | 3 | 4, text, id: slug(text) });
      i++;
      continue;
    }

    if (/^---+$/.test(line.trim())) { blocks.push({ t: "hr" }); i++; continue; }

    // table — header row followed by a |---| separator
    if (line.trim().startsWith("|") && /^\s*\|[\s:|-]+\|\s*$/.test(lines[i + 1] ?? "")) {
      const head = cells(line);
      i += 2;
      const rows: string[][] = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) rows.push(cells(lines[i++]));
      blocks.push({ t: "table", head, rows });
      continue;
    }

    // lists
    if (/^\s*[-*]\s+/.test(line) || /^\s*\d+\.\s+/.test(line)) {
      const ordered = /^\s*\d+\.\s+/.test(line);
      const items: string[] = [];
      while (i < lines.length && /^\s*(?:[-*]|\d+\.)\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*(?:[-*]|\d+\.)\s+/, ""));
        i++;
        // continuation lines (indented) fold into the current item
        while (i < lines.length && /^\s{2,}\S/.test(lines[i]) && !/^\s*(?:[-*]|\d+\.)\s+/.test(lines[i])) {
          items[items.length - 1] += " " + lines[i].trim();
          i++;
        }
      }
      blocks.push({ t: ordered ? "ol" : "ul", items });
      continue;
    }

    // blockquote
    if (line.startsWith(">")) {
      const buf: string[] = [];
      while (i < lines.length && lines[i].startsWith(">")) buf.push(lines[i++].replace(/^>\s?/, ""));
      blocks.push({ t: "quote", text: buf.join(" ") });
      continue;
    }

    // paragraph
    const buf: string[] = [];
    while (
      i < lines.length && lines[i].trim() &&
      !lines[i].startsWith("```") && !lines[i].startsWith(":::") &&
      !/^#{2,4}\s/.test(lines[i]) && !lines[i].trim().startsWith("|") &&
      !/^\s*(?:[-*]|\d+\.)\s+/.test(lines[i]) && !lines[i].startsWith(">") &&
      !/^---+$/.test(lines[i].trim())
    ) buf.push(lines[i++]);
    blocks.push({ t: "p", text: buf.join(" ") });
  }

  return blocks;
}

/* ── public API ─────────────────────────────────────────────────────────── */

/** Headings a page contributes to the "On this page" rail. */
export function headings(src: string): Heading[] {
  return parse(src)
    .filter((b): b is Extract<Block, { t: "h" }> => b.t === "h" && b.level < 4)
    .map((b) => ({ id: b.id, text: b.text, level: b.level as 2 | 3 }));
}

/** Plain-text projection used to build the search index. */
export function plainText(src: string): string {
  return parse(src)
    .map((b) => {
      switch (b.t) {
        case "h": return b.text;
        case "p": case "quote": return b.text;
        case "ul": case "ol": return b.items.join(" ");
        case "table": return [...b.head, ...b.rows.flat()].join(" ");
        case "callout": return `${b.title} ${b.body.join(" ")}`;
        case "code": return b.body;
        default: return "";
      }
    })
    .join("\n")
    .replace(/[`*|>#]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/** Fold a callout's raw lines into paragraphs, split on blank lines — otherwise
 *  every wrapped source line renders as its own paragraph. */
function paragraphs(lines: string[]): string[] {
  const out: string[] = [];
  let buf: string[] = [];
  for (const line of lines) {
    if (line.trim()) buf.push(line.trim());
    else if (buf.length) { out.push(buf.join(" ")); buf = []; }
  }
  if (buf.length) out.push(buf.join(" "));
  return out;
}

export function Markdown({ source }: { source: string }) {
  const blocks = parse(source);
  return (
    <>
      {blocks.map((b, n) => {
        const key = `b${n}`;
        switch (b.t) {
          case "h": {
            const Tag = (`h${b.level}`) as "h2" | "h3" | "h4";
            return (
              <Tag key={key} id={b.id} className="dc-h">
                {inline(b.text, key)}
                <a className="dc-anchor" href={`#${b.id}`} aria-label={`Link to ${b.text}`}>#</a>
              </Tag>
            );
          }
          case "p": return <p key={key} className="dc-p">{inline(b.text, key)}</p>;
          case "ul": return <ul key={key} className="dc-list">{b.items.map((it, j) => <li key={j}>{inline(it, `${key}-${j}`)}</li>)}</ul>;
          case "ol": return <ol key={key} className="dc-list dc-list-ol">{b.items.map((it, j) => <li key={j}>{inline(it, `${key}-${j}`)}</li>)}</ol>;
          case "hr": return <hr key={key} className="dc-hr" />;
          case "quote": return <blockquote key={key} className="dc-quote">{inline(b.text, key)}</blockquote>;
          case "diagram": return <Diagram key={key} name={b.name} />;
          case "code": return (
            <div key={key} className="dc-pre">
              <div className="dc-pre-head"><span className="dc-lang">{b.lang}</span><CopyButton text={b.body} /></div>
              <pre><code>{b.body}</code></pre>
            </div>
          );
          case "callout": return (
            <aside key={key} className={`dc-callout dc-callout-${b.kind}`}>
              {b.title ? <div className="dc-callout-title">{b.title}</div> : null}
              <div className="dc-callout-body">
                {paragraphs(b.body).map((l, j) => <p key={j}>{inline(l, `${key}-${j}`)}</p>)}
              </div>
            </aside>
          );
          case "table": return (
            <div key={key} className="dc-table-wrap">
              <table className="dc-table">
                <thead><tr>{b.head.map((c, j) => <th key={j}>{inline(c, `${key}h${j}`)}</th>)}</tr></thead>
                <tbody>
                  {b.rows.map((r, j) => (
                    <tr key={j}>{r.map((c, k) => <td key={k}>{inline(c, `${key}r${j}c${k}`)}</td>)}</tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        }
      })}
    </>
  );
}

function CopyButton({ text }: { text: string }) {
  return (
    <button
      type="button"
      className="dc-copy"
      onClick={(e) => {
        void navigator.clipboard?.writeText(text);
        const el = e.currentTarget;
        el.dataset.done = "1";
        window.setTimeout(() => delete el.dataset.done, 1400);
      }}
    >
      <span className="dc-copy-idle">Copy</span>
      <span className="dc-copy-done">Copied</span>
    </button>
  );
}
