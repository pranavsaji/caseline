"use client";

import { useEffect, useState } from "react";

export type Tier = "high" | "low" | "none";

/** One-time WebGL support probe (creates and discards a throwaway context). */
export function detectWebGL(): boolean {
  if (typeof window === "undefined") return false;
  try {
    const canvas = document.createElement("canvas");
    return !!(
      window.WebGLRenderingContext &&
      (canvas.getContext("webgl") || canvas.getContext("experimental-webgl"))
    );
  } catch {
    return false;
  }
}

/**
 * Picks a rendering tier once, on mount:
 *  - "none": no WebGL → static poster fallback.
 *  - "low":  coarse pointer / small viewport / few cores → simplified scene
 *            (fewer particles, no post-processing, no cursor parallax).
 *  - "high": desktop-class → the full cinematic scene.
 * Returns `null` until measured so the caller can hold the loader (no SSR/CSR
 * mismatch, no layout shift).
 */
export function useDeviceTier(): Tier | null {
  const [tier, setTier] = useState<Tier | null>(null);

  useEffect(() => {
    if (!detectWebGL()) {
      setTier("none");
      return;
    }
    const coarse = window.matchMedia("(pointer: coarse)").matches;
    const small = window.matchMedia("(max-width: 820px)").matches;
    const fewCores =
      typeof navigator !== "undefined" &&
      typeof navigator.hardwareConcurrency === "number" &&
      navigator.hardwareConcurrency <= 4;
    setTier(coarse || small || fewCores ? "low" : "high");
  }, []);

  return tier;
}

/** Live "prefers-reduced-motion" flag, updated if the OS setting changes. */
export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);
  return reduced;
}
