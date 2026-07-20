"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  BarChart3,
  Braces,
  LayoutGrid,
  MessagesSquare,
  Share2,
  SlidersHorizontal,
  PencilRuler,
  PhoneCall,
  Activity,
} from "lucide-react";
import type { ComponentType } from "react";
import styles from "./kit.module.css";

/** Icon components stay on the client side of the boundary — server components
 *  can't hand a function prop to a client component, so we key by name. */
const ICONS: Record<string, ComponentType<{ size?: number; className?: string; "aria-hidden"?: boolean }>> = {
  overview: LayoutGrid,
  calls: PhoneCall,
  threads: MessagesSquare,
  analytics: BarChart3,
  tuning: SlidersHorizontal,
  referrals: Share2,
  studio: PencilRuler,
  ops: Activity,
  config: Braces,
};

/**
 * Neomorphic sidebar link. Raised-on-hover, **pressed/inset when active** so
 * you can feel where you are (§6). Active detection: exact match, or a prefix
 * match on the next path segment. Renders a real `aria-current`.
 */
export default function NavItem({
  href,
  label,
  icon,
}: {
  href: string;
  label: string;
  icon: string;
}) {
  const pathname = usePathname();
  const active = pathname === href || pathname.startsWith(`${href}/`);
  const Icon = ICONS[icon] ?? LayoutGrid;
  return (
    <Link
      href={href}
      className={`${styles.navItem} ${active ? styles.navItemActive : ""}`}
      aria-current={active ? "page" : undefined}
      aria-label={label}
    >
      <Icon size={17} className={styles.navIcon} aria-hidden />
      <span className={styles.navLabel}>{label}</span>
    </Link>
  );
}
