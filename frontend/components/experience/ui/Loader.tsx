"use client";

import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import styles from "../experience.module.css";

/**
 * Cinematic loading sequence with visible progress. Because the scene is fully
 * procedural (no assets to download), progress is scripted: it eases toward
 * 100%, but holds near the end until the caller signals `ready` (device tier
 * resolved + first frame able to render). Prevents both a blank hold and an
 * instant flash. Calls `onComplete` once, after the bar fills and fades.
 */
export function Loader({ ready, onComplete }: { ready: boolean; onComplete: () => void }) {
  const [progress, setProgress] = useState(0);
  const [hidden, setHidden] = useState(false);
  const done = useRef(false);

  // Completes the loader exactly once: fill the bar, fade out, then hand off.
  // Held in a ref (refreshed each render) so both the rAF loop and the safety
  // timeout below can call the latest closure without re-subscribing effects.
  const finish = useRef<() => void>(() => {});
  finish.current = () => {
    if (done.current) return;
    done.current = true;
    setProgress(100);
    setHidden(true);
    window.setTimeout(onComplete, 750);
  };

  // Safety net: once the scene can render, never let the loader outstay ~2.6s,
  // even if the main thread is momentarily saturated by scene init (which can
  // starve the rAF-driven progress animation below).
  useEffect(() => {
    if (!ready) return;
    const t = window.setTimeout(() => finish.current(), 2600);
    return () => clearTimeout(t);
  }, [ready]);

  useEffect(() => {
    let raf = 0;
    let last = performance.now();
    const tick = (now: number) => {
      const dt = Math.min((now - last) / 1000, 0.05);
      last = now;
      setProgress((p) => {
        // Ease toward 100 if ready, otherwise stall at ~88 (the "connecting" hold).
        const target = ready ? 100 : 88;
        const next = p + (target - p) * (1 - Math.exp(-3.4 * dt));
        if (ready && next > 99 && !done.current) {
          window.setTimeout(() => finish.current(), 200);
          return 100;
        }
        return next;
      });
      if (!done.current) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [ready]);

  return (
    <div className={`${styles.loader} ${hidden ? styles.loaderHidden : ""}`} aria-hidden={hidden}>
      <div className={styles.loaderMark}>
        <span className={styles.brandDot} aria-hidden />
        Caseline
      </div>
      <div className={styles.loaderBarTrack}>
        <motion.div
          className={styles.loaderBar}
          style={{ scaleX: progress / 100 }}
          transition={{ ease: "linear" }}
        />
      </div>
      <div className={styles.loaderMeta}>
        <span>{ready ? "Ready" : "Connecting"}</span>
        <span>{Math.round(progress)}%</span>
      </div>
    </div>
  );
}
