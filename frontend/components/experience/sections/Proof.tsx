"use client";

import { useEffect, useRef, useState } from "react";
import { useInView } from "framer-motion";
import styles from "../experience.module.css";
import { SectionCta } from "../ui/DashboardCta";
import { Reveal } from "../ui/Reveal";

type Metric = { value: number; unit?: string; decimals?: number; label: string };

const METRICS: Metric[] = [
  { value: 0.6, unit: "s", decimals: 1, label: "Median lead-to-first-contact, verified in live smoke tests" },
  { value: 100, unit: "%", label: "Of after-hours calls answered — no voicemail, no queue" },
  { value: 12, unit: "/12", label: "Differentiation-suite live checks passing on the last run" },
  { value: 3, unit: "×", label: "Case-management systems supported: Clio, Filevine, Litify" },
];

/** Counts up to `value` once the metric scrolls into view. */
function Counter({ value, unit, decimals = 0 }: Metric) {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true, margin: "-20%" });
  const [n, setN] = useState(0);

  useEffect(() => {
    if (!inView) return;
    let raf = 0;
    const start = performance.now();
    const dur = 1400;
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / dur);
      const eased = 1 - Math.pow(1 - t, 3);
      setN(value * eased);
      if (t < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [inView, value]);

  return (
    <div ref={ref} className={styles.metricValue}>
      {n.toFixed(decimals)}
      {unit && <span className={styles.unit}>{unit}</span>}
    </div>
  );
}

/** Section 5 — proof / metrics as the camera rises over the particle field. */
export function Proof() {
  return (
    <section id="proof" className={styles.section} aria-label="Proof and metrics">
      <div className={`${styles.sectionInner} ${styles.wide}`}>
        <Reveal as="p" className={styles.eyebrow}>
          Proof
        </Reveal>
        <h2 className={styles.h2}>Instrumented from the first ring.</h2>
        <div className={styles.metrics}>
          {METRICS.map((m) => (
            <Reveal key={m.label}>
              <Counter {...m} />
              <p className={styles.metricLabel}>{m.label}</p>
            </Reveal>
          ))}
        </div>
        <SectionCta />
      </div>
    </section>
  );
}
