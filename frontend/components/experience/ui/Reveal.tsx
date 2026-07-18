"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { motion, useInView, useReducedMotion } from "framer-motion";
import styles from "../experience.module.css";

/**
 * Whether an element has scrolled into view, with a hard fallback: some
 * embedded/automation browsers throttle IntersectionObserver, which would
 * otherwise leave reveal content stuck hidden. The timer guarantees the
 * content resolves visible within ~1.1s regardless. `once` semantics.
 */
function useRevealed<T extends Element>(ref: React.RefObject<T | null>) {
  const inView = useInView(ref, { once: true, margin: "-12% 0px -12% 0px" });
  const [fallback, setFallback] = useState(false);
  useEffect(() => {
    const t = window.setTimeout(() => setFallback(true), 1100);
    return () => clearTimeout(t);
  }, []);
  return inView || fallback;
}

/**
 * Scroll-synchronized reveal. Children rise + fade in when the element enters
 * the viewport, staggered by `delay`. Under reduced-motion everything is shown
 * immediately with no transform. Used for text and blocks throughout the page
 * so copy resolves in time with the camera settling on each section.
 */
export function Reveal({
  children,
  delay = 0,
  as = "div",
  className,
}: {
  children: ReactNode;
  delay?: number;
  as?: "div" | "h1" | "h2" | "p" | "span" | "li";
  className?: string;
}) {
  const reduced = useReducedMotion();
  const ref = useRef<HTMLDivElement>(null);
  const shown = useRevealed(ref);
  const MotionTag = motion[as] as typeof motion.div;

  if (reduced) {
    const Tag = as;
    return <Tag className={className}>{children}</Tag>;
  }

  return (
    <MotionTag
      ref={ref}
      className={className}
      initial={{ opacity: 0, y: 26, filter: "blur(6px)" }}
      animate={shown ? { opacity: 1, y: 0, filter: "blur(0px)" } : undefined}
      transition={{ duration: 0.9, delay, ease: [0.16, 1, 0.3, 1] }}
    >
      {children}
    </MotionTag>
  );
}

/** Splits a line into words that stagger in — for hero headlines. */
export function RevealWords({ text, className }: { text: string; className?: string }) {
  const reduced = useReducedMotion();
  const ref = useRef<HTMLSpanElement>(null);
  const shown = useRevealed(ref);
  if (reduced) return <span className={className}>{text}</span>;
  const words = text.split(" ");
  return (
    <span ref={ref} className={className} style={{ display: "inline" }}>
      {words.map((w, i) => (
        <span
          key={i}
          style={{
            display: "inline-block",
            overflow: "hidden",
            verticalAlign: "top",
            // Give descenders (y, g, p) room inside the clip box, then pull the
            // extra height back so line layout is unchanged.
            paddingBottom: "0.2em",
            marginBottom: "-0.2em",
          }}
        >
          <motion.span
            style={{ display: "inline-block" }}
            initial={{ y: "110%" }}
            animate={shown ? { y: "0%" } : undefined}
            transition={{ duration: 0.8, delay: i * 0.06, ease: [0.16, 1, 0.3, 1] }}
          >
            {w}
            {i < words.length - 1 ? " " : ""}
          </motion.span>
        </span>
      ))}
    </span>
  );
}

export { styles as experienceStyles };
