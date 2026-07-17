import type { ReactNode } from "react";
import NavItem from "./NavItem";
import ThemeToggle from "./ThemeToggle";
import styles from "./kit.module.css";

/**
 * The molded control-panel chrome (§6): a raised soft sidebar (desktop) that
 * collapses to a horizontal scrolling top bar on mobile, with the theme toggle
 * pinned in the footer. Replaces the flat top nav from `layout.tsx` in Phase 2;
 * data layer and children stay untouched. Server component — the only client
 * islands are <NavItem> (active-route) and <ThemeToggle>.
 */
const NAV = [
  { href: "/", label: "Overview", icon: "overview" },
  { href: "/threads", label: "Threads", icon: "threads" },
  { href: "/analytics", label: "Analytics", icon: "analytics" },
  { href: "/tuning", label: "Tuning", icon: "tuning" },
  { href: "/referrals", label: "Referrals", icon: "referrals" },
  { href: "/studio", label: "Studio", icon: "studio" },
  { href: "/config", label: "Config", icon: "config" },
] as const;

export default function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className={styles.shell}>
      <nav className={styles.sidebar} aria-label="Primary">
        <div className={styles.brand}>
          <span className={styles.brandMark} aria-hidden />
          Caseline
        </div>
        {NAV.map((item) => (
          <NavItem key={item.href} href={item.href} label={item.label} icon={item.icon} />
        ))}
        <div className={styles.sidebarSpacer} />
        <div className={styles.sidebarFooter}>
          <ThemeToggle />
        </div>
      </nav>
      <main className={styles.content}>{children}</main>
    </div>
  );
}
