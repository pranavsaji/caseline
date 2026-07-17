# Caseline Dashboard — UI Redesign Plan (Neomorphism)

> **Status:** Phase 0 ✅ complete · Phase 1 ✅ complete · Phase 2 ✅ complete · Phase 3 ⬜ · Phase 4 ⬜ — _(last updated 2026-07-16)_

> **Goal:** Turn the current flat, functional dashboard into a production-grade, friendly, and visually distinctive interface using a **neomorphic ("soft UI")** design language — without touching the Python backend or the `frontend/lib/api.ts` contract.
>
> **Scope:** `frontend/` only (Next.js 15.3 App Router · React 19 · TypeScript). 9 existing pages + shared chrome. Deploy target: Vercel (already linked, project `caseline`).
>
> **Non-goals:** No backend changes, no new API endpoints in phase 1, no auth rework. The firm token stays server-side in the BFF route handlers.

---

## 1. Design thesis

Caseline is an **AI intake employee for law firms**. The product's whole promise is *calm competence under time pressure* — it answers within seconds, qualifies leads correctly, and never drops a case. The current UI is a dark spreadsheet: correct, but it reads like an internal admin tool, not a product a managing partner trusts with their front desk.

Neomorphism fits this brief when disciplined: soft, tactile surfaces read as **physical, reassuring, and premium** — like a well-made control panel rather than a database. The risk with neomorphism is universally known (low contrast, mushy affordances, poor accessibility). This plan treats that risk as the central constraint, not an afterthought.

**The one aesthetic risk we take:** a *dual-mode neomorphic surface* where **latency and status are expressed through the material itself** — an SLO-healthy metric sits *raised* (extruded, confident), a breached one sits *pressed/inset* (recessed, needs attention). The signature element is the **"pulse tile"**: the live latency/SLO readout rendered as a soft-extruded control with a subtle breathing glow keyed to health. This ties the visual language directly to what Caseline is measured on (per-turn latency budgets, speed-to-lead SLOs).

### Guiding principle: neomorphism for *surfaces*, not for *text*

Pure neomorphism (foreground = background color, shape defined only by shadow) fails WCAG. We adopt a **hybrid rule**, applied everywhere:

- **Containers, cards, buttons, toggles, inputs** → neomorphic (soft dual shadows, same-family fill).
- **Text, icons, data, status pills, focus rings** → **high-contrast**, sitting *on top* of soft surfaces. Pills keep solid saturated fills. Body text meets **WCAG AA (4.5:1)**; large text and UI ≥ 3:1.
- Every interactive element has a **non-shadow affordance** too (color shift, ring, or label) so it's usable for low-vision users and passes focus-visible checks.

---

## 2. Palette

Neomorphism needs a **mid-tone base** (not pure black, not pure white) so both the light and dark shadow of each element are visible. We ship **two themes**; default is **Slate Light** (best neomorphic legibility), with a **Graphite Dark** for night use. Theme is user-toggle + `prefers-color-scheme`, persisted to `localStorage`.

### Slate Light (default)
| Token | Hex | Role |
|---|---|---|
| `--surface` | `#E4E9F2` | Page + card base (the "clay") |
| `--surface-raised` | `#EDF1F9` | Slightly lifted card fill |
| `--shadow-dark` | `#C3CAD9` | Bottom-right cast shadow |
| `--shadow-light` | `#FFFFFF` | Top-left highlight |
| `--text` | `#26303E` | Primary text (≈ 11:1 on surface) |
| `--muted` | `#5C6879` | Secondary text (≈ 4.7:1) |
| `--accent` | `#3B6EF5` | Primary action / links / focus |
| `--accent-deep` | `#2551C6` | Pressed accent |

### Graphite Dark
| Token | Hex | Role |
|---|---|---|
| `--surface` | `#1E222B` | Page + card base |
| `--surface-raised` | `#242A35` | Lifted card fill |
| `--shadow-dark` | `#141820` | Bottom-right cast shadow |
| `--shadow-light` | `#2C3340` | Top-left highlight |
| `--text` | `#E7ECF5` | Primary text |
| `--muted` | `#96A0B5` | Secondary text |
| `--accent` | `#5B8DEF` | Primary action / links / focus |
| `--accent-deep` | `#3F6BD0` | Pressed accent |

