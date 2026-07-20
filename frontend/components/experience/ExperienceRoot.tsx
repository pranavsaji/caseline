"use client";

import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import styles from "./experience.module.css";
import { experience } from "./lib/store";
import { EXPERIENCE_SECTIONS } from "./lib/sections";
import { useDeviceTier, useReducedMotion } from "./lib/capabilities";
import { useSmoothScroll, usePointerTracking } from "./lib/useSmoothScroll";
import { Loader } from "./ui/Loader";
import { Cursor } from "./ui/Cursor";
import { SideNav } from "./ui/SideNav";
import { Fallback } from "./ui/Fallback";
import { DASHBOARD_HREF } from "./ui/DashboardCta";
import { Hero } from "./sections/Hero";
import { Intro } from "./sections/Intro";
import { Features } from "./sections/Features";
import { Demo } from "./sections/Demo";
import { Proof } from "./sections/Proof";
import { Cta } from "./sections/Cta";
import { Footer } from "./sections/Footer";

// The WebGL bundle (three + drei + postprocessing) is heavy and browser-only —
// lazy-load it, client-side only, so it never blocks first paint or SSR.
const Canvas3D = dynamic(() => import("./webgl/Canvas3D").then((m) => m.Canvas3D), {
  ssr: false,
});

/**
 * Top-level client orchestrator for the cinematic experience. Resolves the
 * device tier + reduced-motion preference, gates the scene behind a cinematic
 * loader, and wires the scroll/pointer model that feeds the 3D render loop.
 */
export function ExperienceRoot() {
  const tier = useDeviceTier();
  const reduced = useReducedMotion();
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    experience.reducedMotion = reduced;
  }, [reduced]);

  // Loader may finish once the tier is known (scene can mount + paint).
  const ready = tier !== null;
  const showScene = tier === "high" || tier === "low";

  useSmoothScroll(EXPERIENCE_SECTIONS.length, reduced, loaded);
  usePointerTracking(loaded && showScene && !reduced);

  return (
    <div className={styles.root}>
      {tier === "none" && <Fallback />}
      {showScene && (
        <div className={styles.canvasFixed}>
          <Canvas3D tier={tier} />
        </div>
      )}

      {tier === "high" && !reduced && loaded && <Cursor />}

      <header className={styles.topbar}>
        <span className={styles.brand}>
          <span className={styles.brandDot} aria-hidden />
          Caseline
        </span>
        <span className={styles.topActions}>
          <a className={styles.topLink} href="mailto:hello@caseline.ai?subject=Caseline%20demo">
            Book a demo
          </a>
          <a
            className={`${styles.topLink} ${styles.topLinkAccent}`}
            href={DASHBOARD_HREF}
          >
            Go to dashboard
          </a>
        </span>
      </header>

      {showScene && <SideNav />}

      <main className={styles.content}>
        <Hero />
        <Intro />
        <Features />
        <Demo />
        <Proof />
        <Cta />
      </main>
      <Footer />

      <Loader ready={ready} onComplete={() => setLoaded(true)} />
    </div>
  );
}
