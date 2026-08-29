import { useEffect, useMemo, useRef, useState } from "react";
import { Icon, type IconName } from "./icons";

export type Command = {
  id: string;
  label: string;
  hint?: string;
  group: string;
  icon: IconName;
  run: () => void;
  keywords?: string;
};

// ⌘K — keyboard-first navigation & actions. Everything reachable without a mouse.
export default function CommandPalette({
  commands,
  onClose,
}: {
  commands: Command[];
  onClose: () => void;
}) {
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => inputRef.current?.focus(), []);

  const filtered = useMemo(() => {
    const query = q.trim().toLowerCase();
    if (!query) return commands;
    return commands.filter((c) =>
      `${c.label} ${c.hint ?? ""} ${c.group} ${c.keywords ?? ""}`.toLowerCase().includes(query)
    );
  }, [q, commands]);

  useEffect(() => setSel(0), [q]);

  const groups = useMemo(() => {
    const m = new Map<string, Command[]>();
    for (const c of filtered) {
      if (!m.has(c.group)) m.set(c.group, []);
      m.get(c.group)!.push(c);
    }
    return Array.from(m.entries());
  }, [filtered]);

  function onKey(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") { e.preventDefault(); setSel((s) => Math.min(s + 1, filtered.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setSel((s) => Math.max(s - 1, 0)); }
    else if (e.key === "Enter") { e.preventDefault(); filtered[sel]?.run(); onClose(); }
    else if (e.key === "Escape") { e.preventDefault(); onClose(); }
  }

  useEffect(() => {
    listRef.current?.querySelector(".cmdk-item.sel")?.scrollIntoView({ block: "nearest" });
  }, [sel]);

  let flat = -1;
  return (
    <div className="cmdk-veil" onMouseDown={onClose}>
      <div className="cmdk" onMouseDown={(e) => e.stopPropagation()} onKeyDown={onKey}>
        <div className="cmdk-input-row">
          <Icon.search size={17} />
          <input
            ref={inputRef}
            className="cmdk-input"
            placeholder="Jump to a view or run a command…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <span className="kbd" style={{ fontFamily: "var(--mono)", fontSize: 10.5, color: "var(--ink-3)" }}>ESC</span>
        </div>
        <div className="cmdk-list" ref={listRef}>
          {filtered.length === 0 && <div className="cmdk-empty">No matching commands.</div>}
          {groups.map(([group, cmds]) => (
            <div key={group}>
              <div className="cmdk-section overline">{group}</div>
              {cmds.map((c) => {
                flat++;
                const idx = flat;
                const Ic = Icon[c.icon];
                return (
                  <button
                    key={c.id}
                    className={`cmdk-item ${idx === sel ? "sel" : ""}`}
                    onMouseEnter={() => setSel(idx)}
                    onClick={() => { c.run(); onClose(); }}
                  >
                    <Ic size={16} />
                    <span>{c.label}</span>
                    {c.hint && <span className="cmdk-hint">{c.hint}</span>}
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