### Semantic status (shared, solid fills — never neomorphic)
| Token | Light | Dark | Meaning |
|---|---|---|---|
| `--ok` | `#1F9D6B` | `#3FB27F` | Within SLO / booked / synced |
| `--warn` | `#C9871F` | `#E0A03d` | Near budget / pending |
| `--bad` | `#D0453F` | `#E05D5D` | Over budget / failed / opted-out |
| `--info` | `#3B6EF5` | `#5B8DEF` | Neutral state |

These map 1:1 onto the existing class vocabulary (`.pill.ok/.warn/.bad/.muted`) so page markup barely changes.

---

## 3. Typography

Two-role system, self-hosted via `next/font` (no external requests, zero CLS, works on Vercel edge):

- **Display / headings — `Space Grotesk`** (variable). Slightly technical, humanist-geometric; reads as "engineered precision" without being cold. Used for page titles, stat numbers, nav brand. Weights 500/600.
- **Body / UI — `Inter`** (variable). Neutral, superb at small sizes for dense tables. Weights 400/500/600.
- **Data / mono — `JetBrains Mono`** for latency numbers, JSON editors, transcript timestamps, IDs.

### Type scale
```
Display   32 / 600 / -0.02em   page hero titles
H2        22 / 600 / -0.01em   section headers
H3        16 / 600            card titles
Body      14 / 400            default table + prose
Small     12.5 / 500          labels, captions, pills
Mono-data 14 / 500            latency + numeric cells
```
Numbers in stat tiles use `font-variant-numeric: tabular-nums` so columns don't jitter.

---

## 4. The neomorphic material system (core CSS)

All soft surfaces derive from **four reusable shadow tokens**. This is the whole visual language — get these right and every component composes from them.

```css
:root {
  --nm-dist: 6px;         /* shadow offset */
  --nm-blur: 14px;        /* shadow blur */
  --radius: 18px;         /* generous, pillowy */
  --radius-sm: 12px;

  /* Raised (extruded) — default resting state of cards/buttons */
  --nm-raised:
    var(--nm-dist) var(--nm-dist) var(--nm-blur) var(--shadow-dark),
    calc(-1 * var(--nm-dist)) calc(-1 * var(--nm-dist)) var(--nm-blur) var(--shadow-light);

  /* Pressed (inset) — active buttons, inputs, breached metrics */
  --nm-pressed:
    inset var(--nm-dist) var(--nm-dist) var(--nm-blur) var(--shadow-dark),
    inset calc(-1 * var(--nm-dist)) calc(-1 * var(--nm-dist)) var(--nm-blur) var(--shadow-light);

  /* Flat-raised — subtle lift for large containers (tables) */
  --nm-flat: 3px 3px 8px var(--shadow-dark), -3px -3px 8px var(--shadow-light);
}

.nm { background: var(--surface); box-shadow: var(--nm-raised); border-radius: var(--radius); }
.nm-inset { background: var(--surface); box-shadow: var(--nm-pressed); border-radius: var(--radius); }
```

**Rules that keep it from looking cheap:**
1. Soft surfaces **must** share the page background family — no shadow trick works on a contrasting fill.
2. Never nest a raised element directly inside another raised element without an inset "well" between them, or shadows fight. Pattern: `raised card → inset well → raised control`.
3. Radius stays large (16–18px) and consistent; mixing radii breaks the molded look.
4. Cap shadow depth — one `--nm-dist`, one `--nm-blur` sitewide. Escalating shadows = amateur.
5. **Accessibility floor is non-negotiable** (see §7). Shadows are decoration; contrast is law.

---

## 5. Component library (new `frontend/components/`)

Currently there are **zero** reusable components — every page inlines tables and helpers. We extract a small kit so the redesign is consistent and pages get shorter.

