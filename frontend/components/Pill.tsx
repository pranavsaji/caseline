import type { ReactNode } from "react";
import styles from "./kit.module.css";

export type PillTone = "ok" | "warn" | "bad" | "info" | "muted";

/**
 * Solid, high-contrast status pill. Deliberately NOT neomorphic (uiplan.md §1):
 * status must stay legible, so pills keep saturated fills and sit on top of the
 * soft surfaces. Maps 1:1 onto the existing `.pill.ok/.warn/.bad/.muted` vocab.
 */
export default function Pill({
  tone = "muted",
  dot = false,
  children,
}: {
  tone?: PillTone;
  dot?: boolean;
  children: ReactNode;
}) {
  return (
    <span className={`${styles.pill} ${styles[tone]}`}>
      {dot ? <span className={styles.pillDot} aria-hidden /> : null}
      {children}
    </span>
  );
}
