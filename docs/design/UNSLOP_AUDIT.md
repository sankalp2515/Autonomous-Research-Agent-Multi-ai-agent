# Unslop audit — glass skin and the base design (2026-11-25)

Checklist: [heydamir/unslop](https://github.com/heydamir/unslop) `SKILL.md`
(CC BY 4.0, Damir Sokolovsky). Run against the code and against renders of
`frontend/skin-preview.html` in both skins (fixture data, no backend).

## The conflict, stated first

The brief was "match the reference's glassmorphism, premium, not AI slop".
unslop names glassmorphism itself as a trend to avoid swapping in ("do not
swap one trend for another like glass, grain, noise, neon"), and three things
in the reference image are on its list of signs:

| in the reference | unslop sign | what the skin does |
|---|---|---|
| pink/blush blurred blobs behind the window | "radial colour washes and blobs behind content" | one warm-neutral linear tone shift (paper → claret paper), no blobs |
| `PIPELINE`, `EVIDENCE QUALITY`, `RESEARCH CORPUS` | "uppercase labels with wide tracking" | sentence case, near-normal tracking, on all 54 selectors |
| `0.84 High` score dial, "Claim faithfulness 0.88" | decorative stat / mini chart | not copied; also against CLAUDE.md ("evidence strength is a study count, not a score") |
| "Verified" pill on the report | badge that overclaims | not copied, and the base kicker was changed (below) |

So the skin takes the reference's **material** (frosted, layered, framed
window on a warm ground; serif headings; one claret accent; hairlines) and
leaves its **slop signs**. Whether the glass trend itself is acceptable is a
taste call that is yours; the skin is one flag away from off.

## Direction (unslop's five lines)

- **Product.** A research workspace that drafts literature reviews in which every sentence can be traced to a source span.
- **Character.** exact, unhurried, accountable.
- **World.** a reading room: paper, ink, a marked-up proof, archival claret.
- **Moments.** the highlighted source span in the evidence rail; the PRISMA flow.
- **Signature.** the mono provenance line (`quote match · NLI 0.94 · § Results pp. 6–7`) — already in the product, kept everywhere a sentence is sourced.

## Findings

| # | sign | where | status |
|---|---|---|---|
| 1 | Badge that overclaims: "Verified systematic review" | `ReportView.tsx` kicker | **fixed in base** → "Systematic review"; the composition line already says "5 verified · 2 derived" |
| 2 | Unverifiable headline: "A research agent that *can't* make things up" | `Landing.tsx:116` | **open, your call.** SciFact puts the gate at 27% false accepts on contradicted claims; the sentence is now measurably false. Suggested: "Every sentence traced to the passage it came from" |
| 3 | "100% quote-entailed" tag on the landing demo card | `Landing.tsx:193` | **open, your call**, same reason |
| 4 | Uppercase tracked labels (54 selectors) | `styles.css` | fixed **in the glass skin**; base unchanged (the base is the locked Editorial Science system) |
| 5 | Emoji as labels: 🔗 shared badge, 🔔 alert count | `ReportView.tsx`, `ResumeBanner.tsx` | **fixed in base** (text only) |
| 6 | Looping motion on non-live things: `.side-agent .pulse` (monitor dot), landing proof dot, `#vhook` cite pulse | `styles.css:1801, 2156, 3716` | open. The run-progress pulses (`.rl-step.active`, `.ra-wave`) are LIVE state and stay |
| 7 | Hue gradient on avatar and the demo-hook header (`#6b76ea → #3f49b8`, a violet-blue) | `styles.css:1807, 3645, 3689` | open: the violet-blue gradient is the single most recognisable slop sign in the codebase |
| 8 | Radial wash behind the empty-state glyph | `styles.css:209` | open, minor |
| 9 | Two-layer translucency could cost contrast | glass skin | checked: reading surfaces are ≥ 72% white over a near-white ground; `prefers-reduced-transparency` and no-`backdrop-filter` browsers get opaque surfaces |
| 10 | Transparent sticky top bar let scrolled text collide with the breadcrumb | glass skin | **fixed** (found in the harness, not by the checklist) |

Clean on: hype words (none), exclamation marks (none), gradient text (none),
glows on chrome (none beyond item 7), one icon set (lucide-style, one stroke).

## Template check

Swap the name for another product's: the evidence rail, the mono provenance
line and the PRISMA flow would not fit. The base passes. The glass skin by
itself would fit any SaaS dashboard; what keeps it Veriscope is that it
changes only the material, not those three surfaces.

## How to revert

- Everyone: build with `VITE_SKIN=editorial`.
- One browser: open the app once with `?skin=editorial` (remembered).
- Remove entirely: delete `frontend/src/skins/glass.css` and its two lines in
  `main.tsx`, or `git revert` the skin commit. The base CSS was not edited.