| Component | File | Notes |
|---|---|---|
| `<AppShell>` | `components/AppShell.tsx` | Replaces `layout.tsx` body: soft sidebar nav (see §6), theme toggle, page container. |
| `<NavItem>` | `components/NavItem.tsx` | Neomorphic nav link; **pressed/inset when active**, raised on hover. |
| `<Card>` | `components/Card.tsx` | `.nm` container with optional title + actions slot. |
| `<StatTile>` | `components/StatTile.tsx` | The stat readout: big tabular number + label. |
| `<PulseTile>` | `components/PulseTile.tsx` | **Signature.** SLO-aware stat tile; raised+glow when healthy, inset+amber/red when breached. Drives latency & speed-to-lead readouts. |
| `<Pill>` | `components/Pill.tsx` | Solid status pill (ok/warn/bad/muted/info). High-contrast, not neomorphic. |
| `<DataTable>` | `components/DataTable.tsx` | Table shell inside an inset "well"; sticky header, zebra via faint surface shift, row hover lift. Keeps existing column markup. |
| `<SoftButton>` | `components/SoftButton.tsx` | Raised → inset on `:active`; `variant="primary"` gets accent fill + white text (contrast-safe). |
| `<SoftInput>` / `<SoftTextarea>` / `<SoftSelect>` | `components/inputs/*` | Inset fields with accent focus ring. |
| `<Toggle>` | `components/Toggle.tsx` | Neomorphic switch for the recording-disclosure checkbox etc. |
| `<TranscriptTurn>` | `components/TranscriptTurn.tsx` | Chat bubble: agent turns raised+accent-tinted, caller turns inset. Replaces `.turn`. |
| `<Notice>` | `components/Notice.tsx` | Soft inset callout (ok/bad/info). |
| `<EmptyState>` | `components/EmptyState.tsx` | Friendly illustration + one clear action (see writing rules §8). |
| `<PageHeader>` | `components/PageHeader.tsx` | Display title + subtitle + optional right-aligned actions. |
| `<ThemeToggle>` | `components/ThemeToggle.tsx` | Sun/moon soft button; sets `data-theme` on `<html>`. |

Icons: **`lucide-react`** (tree-shakeable, no icon-font request). One dependency.

---

## 6. Layout & navigation

Move from the current top nav bar to a **soft left sidebar** (desktop) that collapses to a **bottom tab bar / hamburger sheet** (mobile). Sidebar reads as a molded control panel — the most neomorphic-appropriate chrome.

```
┌──────────────┬─────────────────────────────────────────────┐
│  ⬤ Caseline   │  Intake overview            [🌗] [firm ▾]     │  ← PageHeader
│              │                                              │
│  ◱ Overview   │  ┌──────────┐ ┌──────────┐ ┌──────────┐      │
│  ◈ Threads    │  │ PulseTile│ │ StatTile │ │ StatTile │      │  ← at-a-glance row
│  ▤ Analytics  │  │ p95 lat  │ │ booked   │ │ qual %   │      │     (NEW — pages
│  ⚙ Tuning     │  └──────────┘ └──────────┘ └──────────┘      │      currently open
│  ↔ Referrals  │                                              │      cold into tables)
│  ✎ Studio     │  ┌──────────────────────────────────────┐   │
│  { } Config   │  │  Recent calls            (DataTable)  │   │
│              │  └──────────────────────────────────────┘   │
│  ─────────    │  ┌──────────────────────────────────────┐   │
│  🌗 Theme     │  │  Leads                   (DataTable)  │   │
└──────────────┴─────────────────────────────────────────────┘
```

- Sidebar sits in a raised panel; the active item is **inset** (you can feel where you are).
- Every list/analytics page gains a **summary tile row** at top so the first thing a partner sees is health, not raw rows. This is the biggest usability win.
- Content max-width ~1180px, generous 24–32px gutters (soft UI needs breathing room; cramped shadows look dirty).

---

## 7. Accessibility & performance (the part most neomorphism ships without)

**Contrast**
- Body text `--text` on `--surface` ≥ 4.5:1 (both themes verified in palette).
- Status pills use solid fills with white/near-black text ≥ 4.5:1.
- Interactive controls have a **≥ 3:1 non-shadow cue** (accent ring or fill), never shadow alone.

**Keyboard & focus**
- `:focus-visible` renders a **2px solid `--accent` ring inset** — visible against soft surfaces (shadows are invisible to keyboard users otherwise).
- Sidebar is a real `<nav>` with `aria-current="page"` on the active item.
- Toggles/switches use real `<input type="checkbox" role="switch">`, styled — not divs.

**Motion**
- `@media (prefers-reduced-motion: reduce)` disables the PulseTile breathing glow and all hover-lift transitions; state still readable via color + inset.

