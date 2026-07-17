"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ComponentType } from "react";
import styles from "./kit.module.css";

/**
 * Neomorphic sidebar link. Raised-on-hover, **pressed/inset when active** so
 * you can feel where you are (§6). Active detection: exact match for the
 * overview root, prefix match for the rest. Renders a real `aria-current`.
 */
export default function NavItem({
  href,
  label,
  icon: Icon,
}: {
  href: string;
  label: string;
  icon: ComponentType<{ size?: number; className?: string; "aria-hidden"?: boolean }>;
}) {
  const pathname = usePathname();
  const active = href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
  return (
    <Link
      href={href}
      className={`${styles.navItem} ${active ? styles.navItemActive : ""}`}
      aria-current={active ? "page" : undefined}
    >
      <Icon size={17} className={styles.navIcon} aria-hidden />
      <span className={styles.navLabel}>{label}</span>
    </Link>
  );
}
