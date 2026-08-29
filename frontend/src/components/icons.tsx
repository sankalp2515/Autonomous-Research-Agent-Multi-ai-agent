// Single thin-stroke icon set (Lucide), ~1.75 stroke, inked in currentColor.
// Glyphs match the "Calm editorial-tech" design-system reference exactly.
// Icons are never decorative — each maps to one action or destination.
import type { SVGProps } from "react";

type P = SVGProps<SVGSVGElement> & { size?: number };

function Svg({ size = 16, children, ...rest }: P & { children: React.ReactNode }) {
  return (
    <svg
      className="ic"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...rest}
    >
      {children}
    </svg>
  );
}

export const Icon = {
  // Navigation
  overview: (p: P) => <Svg {...p}><rect x="3" y="3" width="7" height="9" rx="1" /><rect x="14" y="3" width="7" height="5" rx="1" /><rect x="14" y="12" width="7" height="9" rx="1" /><rect x="3" y="16" width="7" height="5" rx="1" /></Svg>,
  research: (p: P) => <Svg {...p}><circle cx="12" cy="12" r="3" /><ellipse cx="12" cy="12" rx="10" ry="4.5" transform="rotate(-30 12 12)" /><circle cx="20" cy="8" r="1.6" /></Svg>,
  report: (p: P) => <Svg {...p}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6" /><path d="M16 13H8M16 17H8M10 9H8" /></Svg>,
  ask: (p: P) => <Svg {...p}><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /></Svg>,
  metrics: (p: P) => <Svg {...p}><path d="M3 3v18h18" /><path d="M8 17v-5M13 17V7M18 17v-9" /></Svg>,
  sources: (p: P) => <Svg {...p}><path d="M12 2 2 7l10 5 10-5-10-5z" /><path d="m2 17 10 5 10-5" /><path d="m2 12 10 5 10-5" /></Svg>,
  compare: (p: P) => <Svg {...p}><rect x="3" y="3" width="18" height="18" rx="1.5" /><path d="M9 3v18M15 3v18" /></Svg>,
  map: (p: P) => <Svg {...p}><circle cx="18" cy="5" r="2.6" /><circle cx="6" cy="12" r="2.6" /><circle cx="18" cy="19" r="2.6" /><path d="M8.4 13.3 15.6 17.6M15.6 6.4 8.4 10.7" /></Svg>,
  monitor: (p: P) => <Svg {...p}><path d="M6 8a6 6 0 0 1 12 0c0 7 3 8 3 8H3s3-1 3-8" /><path d="M10.5 21a1.8 1.8 0 0 0 3 0" /></Svg>,
  notebook: (p: P) => <Svg {...p}><path d="m19 21-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z" /></Svg>,
  notes: (p: P) => <Svg {...p}><path d="M12 20h9" /><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z" /></Svg>,
  memory: (p: P) => <Svg {...p}><path d="M9 18h6M10 22h4" /><path d="M15.1 14c.2-.8.8-1.4 1.4-2A5 5 0 1 0 7 9c0 .5.1 1.5 1.5 3 .6.6 1.2 1.2 1.4 2" /></Svg>,
  about: (p: P) => <Svg {...p}><circle cx="12" cy="12" r="9" /><path d="M12 16v-4M12 8h.01" /></Svg>,

  // Controls / chrome
  search: (p: P) => <Svg {...p}><circle cx="11" cy="11" r="7.5" /><path d="M21 21l-4.3-4.3" /></Svg>,
  plus: (p: P) => <Svg {...p}><path d="M12 5v14M5 12h14" /></Svg>,
  x: (p: P) => <Svg {...p}><path d="M18 6 6 18M6 6l12 12" /></Svg>,
  check: (p: P) => <Svg {...p}><path d="M20 6 9 17l-5-5" /></Svg>,
  checkCheck: (p: P) => <Svg {...p}><path d="M18 6 7 17l-5-5" /><path d="m22 10-7.5 7.5L13 15" /></Svg>,
  arrowRight: (p: P) => <Svg {...p}><path d="M5 12h14M12 5l7 7-7 7" /></Svg>,
  chevronRight: (p: P) => <Svg {...p}><path d="m9 18 6-6-6-6" /></Svg>,
  chevronsUpDown: (p: P) => <Svg {...p}><path d="M7 15l5 5 5-5" /><path d="M7 9l5-5 5 5" /></Svg>,
  chevron: (p: P) => <Svg {...p}><path d="m6 9 6 6 6-6" /></Svg>,
  external: (p: P) => <Svg {...p}><path d="M15 3h6v6" /><path d="M10 14 21 3" /><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" /></Svg>,
  command: (p: P) => <Svg {...p}><path d="M15 6a3 3 0 1 1 3 3h-3zm0 0v12m0-6H9m6 0h0M9 18a3 3 0 1 1-3-3h3zm0 0V6m0 6h6" /></Svg>,
  sparkle: (p: P) => <Svg {...p}><path d="M12 3l1.8 4.7L18.5 9.5 13.8 11.3 12 16l-1.8-4.7L5.5 9.5l4.7-1.8z" /><path d="M19 15l.7 1.8L21.5 17.5l-1.8.7L19 20l-.7-1.8L16.5 17.5l1.8-.7z" /></Svg>,
  upload: (p: P) => <Svg {...p}><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><path d="M7 10l5-5 5 5M12 4v12" /></Svg>,
  download: (p: P) => <Svg {...p}><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><path d="M7 10l5 5 5-5M12 15V3" /></Svg>,
  back: (p: P) => <Svg {...p}><path d="M9 14 4 9l5-5" /><path d="M4 9h11a5 5 0 0 1 0 10h-1" /></Svg>,
  menu: (p: P) => <Svg {...p}><path d="M4 6h16M4 12h16M4 18h16" /></Svg>,
  gitCompare: (p: P) => <Svg {...p}><circle cx="5" cy="6" r="2.6" /><circle cx="19" cy="18" r="2.6" /><path d="M12 6h5a2 2 0 0 1 2 2v7" /><path d="M12 18H7a2 2 0 0 1-2-2V9" /></Svg>,

  // Provenance / trust
  quote: (p: P) => <Svg {...p}><path d="M6 17h3l2-4V7H5v6h3zM14 17h3l2-4V7h-6v6h3z" /></Svg>,
  textQuote: (p: P) => <Svg {...p}><path d="M17 6H3M21 12H8M21 18H8M3 12v6" /></Svg>,
  shieldCheck: (p: P) => <Svg {...p}><path d="M20 13c0 5-3.5 7.5-7.7 9a1 1 0 0 1-.6 0C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.2-2.7a1.2 1.2 0 0 1 1.5 0C14.5 3.8 17 5 19 5a1 1 0 0 1 1 1z" /><path d="m9 12 2 2 4-4" /></Svg>,
  gitBranch: (p: P) => <Svg {...p}><path d="M6 3v12" /><circle cx="18" cy="6" r="2.6" /><circle cx="6" cy="18" r="2.6" /><path d="M18 8.6a9 9 0 0 1-9 9" /></Svg>,
  keyRound: (p: P) => <Svg {...p}><circle cx="8" cy="15" r="5" /><path d="M11.5 11.5 21 2M18 5l2 2M15 8l2 2" /></Svg>,
  lock: (p: P) => <Svg {...p}><rect x="3" y="11" width="18" height="10" rx="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" /></Svg>,
  bookmark: (p: P) => <Svg {...p}><path d="m19 21-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z" /></Svg>,
  alertTriangle: (p: P) => <Svg {...p}><path d="m10.3 3.9-8.5 14.1a2 2 0 0 0 1.7 3h16.9a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" /><path d="M12 9v4M12 17h.01" /></Svg>,
  calendar: (p: P) => <Svg {...p}><rect x="3" y="4" width="18" height="18" rx="2" /><path d="M16 2v4M8 2v4M3 10h18" /></Svg>,
  clock: (p: P) => <Svg {...p}><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3.5 2" /></Svg>,
  cursor: (p: P) => <Svg {...p}><path d="M3 3l7.1 17 2.5-7.4L20 10.1z" /></Svg>,
};

export type IconName = keyof typeof Icon;
