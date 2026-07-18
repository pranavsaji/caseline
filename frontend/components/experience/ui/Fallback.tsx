"use client";

import styles from "../experience.module.css";

/**
 * Static poster shown when WebGL is unavailable. No canvas, no animation loop —
 * just a CSS-lit deep-space field with a glowing orb, so the content below
 * still reads cleanly and nothing is blank. The scrolling content renders on
 * top of this exactly as it does over the live scene.
 */
export function Fallback() {
  return (
    <div className={styles.fallback} aria-hidden>
      <div className={styles.fallbackOrb} />
    </div>
  );
}
