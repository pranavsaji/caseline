"use client";

import type { InputHTMLAttributes, ReactNode } from "react";
import { useId, useState } from "react";
import { Eye, EyeOff } from "lucide-react";
import styles from "../kit.module.css";

/**
 * Inset text field with an accent focus ring. `invalid` renders a red inset
 * ring (non-shadow cue) plus an optional error hint. Wrap in the built-in
 * label/hint scaffolding or drop the bare control in with `label` omitted.
 *
 * Password fields (`type="password"`) automatically get a show/hide eye toggle
 * inside the right edge — toggling swaps the control to `type="text"` so the
 * value is visible. Pass `revealable={false}` to opt out.
 */
export default function SoftInput({
  label,
  hint,
  error,
  invalid,
  mono,
  className,
  id,
  type,
  revealable = true,
  ...rest
}: {
  label?: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  invalid?: boolean;
  mono?: boolean;
  revealable?: boolean;
} & InputHTMLAttributes<HTMLInputElement>) {
  const autoId = useId();
  const inputId = id ?? autoId;
  const isInvalid = invalid || Boolean(error);
  const canReveal = type === "password" && revealable;
  const [revealed, setRevealed] = useState(false);
  // When revealed, swap to a text input so the value shows.
  const effectiveType = canReveal && revealed ? "text" : type;
  const cls = [
    styles.control,
    mono ? styles.controlMono : "",
    isInvalid ? styles.controlInvalid : "",
    className ?? "",
  ]
    .filter(Boolean)
    .join(" ");

  const input = (
    <input
      id={inputId}
      type={effectiveType}
      aria-invalid={isInvalid || undefined}
      className={cls}
      {...rest}
    />
  );

  return (
    <div className={styles.field}>
      {label ? (
        <label className={styles.label} htmlFor={inputId}>
          {label}
        </label>
      ) : null}
      {canReveal ? (
        <div className={styles.inputWrap}>
          {input}
          <button
            type="button"
            className={styles.revealBtn}
            onClick={() => setRevealed((v) => !v)}
            aria-label={revealed ? "Hide password" : "Show password"}
            aria-pressed={revealed}
            tabIndex={-1}
          >
            {revealed ? <EyeOff size={16} aria-hidden /> : <Eye size={16} aria-hidden />}
          </button>
        </div>
      ) : (
        input
      )}
      {error ? (
        <span className={`${styles.hint} ${styles.hintError}`}>{error}</span>
      ) : hint ? (
        <span className={styles.hint}>{hint}</span>
      ) : null}
    </div>
  );
}
