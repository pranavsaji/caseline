"use client";

import { useEffect } from "react";
import Lenis from "lenis";
import { experience, setSection } from "./store";

/**
 * Drives the whole experience's scroll model. Sets up Lenis smooth scrolling
 * (unless reduced-motion is requested, in which case native scroll is used and
 * Lenis is skipped entirely), and on every scroll frame writes normalized
 * progress into the shared `experience` store the WebGL loop reads. Also
 * derives the coarse active-section index from progress.
 *
 * @param count number of stacked sections (used to bucket progress → section)
 * @param reduced whether reduced-motion is active
 * @param enabled gate so we don't start scrolling until the loader is done
 */
export function useSmoothScroll(count: number, reduced: boolean, enabled: boolean) {
  useEffect(() => {
    if (!enabled) return;

    const update = () => {
      const doc = document.documentElement;
      const max = doc.scrollHeight - window.innerHeight;
      const p = max > 0 ? Math.min(1, Math.max(0, window.scrollY / max)) : 0;
      experience.scroll = p;
      // Bucket into sections with a small bias so a section "activates" as it
      // reaches roughly the middle of the viewport.
      setSection(Math.min(count - 1, Math.round(p * (count - 1))));
    };

    if (reduced) {
      window.addEventListener("scroll", update, { passive: true });
      update();
      return () => window.removeEventListener("scroll", update);
    }

    const lenis = new Lenis({
      duration: 1.15,
      easing: (t) => 1 - Math.pow(1 - t, 3),
      smoothWheel: true,
      touchMultiplier: 1.4,
    });
    lenis.on("scroll", update);

    let raf = 0;
    const loop = (time: number) => {
      lenis.raf(time);
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    update();

    return () => {
      cancelAnimationFrame(raf);
      lenis.destroy();
    };
  }, [count, reduced, enabled]);
}

/** Tracks pointer position into the store (normalized -1..1) for parallax. */
export function usePointerTracking(enabled: boolean) {
  useEffect(() => {
    if (!enabled) return;
    const onMove = (e: PointerEvent) => {
      experience.pointerX = (e.clientX / window.innerWidth) * 2 - 1;
      experience.pointerY = -((e.clientY / window.innerHeight) * 2 - 1);
    };
    const onVisibility = () => {
      experience.visible = document.visibilityState === "visible";
    };
    window.addEventListener("pointermove", onMove, { passive: true });
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.removeEventListener("pointermove", onMove);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [enabled]);
}