**Performance (Vercel)**
- Self-hosted fonts via `next/font` → no layout shift, no third-party request.
- Box-shadow-only styling = no images; keep total CSS < 15KB.
- Keep server components server-rendered; only `/studio` and `/config` stay `"use client"`. Add `<ThemeToggle>` as a tiny client island so pages don't lose SSR.
- Shadows are GPU-cheap but **don't animate `box-shadow` on scroll**; animate `transform`/`opacity` only.

**Contrast gate before ship:** run the palette through a contrast checker; any pair < AA gets darkened. This is a hard gate, not a nice-to-have.

---

## 8. Copy & microcopy pass

Small wording fixes that make it feel like a product, done alongside the visual work:

- Buttons say the outcome: **"Save changes" → "Published"** toast (studio/config). Not "Submit".
- Empty states are invitations, not blanks: e.g. calls table empty → *"No calls yet. Once your number is live, every call shows up here within seconds."* + link to Studio.
- Errors are directive: preview failure → *"Preview couldn't run. Check the caller script isn't empty and try again."* — in the interface's voice, no apology.
- Latency/SLO labels in plain terms: *"Answer speed"* with the ms as the data, tooltip explaining the 800ms budget — not "p95 EOU→TTS".
- Sentence case everywhere; consistent verbs (a lead is **contacted**, a consult is **booked**, a record is **synced**).

---

## 9. Page-by-page redesign

For each page: keep the data + `frontend/lib/api.ts` calls exactly; swap presentation to the component kit; add a summary tile row.

| Page | File | Changes |
|---|---|---|
| **Overview** `/` | `app/page.tsx` | Add PulseTile (p95 answer speed) + StatTiles (booked today, qualification rate). Three tables → `<DataTable>` in inset wells. Outcome/CMS/latency → `<Pill>`/`<PulseTile>` cells. |
| **Call detail** `/calls/[id]` | `app/calls/[id]/page.tsx` | Header → `<PageHeader>` with pills; transcript → `<TranscriptTurn>` bubbles; per-turn latency → `<DataTable>` with inline `<PulseTile>` totals; recording link → `<SoftButton>`. |
| **Analytics** `/analytics` | `app/analytics/page.tsx` | Funnel → row of `<StatTile>`; benchmarks → PulseTiles (own vs cohort percentile); latency-by-day/provider → `<DataTable>`. Suppressed-benchmark state → friendly `<Notice>`. |
| **Threads** `/threads` | `app/threads/page.tsx` | Speed-to-lead → PulseTile (first-contact SLO) + StatTiles; conversations → `<DataTable>`. |
| **Thread detail** `/threads/[id]` | `app/threads/[id]/page.tsx` | `<TranscriptTurn>` bubbles; raw State JSON → collapsible `<Notice>` with mono formatting. |
| **Tuning** `/tuning` | `app/tuning/page.tsx` | Agreement-rate PulseTile; decision matrix → `<DataTable>`; suggestions → cards; proposed rules → mono `<Notice>`. |
| **Referrals** `/referrals` | `app/referrals/page.tsx` | Referrals + partner network → `<DataTable>`; match reasons as inline chips. |
| **Config Studio** `/studio` | `app/studio/page.tsx` | The showcase page. Four config sections → `<Card>`s with `<SoftInput>`/`<Toggle>`/`<SoftSelect>`; Save → `<SoftButton variant="primary">` + toast; test-call preview → soft chat panel reusing `<TranscriptTurn>`, guardrail-tripped turns flagged with a `<Pill bad>`. |
| **Agent Config** `/config` | `app/config/page.tsx` | JSON textareas → `<SoftTextarea>` mono with inset well + validation state ring (red inset on invalid); compiled-instructions → read-only `<Notice>`. |

**Route handlers** (`app/api/config`, `app/api/preview`) are untouched — pure presentation redesign.

---

## 10. Implementation phases

**Phase 0 — Foundation (½ day) — ✅ COMPLETE (2026-07-16)**
1. ✅ `npm i lucide-react` in `frontend/` — added to `package.json`.
2. ✅ Fonts via `next/font/google` in `app/layout.tsx` — Space Grotesk (display), Inter (body), JetBrains Mono (data), exposed as CSS variables, self-hosted at build (no external request, no CLS).
3. ✅ Rewrote `app/globals.css`: dual-theme tokens (Slate Light default + Graphite Dark via `[data-theme]` **and** `prefers-color-scheme`), full `--nm-*` shadow system, **backward-compatible aliases** (`--bg`/`--panel`/`--border`) so all 9 existing pages stay coherent, base resets, `:focus-visible` ring, reduced-motion block, restyled existing class vocabulary (`.nav`, `table`, `.pill`, `.turn`, `.notice`, `.empty`, inputs, buttons) onto soft material with markup unchanged.
4. ✅ Added `<ThemeToggle>` client island (`components/ThemeToggle.tsx`) + inline pre-hydration `data-theme` bootstrap script in `<head>` (no flash-of-wrong-theme), persisted to `localStorage` under `caseline-theme`.

