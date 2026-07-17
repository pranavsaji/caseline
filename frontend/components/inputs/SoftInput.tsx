import type { InputHTMLAttributes, ReactNode } from "react";
import { useId } from "react";
import styles from "../kit.module.css";

/**
 * Inset text field with an accent focus ring. `invalid` renders a red inset
 * ring (non-shadow cue) plus an optional error hint. Wrap in the built-in
 * label/hint scaffolding or drop the bare control in with `label` omitted.
 */
export default function SoftInput({
  label,
  hint,
  error,
  invalid,
  mono,
  className,
  id,
  ...rest
}: {
  label?: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  invalid?: boolean;
  mono?: boolean;
} & InputHTMLAttributes<HTMLInputElement>) {
  const autoId = useId();
  const inputId = id ?? autoId;
  const isInvalid = invalid || Boolean(error);
  const cls = [
    styles.control,
    mono ? styles.controlMono : "",
    isInvalid ? styles.controlInvalid : "",
    className ?? "",
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <div className={styles.field}>
      {label ? (
        <label className={styles.label} htmlFor={inputId}>
          {label}
        </label>
      ) : null}
      <input id={inputId} aria-invalid={isInvalid || undefined} className={cls} {...rest} />
      {error ? (
        <span className={`${styles.hint} ${styles.hintError}`}>{error}</span>
      ) : hint ? (
        <span className={styles.hint}>{hint}</span>
      ) : null}
    </div>
  );
}
