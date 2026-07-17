import type { ButtonHTMLAttributes, ReactNode } from "react";
import styles from "./kit.module.css";

type Variant = "default" | "primary" | "danger";

/**
 * Neomorphic button: raised at rest, lifts on hover, presses inset on `:active`.
 * `variant="primary"` gets the accent fill + on-accent text (contrast-safe) so
 * the affordance never relies on shadow alone (§11). Forwards all native button
 * props (onClick, type, disabled, aria-*), so it works in server or client trees.
 */
export default function SoftButton({
  variant = "default",
  size = "md",
  block = false,
  className,
  children,
  ...rest
}: {
  variant?: Variant;
  size?: "sm" | "md";
  block?: boolean;
  children: ReactNode;
} & ButtonHTMLAttributes<HTMLButtonElement>) {
  const cls = [
    styles.btn,
    variant === "primary" ? styles.btnPrimary : "",
    variant === "danger" ? styles.btnDanger : "",
    size === "sm" ? styles.btnSm : "",
    block ? styles.btnBlock : "",
    className ?? "",
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <button type="button" {...rest} className={cls}>
      {children}
    </button>
  );
}
