import type { ReactNode } from "react";
import styles from "./kit.module.css";

/**
 * The at-a-glance summary row (§6): a responsive grid of StatTiles / PulseTiles
 * that every list & analytics page opens with, so a partner sees health before
 * raw rows. Auto-fits columns down to a single column on narrow screens.
 */
export default function TileRow({ children }: { children: ReactNode }) {
  return <div className={styles.tileRow}>{children}</div>;
}
