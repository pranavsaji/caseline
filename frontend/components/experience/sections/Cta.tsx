"use client";

import styles from "../experience.module.css";
import { Reveal, RevealWords } from "../ui/Reveal";
import { MagneticButton } from "../ui/MagneticButton";

/**
 * Section 6 — the closing call to action. Camera recenters on the orb glowing
 * dead-center. Primary conversion: book a demo. Secondary: see the live
 * dashboard the intake feeds into (links back into the app).
 */
export function Cta() {
  return (
    <section
      id="cta"
      className={styles.section}
      style={{ alignItems: "center", textAlign: "center" }}
      aria-label="Get started"
    >
      <div className={styles.sectionInner} style={{ margin: "0 auto" }}>
        <Reveal as="p" className={styles.eyebrow} delay={0.1}>
          Get started
        </Reveal>
        <h2 className={styles.h2}>
          <RevealWords text="Put Caseline on the phones." />
        </h2>
        <Reveal as="p" className={styles.lede} delay={0.3} >
          <span style={{ marginInline: "auto", display: "block" }}>
            See it answer a live call with your intake rules loaded. Fifteen
            minutes, no scripts, no commitment.
          </span>
        </Reveal>
        <Reveal className={styles.ctaRow} delay={0.5} >
          <div style={{ margin: "2.4rem auto 0", display: "flex", gap: "1rem", flexWrap: "wrap", justifyContent: "center" }}>
            <MagneticButton href="mailto:hello@caseline.ai?subject=Caseline%20demo">
              Book a demo
            </MagneticButton>
            <MagneticButton variant="ghost" href="/">
              Open the dashboard
            </MagneticButton>
          </div>
        </Reveal>
      </div>
    </section>
  );
}
