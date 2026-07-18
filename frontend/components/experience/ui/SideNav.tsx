"use client";

import { useEffect, useState } from "react";
import styles from "../experience.module.css";
import { subscribeSection, experience } from "../lib/store";
import { EXPERIENCE_SECTIONS } from "../lib/sections";
import { scrollToId } from "../lib/scrollToId";

/** Fixed progress dots — one per section, active dot tracks the camera path. */
export function SideNav() {
  const [active, setActive] = useState(experience.section);
  useEffect(() => subscribeSection(setActive), []);

  return (
    <nav className={styles.dots} aria-label="Section navigation">
      {EXPERIENCE_SECTIONS.map((s, i) => (
        <button
          key={s.id}
          type="button"
          className={`${styles.dot} ${i === active ? styles.dotActive : ""}`}
          aria-label={`Go to ${s.eyebrow}`}
          aria-current={i === active}
          onClick={() => scrollToId(s.id)}
        />
      ))}
    </nav>
  );
}
