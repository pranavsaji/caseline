import type { ReactNode } from "react";
import styles from "./kit.module.css";

/**
 * A single conversation turn as a chat bubble (§9). Agent turns are raised and
 * accent-tinted, aligned to the start; caller turns are inset, aligned to the
 * end — so the material itself distinguishes who is speaking. `meta` carries a
 * timestamp or per-turn latency; `tag` carries a guardrail/status pill.
 */
export default function TranscriptTurn({
  role,
  speaker = role === "assistant" || role === "agent" ? "agent" : "caller",
  meta,
  tag,
  children,
}: {
  role: string;
  /** Override the raised/inset side; inferred from `role` by default. */
  speaker?: "agent" | "caller";
  meta?: ReactNode;
  tag?: ReactNode;
  children: ReactNode;
}) {
  const isAgent = speaker === "agent";
  return (
    <div className={`${styles.turn} ${isAgent ? styles.turnAgent : styles.turnCaller}`}>
      <span className={styles.turnRole}>
        {role}
        {tag}
      </span>
      <div className={styles.turnBody}>{children}</div>
      {meta ? <span className={styles.turnMeta}>{meta}</span> : null}
    </div>
  );
}

/** Flex column that lets agent/caller bubbles align to opposite sides. */
export function TranscriptList({ children }: { children: ReactNode }) {
  return <div className={styles.turnList}>{children}</div>;
}
