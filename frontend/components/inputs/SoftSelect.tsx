import type { SelectHTMLAttributes, ReactNode } from "react";
import { useId } from "react";
import { ChevronDown } from "lucide-react";
import styles from "../kit.module.css";

/**
 * Inset select with a custom chevron (native appearance stripped). Same
 * inset well + accent focus ring as the other fields so form rows stay
 * visually consistent.
 */
export default function SoftSelect({
  label,
  hint,
  className,
  id,
  children,
  ...rest
}: {
  label?: ReactNode;
  hint?: ReactNode;
} & SelectHTMLAttributes<HTMLSelectElement>) {
  const autoId = useId();
  const selectId = id ?? autoId;
  const cls = [styles.control, styles.select, className ?? ""].filter(Boolean).join(" ");
  return (
    <div className={styles.field}>
      {label ? (
        <label className={styles.label} htmlFor={selectId}>
          {label}
        </label>
      ) : null}
      <div className={styles.selectWrap}>
        <select id={selectId} className={cls} {...rest}>
          {children}
        </select>
        <ChevronDown size={16} className={styles.selectChevron} aria-hidden />
      </div>
      {hint ? <span className={styles.hint}>{hint}</span> : null}
    </div>
  );
}
