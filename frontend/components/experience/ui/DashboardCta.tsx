"use client";

import styles from "../experience.module.css";

/**
 * The route from the public marketing landing into the product. `/dashboard` is
 * gated, so an unauthenticated visitor following this lands on `/login` and is
 * returned to the dashboard once signed in — no dead end either way.
 *
 * Repeated at the end of each section (plus the topbar, hero, closing CTA, and
 * footer) so the way into the app is never more than a screen away.
 */
export const DASHBOARD_HREF = "/dashboard";

export function SectionCta({ label = "Go to dashboard" }: { label?: string }) {
  return (
    <a className={styles.sectionCta} href={DASHBOARD_HREF}>
      {label}
      <span aria-hidden>→</span>
    </a>
  );
}
