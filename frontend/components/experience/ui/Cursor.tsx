"use client";

import { useEffect } from "react";
import { motion, useMotionValue, useSpring } from "framer-motion";
import styles from "../experience.module.css";

/**
 * A two-part custom cursor: a small solid dot that tracks 1:1 and a larger
 * ring that lags via a spring, growing when hovering interactive elements
 * (anything tagged with `data-cursor="hover"`, plus links/buttons). Rendered
 * only on fine-pointer devices — hidden via CSS on coarse pointers.
 */
export function Cursor() {
  const x = useMotionValue(-100);
  const y = useMotionValue(-100);
  const rx = useSpring(x, { stiffness: 400, damping: 30, mass: 0.5 });
  const ry = useSpring(y, { stiffness: 400, damping: 30, mass: 0.5 });
  const scale = useMotionValue(1);
  const sScale = useSpring(scale, { stiffness: 300, damping: 20 });

  useEffect(() => {
    const move = (e: PointerEvent) => {
      x.set(e.clientX);
      y.set(e.clientY);
      const el = e.target as HTMLElement | null;
      const interactive = el?.closest(
        'a,button,[data-cursor="hover"],input,textarea',
      );
      scale.set(interactive ? 2 : 1);
    };
    window.addEventListener("pointermove", move, { passive: true });
    return () => window.removeEventListener("pointermove", move);
  }, [x, y, scale]);

  return (
    <>
      <motion.div className={styles.cursor} style={{ x: rx, y: ry, scale: sScale }} aria-hidden />
      <motion.div className={styles.cursorDot} style={{ x, y }} aria-hidden />
    </>
  );
}
