"use client";

import styles from "../experience.module.css";
import { SectionCta } from "../ui/DashboardCta";
import { Reveal, RevealWords } from "../ui/Reveal";

/** Section 2 — brand introduction. Camera has pulled back; copy sits right. */
export function Intro() {
  return (
    <section
      id="intro"
      className={`${styles.section} ${styles.alignRight}`}
      aria-label="What Caseline is"
    >
      <div className={styles.sectionInner}>
        <Reveal as="p" className={styles.eyebrow}>
          The intake employee
        </Reveal>
        <h2 className={styles.h2}>
          <RevealWords text="A missed call is a" />{" "}
          <span className={styles.violet}>
            <RevealWords text="missed case." />
          </span>
        </h2>
        <Reveal as="p" className={styles.lede} delay={0.3}>
          Most firms lose a third of their leads to voicemail and slow callbacks.
          Caseline answers every one instantly — with the composure of your best
          front-desk hire and the consistency of software.
        </Reveal>
        <SectionCta />
      </div>
    </section>
  );
}
