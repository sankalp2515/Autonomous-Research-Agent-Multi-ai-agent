import { useEffect, useRef, useState } from "react";
import { authEnabled, getEmail, signOut } from "../auth";
import { api } from "../api";
import { Icon } from "./icons";

export default function ProfileMenu({
  onAbout,
  onShortcuts,
}: {
  onAbout?: () => void;
  onShortcuts?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const email = getEmail();
  const [orgs, setOrgs] = useState<{ id: string; name: string; personal: boolean; role: string }[]>([]);

  useEffect(() => {
    if (open && orgs.length === 0) api.listOrgs().then(setOrgs).catch(() => {});
  }, [open, orgs.length]);

  useEffect(() => {
    const h = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);

  if (!authEnabled) return null;
  const name = email ? email.split("@")[0] : "Account";
  const initial = (email || "?").charAt(0).toUpperCase();
  const close = () => setOpen(false);

  return (
    <div className="profile" ref={ref}>
      <button className="profile-btn" onClick={() => setOpen((o) => !o)} aria-haspopup="menu" aria-expanded={open}>
        <span className="profile-avatar">{initial}</span>
        <span>{name}</span>
        <span style={{ opacity: 0.5, fontSize: 10 }}>▾</span>
      </button>
      {open && (
        <div className="profile-menu" role="menu">
          <div className="pm-head">
            <span className="pm-avatar-lg">{initial}</span>
            <div className="pm-id">
              <b>{name}</b>
              <span className="pm-email">{email || "Signed in"}</span>
              <span className="pm-role">Researcher · Veriscope workspace</span>
            </div>
          </div>

          {orgs.length > 0 && (
            <>
              <div className="pm-sep" />
              <div className="pm-orglabel">Workspaces</div>
              {orgs.map((o) => (
                <div key={o.id} className="pm-org">
                  <span className="pm-org-name">{o.personal ? "Personal workspace" : o.name}</span>
                  <span className="pm-org-role">{o.role}</span>
                </div>
              ))}
            </>
          )}

          <div className="pm-sep" />

          {onAbout && (
            <button className="pm-item" role="menuitem" onClick={() => { close(); onAbout(); }}>
              <Icon.about size={15} /> <span>How Veriscope works</span>
            </button>
          )}
          {onShortcuts && (
            <button className="pm-item" role="menuitem" onClick={() => { close(); onShortcuts(); }}>
              <Icon.search size={15} /> <span>Search &amp; commands</span> <span className="pm-kbd">⌘K</span>
            </button>
          )}
          <a className="pm-item" role="menuitem" href="https://arxiv.org/abs/2005.11401" target="_blank" rel="noreferrer" onClick={close}>
            <Icon.report size={15} /> <span>What is grounded RAG?</span> <Icon.external size={12} />
          </a>

          <div className="pm-sep" />

          <button className="pm-item danger" role="menuitem" onClick={() => signOut()}>
            <Icon.arrowRight size={15} /> <span>Sign out</span>
          </button>
        </div>
      )}
    </div>
  );
}
