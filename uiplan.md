# Caseline Dashboard — UI Design System (Aurora / deep-space)

> **Status:** Shipped — replaces the earlier neomorphic system. Futuristic
> glassmorphism over a live WebGL aurora field. _(last updated 2026-07-16)_
>
> **Scope:** `frontend/` (Next.js 15.3 App Router · React 19 · TypeScript).
> Design tokens rewritten; the component-kit *API* is unchanged, so pages were
> not rewritten — only re-skinned. Backend contract (`frontend/lib/api.ts`)
> untouched by the restyle.

---

## 1. Design thesis

Caseline is an **AI intake employee for law firms** — calm competence under
time pressure. The interface should read as a **high-tech command console**:
dark, luminous, alive, and precise. We replaced the soft neomorphic surfaces
(which read as an internal admin tool) with **frosted glass panels floating over
a living aurora**, so the product feels like mission control for the front desk.

**Signature element:** a full-viewport **WebGL aurora** (violet/teal light
flowing over deep space) rendered behind translucent glass. Latency/SLO health
is still expressed by the material — the **PulseTile** now *glows* (breathing
neon keyed to health) instead of extruding.

## 2. Palette

Two themes via `[data-theme]`. **Aurora (dark)** is the default (no attribute);
**Holographic (light)** is opt-in via the toggle, persisted to `localStorage`
(`caseline-theme`) and applied pre-paint by the bootstrap script in `layout.tsx`.

### Aurora (default, dark) — `frontend/app/globals.css :root`
| Token | Value | Role |
|---|---|---|
| `--space` / `--space-2` | `#07081a` / `#0c0e26` | Deep-space base (behind WebGL) |
| `--surface` | `rgba(20,22,46,0.55)` | Translucent glass panel |
| `--surface-raised` | `rgba(32,34,66,0.66)` | Lifted glass (sticky headers) |
| `--surface-sunken` | `rgba(9,10,26,0.55)` | Inset well |
| `--glass-line` / `--glass-line-strong` | `rgba(150,170,255,.16)` / `.28` | Hairline borders |
| `--glass-glow` | `rgba(45,212,191,.20)` | Neon hover/active glow |
| `--text` / `--muted` | `#eaeeff` / `#a6afd6` | Text (AA on glass) |
| `--accent` / `--accent-2` | `#2dd4bf` (teal) / `#8b5cf6` (violet) | Primary / companion |
| `--accent-hover` / `--accent-deep` | `#5eead4` / `#14b8a6` | Hover / pressed |
| `--on-accent` | `#051018` | Text on the teal→violet button |

### Holographic (opt-in, light) — `:root[data-theme="light"]`
White iridescent glass over a soft gradient; teal `#0d9488` + violet `#7c3aed`
accents. Same token names, light values.

### Semantic status (shared)
`--ok #34d399 · --warn #fbbf24 · --bad #fb7185 · --info #60a5fa`, each with a
lightened **`*-ink`** variant used as foreground text (clears AA 4.5:1 on glass).
Pills keep tinted fills + ink text; never neomorphic, never low-contrast.

## 3. Material tokens (reused by the kit under their old names)

`globals.css` redefines the former neomorphic shadow tokens as **glass**, so
`components/kit.module.css` composes them unchanged:
- `--nm-raised` → hairline outline + top highlight + depth shadow (glass card).
- `--nm-pressed` → recessed inner shadow + hairline (inset well/input).
- `--nm-flat` → subtle outline + light depth (buttons/nav).
- `--nm-glow` → neon ring + blur glow (hover/active/signature tiles).
- `--nm-blur` (16px) → `backdrop-filter` radius applied to surfaces.

Aurora-specific overrides (frosted `backdrop-filter`, neon hovers, gradient
primary button, glowing active nav, holographic PulseTile) live in the override
block at the bottom of `kit.module.css`.

## 4. Typography

Unchanged, self-hosted via `next/font`: **Space Grotesk** (display/stat numbers),
**Inter** (body/UI), **JetBrains Mono** (latency, JSON, IDs).

## 5. WebGL aurora — `frontend/components/AuroraBackground.tsx`

Self-contained raw **WebGL2** fragment shader (no three.js → tiny, React-19
safe). A fixed, `aria-hidden`, `pointer-events:none`, `z-index:-1` canvas
(`.auroraCanvas`) domain-warps fbm noise into flowing violet/teal light.
Mounted once in `AppShell`. Guards: caps `devicePixelRatio` at 1.5, pauses the
RAF loop when the tab is hidden, and honours `prefers-reduced-motion` by drawing
a **single static frame** (no loop). If WebGL2 is unavailable, the CSS gradient
on `body` is the backdrop.

## 6. Components & pages

Shared kit in `frontend/components/` (Card, Pill, StatTile, PulseTile, DataTable,
SoftButton, inputs, Toggle, Notice, TranscriptTurn, EmptyState, PageHeader,
AppShell, NavItem) — same props as before, glass skin. Routes: Overview, Calls,
Threads, Analytics, Tuning, Referrals, Studio, Ops, Config (+ `calls/[id]`,
`threads/[id]`, `kit`).

## 7. Accessibility & performance

- Text/pills/focus rings stay high-contrast on glass (AA 4.5:1; UI ≥ 3:1).
- Every interactive element keeps a non-glow affordance (color, ring, label).
- Reduced-motion disables the shader loop and all transitions.
- One backdrop-blur per panel, capped DPR, hidden-tab pause → protects the
  Lighthouse posture (Perf/A11y).

## 8. Non-goals

No per-widget 3D scenes (background aurora only), no external asset requests
(WebGL + fonts are self-hosted), no backend/design-contract changes from the
restyle.
