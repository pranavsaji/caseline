"use client";

import styles from "../experience.module.css";

/** Section 7 — minimal footer. */
export function Footer() {
  return (
    <footer className={styles.footer}>
      <span>© {"2026"} Caseline — AI intake for law firms</span>
      <span style={{ display: "inline-flex", gap: "1.4rem" }}>
        <a href="/">Dashboard</a>
        <a href="mailto:hello@caseline.ai">Contact</a>
        <a href="#hero">Back to top</a>
      </span>
    </footer>
  );
}
