"use client";

import { useRef, type ReactNode } from "react";
import { motion, useMotionValue, useSpring, useReducedMotion } from "framer-motion";
import styles from "../experience.module.css";

type Props = {
  children: ReactNode;
  href?: string;
  onClick?: () => void;
  variant?: "solid" | "ghost";
  strength?: number;
};

/**
 * A magnetic button: the label is pulled toward the cursor while hovering and
 * springs back on leave. Works as an anchor (href) or a button (onClick).
 * Fully disabled under reduced-motion — it renders a plain, static control.
 */
export function MagneticButton({
  children,
  href,
  onClick,
  variant = "solid",
  strength = 0.4,
}: Props) {
  const reduced = useReducedMotion();
  const ref = useRef<HTMLDivElement>(null);
  const x = useMotionValue(0);
  const y = useMotionValue(0);
  const sx = useSpring(x, { stiffness: 180, damping: 15, mass: 0.4 });
  const sy = useSpring(y, { stiffness: 180, damping: 15, mass: 0.4 });

  const onMove = (e: React.PointerEvent) => {
    if (reduced || !ref.current) return;
    const r = ref.current.getBoundingClientRect();
    x.set((e.clientX - (r.left + r.width / 2)) * strength);
    y.set((e.clientY - (r.top + r.height / 2)) * strength);
  };
  const reset = () => {
    x.set(0);
    y.set(0);
  };

  const cls = `${styles.btn} ${variant === "ghost" ? styles.btnGhost : ""}`;
  const inner = (
    <>
      {children}
      <span className={styles.btnArrow} aria-hidden>
        →
      </span>
    </>
  );

  return (
    <motion.div
      ref={ref}
      className={styles.magneticWrap}
      style={reduced ? undefined : { x: sx, y: sy }}
      onPointerMove={onMove}
      onPointerLeave={reset}
    >
      {href ? (
        <a className={cls} href={href} target="_blank" rel="noreferrer">
          {inner}
        </a>
      ) : (
        <button className={cls} type="button" onClick={onClick}>
          {inner}
        </button>
      )}
    </motion.div>
  );
}
