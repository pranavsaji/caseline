import type { ReactNode } from "react";
import styles from "./kit.module.css";

/**
 * Raised neomorphic container (`--nm-raised`) with an optional title + actions
 * slot. To nest another raised control inside, wrap it in a `<Well>` first —
 * raised-in-raised without an inset buffer makes the shadows fight (§4 rule 2).
 */
export default function Card({
  title,
  actions,
  className,
  children,
}: {
  title?: ReactNode;
  actions?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section className={className ? `${styles.card} ${className}` : styles.card}>
      {(title || actions) && (
        <header className={styles.cardHeader}>
          {title ? <h2 className={styles.cardTitle}>{title}</h2> : <span />}
          {actions ? <div className={styles.cardActions}>{actions}</div> : null}
        </header>
      )}
      {children}
    </section>
  );
}

/** Inset "well" — the buffer that keeps nested raised controls from clashing. */
export function Well({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={className ? `${styles.well} ${className}` : styles.well}>{children}</div>;
}