**Files touched:** `frontend/package.json`, `frontend/package-lock.json`, `frontend/app/layout.tsx`, `frontend/app/globals.css`, `frontend/components/ThemeToggle.tsx` (new).

**Validation performed:**
- `npx tsc --noEmit` → clean (exit 0).
- `npm run build` → all 12 routes compiled, 7/7 static pages generated, `next/font` fetched successfully, no lint/type errors.
- Runtime smoke test (`next start` on a clean port): `/`, `/studio`, `/config` all HTTP 200; verified in served HTML — theme bootstrap script present, `next/font` variable classes on `<html>`, `<ThemeToggle>` rendered, nav chrome intact.
- Compiled CSS = **13.3 KB** (under the 15 KB budget); confirmed to contain `--nm-raised`/`--nm-pressed`, both theme blocks (`[data-theme=dark]` + `prefers-color-scheme:dark`), `prefers-reduced-motion`, `:focus-visible`, and both base palettes.
- **Visual check in Chrome, both themes:** light mode = textbook neomorphism (soft raised nav panel, inset input wells, high-contrast `#26303e` text on `#e4e9f2`); dark mode = matching soft surfaces on graphite; theme toggle switches live and persists.

**Notes / learnings for later phases:**
- OS default here is dark, so the app opens in Graphite Dark unless toggled — expected behavior.
- Existing pages now inherit soft styling for free via the restyled class vocabulary; Phase 2 replaces them with the real component kit.
- Keep the single-shadow-depth rule (`--nm-dist`/`--nm-blur`) when building components — the material already looks right; don't escalate shadows.

**Phase 1 — Component kit (1 day) — ✅ COMPLETE (2026-07-16)**
Build `components/*` from §5, in dependency order: `Pill` → `Card` → `SoftButton`/inputs → `StatTile`/`PulseTile` → `DataTable` → `TranscriptTurn`/`Notice`/`EmptyState` → `AppShell`/`NavItem`/`PageHeader`. Storybook-style scratch page at `/kit` (dev-only) to eyeball every component in both themes.

1. ✅ Shared scoped styles: `components/kit.module.css` (CSS Module) composes the Phase 0 tokens (`--surface`, `--nm-raised`, `--accent`, …) into every component. Kept `globals.css` as the pure token/foundation layer — no globals bloat, idiomatic Next.js. One shadow depth sitewide preserved; PulseTile breathing glow via scoped `@keyframes`, frozen under `prefers-reduced-motion`.
2. ✅ Built all 15 components from §5:
   - Primitives: `Pill` (solid, high-contrast, 5 tones + dot), `Card` + `Well` (the required inset buffer for nested raised controls), `SoftButton` (default/primary/danger, raised→lift→inset-press, forwards native props).
   - Inputs (`components/inputs/*`): `SoftInput`, `SoftTextarea` (mono default), `SoftSelect` (custom chevron) — all inset wells with accent focus ring + red-inset `invalid` validation cue; `Toggle` (real `<input type=checkbox role=switch>`, focus ring, accent-fill thumb).
   - Data/signature: `StatTile` (tabular number + label), **`PulseTile`** (SLO-aware — raised+glow healthy, amber breathing near-budget, **inset/recessed when breached**; `pulseStatus()` helper computes health from value vs budget, lower- or higher-is-better), `DataTable<T>` (generic columns, inset well, sticky header, zebra via surface shift, hover lift, horizontal scroll), `TranscriptTurn` + `TranscriptList` (agent raised+accent-left / caller inset, opposite alignment).
   - Feedback/chrome: `Notice` (4 tones + lucide icon), `EmptyState` (soft icon medallion + copy + action), `PageHeader` (display title/subtitle/actions), `AppShell` (raised soft sidebar → mobile top bar, theme toggle pinned) + `NavItem` (client island, **inset when active** via `usePathname`, `aria-current`).
