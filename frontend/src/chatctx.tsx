import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

// A one-off chat context: a set of entities (papers, claims, answers…) the user
// has picked from ANYWHERE in the app to chat over. Selection lives app-wide so
// you can gather items across views, then open Ask grounded in exactly that set.
export type EntityKind = "document" | "claim" | "answer" | "node";
export interface EntityRef {
  kind: EntityKind;
  id: string;
  label: string; // human summary, shown in the tray + chat header
}

interface ChatCtx {
  items: EntityRef[];
  has: (id: string) => boolean;
  toggle: (item: EntityRef) => void;
  add: (item: EntityRef) => void;
  remove: (id: string) => void;
  clear: () => void;
  count: number;
}

const Ctx = createContext<ChatCtx | null>(null);

export function ChatContextProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<EntityRef[]>([]);

  const has = useCallback((id: string) => items.some((i) => i.id === id), [items]);
  const add = useCallback((item: EntityRef) =>
    setItems((s) => (s.some((i) => i.id === item.id) ? s : [...s, item])), []);
  const remove = useCallback((id: string) =>
    setItems((s) => s.filter((i) => i.id !== id)), []);
  const toggle = useCallback((item: EntityRef) =>
    setItems((s) => (s.some((i) => i.id === item.id) ? s.filter((i) => i.id !== item.id) : [...s, item])), []);
  const clear = useCallback(() => setItems([]), []);

  const value = useMemo<ChatCtx>(
    () => ({ items, has, toggle, add, remove, clear, count: items.length }),
    [items, has, toggle, add, remove, clear]
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useChatContext(): ChatCtx {
  const c = useContext(Ctx);
  if (!c) throw new Error("useChatContext must be used within ChatContextProvider");
  return c;
}

// A universal toggle — drop it on any entity so "add to chat" is available
// everywhere, the way an AI-native system should be. `compact` renders an
// icon-only pill for dense surfaces (claim rows, map panels).
export function AddToChat({ item, compact = false }: { item: EntityRef; compact?: boolean }) {
  const { has, toggle } = useChatContext();
  const on = has(item.id);
  return (
    <button
      type="button"
      className={`addchat ${on ? "on" : ""} ${compact ? "compact" : ""}`}
      title={on ? "Remove from chat context" : "Add to chat context"}
      aria-pressed={on}
      onClick={(e) => { e.stopPropagation(); toggle(item); }}
    >
      <span className="addchat-glyph">{on ? "✓" : "＋"}</span>
      {compact ? <span className="addchat-clabel">Chat</span> : <span>{on ? "In chat" : "Add to chat"}</span>}
    </button>
  );
}

const KIND_LABEL: Record<EntityKind, string> = {
  document: "paper", node: "paper", claim: "claim", answer: "answer",
};

// Floating tray — mirrors the map's compare tray. Appears whenever the context
// is non-empty, from any view.
export function ChatContextTray({ onOpenChat }: { onOpenChat: () => void }) {
  const { items, remove, clear, count } = useChatContext();
  if (count === 0) return null;
  const kinds = items.reduce<Record<string, number>>((a, i) => {
    a[KIND_LABEL[i.kind]] = (a[KIND_LABEL[i.kind]] ?? 0) + 1; return a;
  }, {});
  const summary = Object.entries(kinds).map(([k, n]) => `${n} ${k}${n === 1 ? "" : "s"}`).join(" · ");
  return (
    <div className="chatctx-tray" role="region" aria-label="Chat context">
      <div className="chatctx-tray-head">
        <span className="chatctx-tray-count mono">{count}</span>
        <span className="chatctx-tray-sum">{summary} selected for chat</span>
        <span style={{ flex: 1 }} />
        <button className="btn btn-ghost" style={{ fontSize: 12 }} onClick={clear}>Clear</button>
        <button className="btn btn-accent" style={{ fontSize: 12 }} onClick={onOpenChat}>
          ❝ Chat with selection →
        </button>
      </div>
      <div className="chatctx-chips">
        {items.map((i) => (
          <span key={i.id} className={`chatctx-chip ${i.kind}`} title={i.label}>
            <span className="chatctx-chip-k">{KIND_LABEL[i.kind]}</span>
            {i.label.replace(/^(paper|claim|answer) · /, "").slice(0, 46)}
            <button className="chatctx-chip-x" onClick={() => remove(i.id)} aria-label="Remove">×</button>
          </span>
        ))}
      </div>
    </div>
  );
}
