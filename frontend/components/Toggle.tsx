import type { InputHTMLAttributes, ReactNode } from "react";
import { useId } from "react";
import styles from "./kit.module.css";

/**
 * Neomorphic switch built on a real `<input type="checkbox" role="switch">`
 * (§7) — never a div — so it's keyboard-operable and screen-reader-correct.
 * The track is an inset well; the thumb lifts (flat shadow) and slides to the
 * accent fill when checked. Focus renders a real ring (shadows are invisible
 * to keyboard users).
 */
export default function Toggle({
  label,
  id,
  className,
  ...rest
}: {
  label?: ReactNode;
} & InputHTMLAttributes<HTMLInputElement>) {
  const autoId = useId();
  const inputId = id ?? autoId;
  return (
    <label className={className ? `${styles.toggle} ${className}` : styles.toggle} htmlFor={inputId}>
      <input id={inputId} type="checkbox" role="switch" {...rest} />
      <span className={styles.toggleTrack}>
        <span className={styles.toggleThumb} />
      </span>
      {label ? <span className={styles.toggleLabel}>{label}</span> : null}
    </label>
  );
}
