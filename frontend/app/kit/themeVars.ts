import type { CSSProperties } from "react";

// Palette snapshots mirroring app/globals.css. Applied inline on the /kit
// gallery panels so both themes render side-by-side on one page: CSS custom
// properties inherit, and --nm-* shadow substitution resolves against whatever
// --shadow-* / --surface are in scope at the component — so overriding the
// palette on a wrapper is enough to re-theme everything inside it.
export const LIGHT_VARS = {
  "--surface": "#e4e9f2",
  "--surface-raised": "#edf1f9",
  "--surface-sunken": "#dbe1ec",
  "--shadow-dark": "#c3cad9",
  "--shadow-light": "#ffffff",
  "--text": "#26303e",
  "--muted": "#5c6879",
  "--accent": "#3363e6",
  "--accent-deep": "#2551c6",
  "--accent-hover": "#2551c6",
  "--on-accent": "#ffffff",
  "--ok": "#1f9d6b",
  "--warn": "#c9871f",
  "--bad": "#d0453f",
  "--info": "#3b6ef5",
  "--ok-ink": "#156b49",
  "--warn-ink": "#815614",
  "--bad-ink": "#a23631",
  "--info-ink": "#2d54ba",
  "--muted-ink": "#535e6d",
  "--border": "#ccd3e0",
  background: "#e4e9f2",
  color: "#26303e",
} as CSSProperties;

export const DARK_VARS = {
  "--surface": "#1e222b",
  "--surface-raised": "#242a35",
  "--surface-sunken": "#191d25",
  "--shadow-dark": "#141820",
  "--shadow-light": "#2c3340",
  "--text": "#e7ecf5",
  "--muted": "#96a0b5",
  "--accent": "#5b8def",
  "--accent-deep": "#3f6bd0",
  "--accent-hover": "#7aa4f4",
  "--on-accent": "#0f1320",
  "--ok": "#3fb27f",
  "--warn": "#e0a03d",
  "--bad": "#e05d5d",
  "--info": "#5b8def",
  "--ok-ink": "#3fb27f",
  "--warn-ink": "#e0a03d",
  "--bad-ink": "#e57777",
  "--info-ink": "#6f9bf1",
  "--muted-ink": "#96a0b5",
  "--border": "#313846",
  background: "#1e222b",
  color: "#e7ecf5",
} as CSSProperties;
