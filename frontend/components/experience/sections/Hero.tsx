"use client";

import { motion } from "framer-motion";
import styles from "../experience.module.css";
import { Reveal, RevealWords } from "../ui/Reveal";
import { MagneticButton } from "../ui/MagneticButton";
import { scrollToId } from "../lib/scrollToId";

/** Section 1 — the immersive hero. Copy sits low-left over the orb. */
export function Hero() {
  return (
    <section id="hero" className={styles.section} aria-label="Introduction">
      <div className={styles.sectionInner}>
        <Reveal as="p" className={styles.eyebrow} delay={0.1}>
          It never misses a call
        </Reveal>
        <h1 className={styles.display}>
          <RevealWords text="The voice that answers" />
          <br />
          <span className={styles.accent}>
            <RevealWords text="when your firm can't." />
          </span>
        </h1>
        <Reveal as="p" className={styles.lede} delay={0.5}>
          Caseline is an AI intake employee for law firms. It picks up in a natural
          voice, qualifies the lead against your rules, and books the consult —
          day or night, on the first ring.
        </Reveal>
        <Reveal className={styles.ctaRow} delay={0.7}>
          <MagneticButton onClick={() => scrollToId("cta")}>Book a demo</MagneticButton>
          <MagneticButton variant="ghost" onClick={() => scrollToId("demo")}>
            Hear it answer
          </MagneticButton>
        </Reveal>
      </div>

      <motion.div
        className={styles.scrollHint}
        initial={{ opacity: 0 }}
        animate={{ opacity: 0.75 }}
        transition={{ delay: 1.4, duration: 1 }}
      >
        <span>Scroll</span>
        <span className={styles.scrollLine} aria-hidden />
      </motion.div>
    </section>
  );
}
