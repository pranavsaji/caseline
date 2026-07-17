import type { ReactNode } from "react";
import styles from "./kit.module.css";
import Pill from "./Pill";

export type PulseStatus = "ok" | "warn" | "bad";

/**
 * Derive health from a value against an SLO budget. Lower-is-better metrics
 * (latency, speed-to-lead) breach when they exceed the budget; higher-is-better
 * metrics (contact rate) breach when they fall below it. `warnRatio` is the
 * fraction of the budget at which we start flagging amber (default 0.8 of a
 * lower-is-better budget → warn once within 20% of the ceiling).
 */
export function pulseStatus(
  value: number | null | undefined,
  budget: number,
  { higherIsBetter = false, warnRatio = 0.8 }: { higherIsBetter?: boolean; warnRatio?: number } = {},
): PulseStatus | null {
  if (value == null || Number.isNaN(value)) return null;
  if (higherIsBetter) {
    if (value >= budget) return "ok";
    if (value >= budget * warnRatio) return "warn";
    return "bad";
  }
  if (value <= budget * warnRatio) return "ok";
  if (value <= budget) return "warn";
  return "bad";
}

const STATUS_CLASS: Record<PulseStatus, string> = {
  ok: styles.pulseOk,
  warn: styles.pulseWarn,
  bad: styles.pulseBad,
};

const STATUS_LABEL: Record<PulseStatus, string> = {
  ok: "Within budget",
  warn: "Near budget",
  bad: "Over budget",
};

/**
 * The signature element (uiplan.md §1). An SLO-aware readout whose *material*
 * expresses health: healthy sits raised with a breathing glow, near-budget
 * breathes amber, breached sits pressed/inset and recessed. Pass an explicit
 * `status`, or `value` + `budget` and let it compute. Falls back to a neutral
 * raised StatTile when there's no data.
 */
export default function PulseTile({
  label,
  value,
  unit,
  status,
  budget,
  higherIsBetter,
  warnRatio,
  hint,
  showBadge = true,
}: {
  label: ReactNode;
  value: ReactNode;
  unit?: ReactNode;
  status?: PulseStatus | null;
  budget?: number;
  higherIsBetter?: boolean;
  warnRatio?: number;
  hint?: ReactNode;
  showBadge?: boolean;
}) {
  let health: PulseStatus | null = status ?? null;
  if (health == null && budget != null && typeof value === "number") {
    health = pulseStatus(value, budget, { higherIsBetter, warnRatio });
  }

  // No health signal → neutral raised readout (never masquerade as healthy).
  const stateClass = health ? STATUS_CLASS[health] : styles.pulseNone;
  const badgeTone = health === "bad" ? "bad" : health === "warn" ? "warn" : "ok";

  return (
    <div className={`${styles.pulse} ${stateClass}`} data-status={health ?? "none"}>
      <div className={styles.pulseHead}>
        <span className={styles.statLabel}>{label}</span>
        {showBadge && health ? (
          <Pill tone={badgeTone} dot>
            {STATUS_LABEL[health]}
          </Pill>
        ) : null}
      </div>
      <span className={styles.pulseValue}>
        {value}
        {unit ? <span className={styles.pulseUnit}>{unit}</span> : null}
      </span>
      {hint ? <span className={styles.statFooter}>{hint}</span> : null}
    </div>
  );
}
