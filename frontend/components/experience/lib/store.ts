/**
 * Frame-loop state for the cinematic experience.
 *
 * This is deliberately a plain mutable singleton, NOT React state: the WebGL
 * scene reads these values every frame inside `useFrame`, and routing them
 * through React would cause a re-render storm at 60fps. Scroll and pointer
 * handlers write here; the render loop reads here. A tiny subscription channel
 * exists only for coarse, low-frequency UI (the active section index driving
 * nav + progress dots), which DOES want React re-renders.
 */

export type ExperienceState = {
  /** Normalized scroll progress across the whole page, 0..1. */
  scroll: number;
  /** Pointer position in normalized device coords, -1..1 on each axis. */
  pointerX: number;
  pointerY: number;
  /** Smoothed "is the agent speaking" energy, 0..1 — drives orb displacement. */
  speak: number;
  /** Hover intensity on the orb / interactive hotspots, 0..1. */
  hover: number;
  /** Discrete active section index (for UI only). */
  section: number;
  /** True while the tab is visible; the render loop pauses when false. */
  visible: boolean;
  /** OS "prefers-reduced-motion" — freezes camera travel + parallax. */
  reducedMotion: boolean;
};

export const experience: ExperienceState = {
  scroll: 0,
  pointerX: 0,
  pointerY: 0,
  speak: 0,
  hover: 0,
  section: 0,
  visible: true,
  reducedMotion: false,
};

// ---- coarse section subscription (React-facing) -------------------------
type Listener = (section: number) => void;
const listeners = new Set<Listener>();

export function setSection(next: number) {
  if (next === experience.section) return;
  experience.section = next;
  for (const l of listeners) l(next);
}

export function subscribeSection(l: Listener): () => void {
  listeners.add(l);
  return () => listeners.delete(l);
}

/** Frame-rate-independent damping toward a target (exponential smoothing). */
export function damp(current: number, target: number, lambda: number, dt: number) {
  return current + (target - current) * (1 - Math.exp(-lambda * dt));
}