3. ✅ Dev-only `/kit` gallery (`app/kit/page.tsx` + `Gallery.tsx` + `themeVars.ts`): renders the full kit **twice on one page — Slate Light and Graphite Dark side by side** — by inline-overriding the palette CSS vars per panel (custom-property substitution resolves `--nm-*` shadows against the in-scope palette). Gated with `notFound()` when `NODE_ENV === "production"` so it never ships as a route.

**Files touched:** `frontend/components/kit.module.css` (new), `frontend/components/{Pill,Card,SoftButton,StatTile,PulseTile,DataTable,TranscriptTurn,Notice,EmptyState,PageHeader,Toggle,NavItem,AppShell}.tsx` (new), `frontend/components/inputs/{SoftInput,SoftTextarea,SoftSelect}.tsx` (new), `frontend/app/kit/{page,Gallery,themeVars}.tsx` (new). No existing pages, `lib/api.ts`, or route handlers changed — kit is additive.

**Validation performed:**
- `npx tsc --noEmit` → clean (exit 0).
- `npm run build` → all 8 static routes generated including `/kit`; no lint/type errors; First Load JS unchanged for existing routes (kit code is isolated).
- **Production gate verified:** `next start` on the prod build → `/kit` returns **404** (dev-only), while `/config` returns 200 — the `notFound()` gate works.
- **Dev runtime:** `next dev` → `/kit` HTTP 200, served HTML contains both theme panels + every component, no runtime errors in the log.
- **Visual check in Chrome (both themes on one page):** Slate Light + Graphite Dark both render as textbook neomorphism — PulseTiles express health through material (healthy = raised green, breached "Speed to lead" = **inset/recessed red**), inset input wells with red error text, accent-filled Toggle, agent-raised/caller-inset transcript bubbles, tone-colored Notices, soft EmptyState medallions, `Card → Well → SoftButton` nesting rule demonstrated. **Console clean on reload — no errors, no hydration warnings.**

**Notes / learnings for later phases (Phase 2 shell + page migration):**
- `AppShell`/`NavItem` are built and gallery-verified but **not yet wired into `layout.tsx`** — that swap is Phase 2 (replace the flat `.nav` with `<AppShell>`). The old class vocabulary in `globals.css` still styles the un-migrated pages until then.
- Import components via the `@/components/*` path alias (e.g. `@/components/PulseTile`). Server pages can use every component except `NavItem`/`AppShell`/`ThemeToggle` (client islands) — but AppShell wraps them for you, so pages stay server-rendered.
- `DataTable` is generic (`Column<T>`) and keeps existing column markup — Phase 2 page migrations map current `<table>` rows onto its `columns` array with `render`.
- For latency/SLO cells use `PulseTile` (or `pulseStatus()` + `Pill`) so health reads from the material, not just color.
- CSS Module (`kit.module.css`) is ~16KB source but scoped and tree-split per route by Next.js — the <15KB global budget from Phase 0 (`globals.css` = 13.3KB) is unaffected.

**Phase 2 — Shell + pages (1.5 days) — ✅ COMPLETE (2026-07-16)**
Swap `layout.tsx` to `<AppShell>`; migrate pages in order of §9 (Overview → detail pages → Studio last). Keep each page's data layer identical.

