import type { ComponentType, ReactNode } from "react";
import { Inbox } from "lucide-react";
import styles from "./kit.module.css";

/**
 * Friendly empty state (§8): a soft icon medallion, a title, an inviting line
 * of copy, and one clear action — never a bare "no data" blank.
 */
export default function EmptyState({
  icon: Icon = Inbox,
  title,
  children,
  action,
}: {
  icon?: ComponentType<{ size?: number; "aria-hidden"?: boolean }>;
  title: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className={styles.empty}>
      <span className={styles.emptyIcon}>
        <Icon size={24} aria-hidden />
      </span>
      <p className={styles.emptyTitle}>{title}</p>
      {children ? <p className={styles.emptyText}>{children}</p> : null}
      {action ? <div className={styles.emptyAction}>{action}</div> : null}
    </div>
  );
}
