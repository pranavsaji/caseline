import type { TextareaHTMLAttributes, ReactNode } from "react";
import { useId } from "react";
import styles from "../kit.module.css";

/**
 * Inset textarea. Defaults to the mono face (JSON/script editing on
 * /config and /studio); pass `mono={false}` for prose. `invalid` renders the
 * red inset validation ring used by the Agent Config JSON editors.
 */
export default function SoftTextarea({
  label,
  hint,
  error,
  invalid,
  mono = true,
  className,
  id,
  ...rest
}: {
  label?: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  invalid?: boolean;
  mono?: boolean;
} & TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const autoId = useId();
  const areaId = id ?? autoId;
  const isInvalid = invalid || Boolean(error);
  const cls = [
    styles.control,
    styles.textarea,
    mono ? styles.controlMono : "",
    isInvalid ? styles.controlInvalid : "",
    className ?? "",
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <div className={styles.field}>
      {label ? (
        <label className={styles.label} htmlFor={areaId}>
          {label}
        </label>
      ) : null}
      <textarea id={areaId} aria-invalid={isInvalid || undefined} className={cls} {...rest} />
      {error ? (
        <span className={`${styles.hint} ${styles.hintError}`}>{error}</span>
      ) : hint ? (
        <span className={styles.hint}>{hint}</span>
      ) : null}
    </div>
  );
}
