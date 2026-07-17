import type { ReactNode } from "react";
import styles from "./kit.module.css";

/**
 * Raised readout: a big tabular number + label, with an optional footer line.
 * Use for counts and rates that carry no SLO health signal (booked today,
 * qualification %). For latency/SLO metrics use <PulseTile> instead.
 */
export default function StatTile({
  label,
  value,
  unit,
  footer,
}: {
  label: ReactNode;
  value: ReactNode;
  unit?: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <div className={styles.stat}>
      <span className={styles.statLabel}>{label}</span>
      <span className={styles.statValue}>
        {value}
        {unit ? <span className={styles.statUnit}>{unit}</span> : null}
      </span>
      {footer ? <span className={styles.statFooter}>{footer}</span> : null}
    </div>
  );
}
