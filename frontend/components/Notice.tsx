import type { ReactNode } from "react";
import { AlertTriangle, CheckCircle2, Info, XCircle } from "lucide-react";
import styles from "./kit.module.css";

export type NoticeTone = "ok" | "bad" | "info" | "warn";

const ICON = {
  ok: CheckCircle2,
  bad: XCircle,
  info: Info,
  warn: AlertTriangle,
} as const;

const TONE_CLASS = {
  ok: styles.noticeOk,
  bad: styles.noticeBad,
  info: styles.noticeInfo,
  warn: styles.noticeWarn,
} as const;

/**
 * Soft inset callout with a tone icon + accent stripe. Use `title` for a
 * heading; pass mono/JSON children for collapsible State dumps (§9 threads).
 */
export default function Notice({
  tone = "info",
  title,
  icon = true,
  children,
}: {
  tone?: NoticeTone;
  title?: ReactNode;
  icon?: boolean;
  children?: ReactNode;
}) {
  const Icon = ICON[tone];
  return (
    <div className={`${styles.notice} ${TONE_CLASS[tone]}`} role="note">
      {icon ? (
        <span className={styles.noticeIcon}>
          <Icon size={17} aria-hidden />
        </span>
      ) : null}
      <div>
        {title ? <p className={styles.noticeTitle}>{title}</p> : null}
        {children ? <div className={styles.noticeBody}>{children}</div> : null}
      </div>
    </div>
  );
}
