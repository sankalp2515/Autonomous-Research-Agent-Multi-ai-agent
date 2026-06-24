import { useEffect, useRef, useState } from "react";
import { authEnabled, getEmail, signOut } from "../auth";

export default function ProfileMenu() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const email = getEmail();

  useEffect(() => {
    const h = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);

  if (!authEnabled) return null;
  const initial = (email || "?").charAt(0).toUpperCase();

  return (
    <div className="profile" ref={ref}>
      <button className="profile-btn" onClick={() => setOpen((o) => !o)}>
        <span className="profile-avatar">{initial}</span>
        <span>{email ? email.split("@")[0] : "Account"}</span>
        <span style={{ opacity: 0.5, fontSize: 10 }}>▾</span>
      </button>
      {open && (
        <div className="profile-menu">
          <div className="pm-email">{email || "Signed in"}</div>
          <button onClick={() => signOut()}>Sign out</button>
        </div>
      )}
    </div>
  );
}
