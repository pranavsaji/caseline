"use client";

import { useEffect, useRef } from "react";
import { experience } from "../lib/store";
import { VoiceScene } from "./VoiceScene";
import type { Tier } from "../lib/capabilities";

/**
 * The fixed, full-viewport WebGL host. Renders an empty container and lets the
 * imperative {@link VoiceScene} (vanilla Three.js) create + own its own
 * <canvas> inside it — react-three-fiber's reconciler doesn't commit in this
 * Next 15 / React 19 setup, and a scene-owned canvas also survives StrictMode's
 * dev-only double mount (a shared canvas would render black on remount because
 * its WebGL context can't be re-acquired after dispose).
 *
 * Performance guards live in VoiceScene: DPR is clamped per tier, and rendering
 * pauses whenever the tab is hidden (tracked here into the shared store).
 */
export function Canvas3D({ tier }: { tier: Tier }) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    let scene: VoiceScene | null = null;
    try {
      scene = new VoiceScene(container, tier);
      scene.start();
    } catch (err) {
      // If WebGL context creation fails at runtime, fail quietly — the static
      // CSS fallback behind the canvas remains visible.
      console.error("VoiceScene failed to initialize", err);
    }

    const onVis = () => {
      experience.visible = document.visibilityState === "visible";
    };
    document.addEventListener("visibilitychange", onVis);
    onVis();

    return () => {
      document.removeEventListener("visibilitychange", onVis);
      scene?.dispose();
    };
  }, [tier]);

  return <div ref={containerRef} style={{ width: "100%", height: "100%" }} />;
}
