"use client";

import styles from "../experience.module.css";
import { SectionCta } from "../ui/DashboardCta";
import { Reveal } from "../ui/Reveal";

const FEATURES = [
  {
    n: "01",
    title: "Answers in a natural voice",
    body: "Sub-second turn latency over a real telephony trunk. Callers hear a warm, human cadence — not a menu, not a beep, not hold music.",
  },
  {
    n: "02",
    title: "Qualifies against your rules",
    body: "Practice area, jurisdiction, statute of limitations, conflict checks. Caseline runs your firm's intake logic on every call and flags what matters.",
  },
  {
    n: "03",
    title: "Books the consult",
    body: "Qualified leads get a calendar slot before they hang up. The rest are captured, tagged, and routed — nothing slips to voicemail.",
  },
  {
    n: "04",
    title: "Syncs a clean record",
    body: "Structured intake writes straight into Clio, Filevine, or Litify. Your team opens the matter already filled in, with the transcript attached.",
  },
];

/** Section 3 — scroll-driven feature storytelling as the camera orbits. */
export function Features() {
  return (
    <section id="features" className={styles.section} aria-label="How Caseline works">
      <div className={`${styles.sectionInner} ${styles.wide}`}>
        <Reveal as="p" className={styles.eyebrow}>
          How it works
        </Reveal>
        <div className={styles.features}>
          {FEATURES.map((f, i) => (
            <Reveal key={f.n} className={styles.feature} delay={i * 0.05}>
              <span className={styles.featureNum}>{f.n}</span>
              <div>
                <h3 className={styles.featureTitle}>{f.title}</h3>
                <p className={styles.featureBody}>{f.body}</p>
              </div>
            </Reveal>
          ))}
        </div>
        <SectionCta />
      </div>
    </section>
  );
}