1. ✅ `layout.tsx` now renders `<AppShell>` (soft left sidebar → mobile top bar) in place of the flat `.nav`; fonts + pre-hydration theme bootstrap kept. The old `.nav`/`.shell`/element-restyle "backward-compat" block in `globals.css` was **removed** — every page is on the kit now, so those global `table`/`button`/`input` selectors would only fight the CSS-Module components (double table shadows inside wells, stray input margins). Only the `.theme-toggle` global (a plain `<button>` the shell pins) remains.
2. ✅ All **9 pages migrated** to the Phase 1 kit, data layer + `lib/api.ts` calls unchanged:
   - **Overview `/`** — `<PageHeader>` + summary `<TileRow>` (PulseTile answer-speed p95, StatTiles for consults booked & qualification rate); Recent calls / Leads / Booked consults → `<Card>` + `<DataTable>` with `<Pill>` cells and `<EmptyState>` empties. Added `getLatencyAnalytics` + `getOutcomeAnalytics` fetches (presentation-only, for the tile row).
   - **Call detail `/calls/[id]`** — `<PageHeader>` (outcome pill + recording `<SoftButton>`), tile row (PulseTile p95 + StatTiles), summary `<Notice>`, transcript → `<TranscriptTurn>`/`<TranscriptList>` bubbles, per-turn latency → `<DataTable>` with `pulseStatus()`-toned `<Pill>` totals.
   - **Analytics `/analytics`** — funnel `<TileRow>` (PulseTile + StatTiles), outcomes / latency-by-day / by-provider → `<DataTable>`, suppressed benchmarks → friendly `<Notice>`.
   - **Threads `/threads`** — speed-to-lead PulseTile (first-contact SLO) + StatTiles, conversations `<DataTable>`.
   - **Thread detail `/threads/[id]`** — `<TranscriptTurn>` bubbles (out=agent/in=caller), raw State JSON → mono `<Notice>`.
   - **Tuning `/tuning`** — agreement-rate PulseTile (higher-is-better), decision matrix `<DataTable>`, suggestions as tone-warn `<Notice>`s, proposed rules → mono `<Notice>`.
   - **Referrals `/referrals`** — referrals + partner network `<DataTable>`s, match reasons as inline `<Pill>` chips.
   - **Studio `/studio`** — the showcase: four `<Card>` sections with `<SoftInput>`/`<Toggle>`/`<SoftSelect>`/`<SoftTextarea>`, `<SoftButton variant="primary">` publish + auto-dismissing toast `<Notice>`, test-call preview reusing `<TranscriptTurn>` with guardrail-tripped turns flagged `<Pill tone="bad">`.
   - **Agent Config `/config`** — JSON sections → `<SoftTextarea>` in `<Card>`s with a **live red-inset validation ring** (shared `lib/json.ts#getConfigError`), publish disabled while any section is invalid, compiled instructions → read-only mono `<Notice>`.
3. ✅ New helpers: `components/TileRow.tsx` (the §6 summary-row grid), `lib/json.ts` (shared JSON-parse error helper). Global utilities `.stackCard` / `.formGrid` / `.formRow` added to `globals.css` for page rhythm (kept global, not module, so component `className` passthrough works).

**Files touched:** `frontend/app/layout.tsx`, `frontend/app/globals.css`, all 9 page files (`app/{page,calls/[id]/page,analytics/page,threads/page,threads/[id]/page,tuning/page,referrals/page,studio/page,config/page}.tsx`), `frontend/components/{AppShell,NavItem}.tsx` (icon prop crossed the server→client boundary — see learning below), `frontend/components/TileRow.tsx` (new), `frontend/lib/json.ts` (new). `lib/api.ts` + route handlers unchanged.

**Validation performed:**
- `npx tsc --noEmit` → clean (exit 0).
- `npm run build` → all 8 routes compiled; `/kit` stays dev-only; First Load JS ~103–110 KB per route. **First build failed** on `/_not-found` prerender (see learning) — fixed, second build green.
- **Runtime smoke test** (`next start`, real Railway-style backend on `:8000`): `/`, `/threads`, `/analytics`, `/tuning`, `/referrals`, `/studio`, `/config` all **HTTP 200**; `/kit` **404** (prod gate holds). Dynamic detail routes `/calls/[id]` and `/threads/[id]` **200** with real data (transcript bubbles `turnAgent`/`turnCaller`, per-turn latency, PulseTile all present). No `application error` / server-error markup in served HTML; hashed kit classes + `aria-current` active-nav confirmed.
- **Visual check in Chrome, both themes:** Slate Light + Graphite Dark both render as textbook neomorphism — soft sidebar with the active item **inset**, PageHeader hero, summary tile rows, DataTables in inset wells with solid pills, accent-filled Toggle, primary publish button. **Console clean** (no errors/hydration warnings).
- **Interaction test:** typed invalid JSON into `/config` → red inset validation ring + directive error text (`Invalid JSON — Expected property name…`) + Publish auto-disabled (`aria-invalid=true`), exactly as designed.

**Notes / learnings for Phase 3:**
- **Server→client prop boundary:** `AppShell` (server component, in `layout.tsx`) originally passed lucide **icon components** (functions) to the client `<NavItem>` — Next.js rejects this and it surfaced as a `/_not-found` **prerender failure at build time**, not in dev. Fix: pass an icon **name string** and resolve it to a component inside `NavItem` (client). Rule for later: never hand a function/component prop across the RSC boundary; key by string.
- Pages no longer render their own `<main>` — `AppShell` provides the single `<main className={content}>`; page roots are fragments. Don't reintroduce a nested `<main>`.
- The `PulseTile` "no data" fallback renders the em-dash in the healthy-green color (status `null` → `pulseOk`). Cosmetically reads slightly "healthy" when there's genuinely no data — candidate for a neutral `pulseNone` state in the Phase 3 polish pass if it bothers a partner.
- Remaining for **Phase 3**: contrast audit (hard AA gate), keyboard walkthrough, mobile breakpoints (sidebar → top bar already responsive at ≤860px — verify on device), reduced-motion, Lighthouse, and the §8 microcopy sweep (much of it already applied: "Publish changes", directive errors, inviting empty states).

**Phase 3 — Polish & a11y gate (½ day)**
Contrast audit (hard gate), keyboard walkthrough of every page, mobile breakpoints (sidebar → bottom tabs), reduced-motion check, Lighthouse (target ≥ 95 a11y / ≥ 90 perf). Microcopy pass (§8).

**Phase 4 — Ship**
`cd frontend && npm run build` locally → fix type errors → `vercel --prod` (or push to the linked project's production branch). Confirm `CASELINE_API_URL` + `CASELINE_FIRM_TOKEN` env vars are set in Vercel. Smoke-test all 9 routes against the Railway backend.

**Total: ~4 working days.**

---

## 11. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Neomorphism fails contrast → unusable | Hybrid rule (§1): soft surfaces, high-contrast text/pills. Hard AA gate before ship. |
| Soft buttons don't look clickable | Accent fill on primary + inset-on-press + hover lift + focus ring. Never shadow-only. |
| Flash of wrong theme on load | Inline pre-hydration script sets `data-theme` before paint. |
| Shadows look muddy on wrong bg | Enforce single surface family; lint that no soft component sets a custom background. |
| Scope creep into backend features | Phase 1 is presentation-only. Backend-ready-but-UI-absent features (voice cloning, lead review, admin ops) are a **separate future phase**, noted below. |
| Dense tables feel cramped in soft UI | Inset "well" wrapper + generous padding + zebra via faint surface shift, not borders. |

---

## 12. Future phases (backend already supports, out of scope now)

The FastAPI backend exposes ~45 endpoints; only ~20 are surfaced today. Natural next UI increments once the neomorphic kit exists:
- **Voice profiles** — cloning/assignment UI (`POST /v1/voice-profiles`, `/v1/agents/{id}/voice`).
- **Lead review workflow** — attorney verdict capture (`POST /v1/leads/{id}/review`) to close the tuning loop.
- **Admin ops panel** — queue overview, DLQ replay, alerts, onboarding.
- **Referral send/status actions** — make the referrals page interactive.

---

## Appendix A — File change map

```
frontend/
  app/
    layout.tsx            ✎ swap to <AppShell> + fonts + theme bootstrap
    globals.css           ✎ full rewrite: tokens + --nm-* system + a11y
    page.tsx              ✎ tiles + DataTable
    calls/[id]/page.tsx   ✎ TranscriptTurn + PulseTile
    analytics/page.tsx    ✎ StatTile/PulseTile + DataTable
    threads/page.tsx      ✎
    threads/[id]/page.tsx ✎
    tuning/page.tsx       ✎
    referrals/page.tsx    ✎
    studio/page.tsx       ✎ SoftInput/Toggle/preview panel
    config/page.tsx       ✎ SoftTextarea + validation ring
    kit/page.tsx          + dev-only component gallery
    api/config/route.ts   ✓ unchanged
    api/preview/route.ts   ✓ unchanged
  components/             + new component kit (§5)
  lib/api.ts              ✓ unchanged (contract frozen)
  package.json            ✎ + lucide-react
```

## Appendix B — Neomorphism do / don't (build checklist)

**Do:** mid-tone base · one shadow depth sitewide · large consistent radius · inset for pressed/active · high-contrast text on soft surfaces · real focus rings · tabular-nums for data.

**Don't:** neomorphic text · contrasting backgrounds under soft elements · escalating shadow depths · shadow as the only affordance · animate box-shadow · pure-white or pure-black base · nest raised-in-raised without an inset well.
