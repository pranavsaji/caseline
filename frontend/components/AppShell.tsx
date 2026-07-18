import type { ReactNode } from "react";
import NavItem from "./NavItem";
import AuroraBackground from "./AuroraBackground";
import SignOutButton from "./SignOutButton";
import styles from "./kit.module.css";

/**
 * The molded control-panel chrome (§6): a raised soft sidebar (desktop) that
 * collapses to a horizontal scrolling top bar on mobile. Replaces the flat top
 * nav from `layout.tsx` in Phase 2; data layer and children stay untouched.
 * The dashboard is dark-only, so there is no theme toggle. Server component —
 * the only client island is <NavItem> (active-route highlighting).
 */
const NAV = [
  { href: "/", label: "Overview", icon: "overview" },
  { href: "/calls", label: "Calls", icon: "calls" },
  { href: "/threads", label: "Threads", icon: "threads" },
  { href: "/analytics", label: "Analytics", icon: "analytics" },
  { href: "/tuning", label: "Tuning", icon: "tuning" },
  { href: "/referrals", label: "Referrals", icon: "referrals" },
  { href: "/studio", label: "Studio", icon: "studio" },
  { href: "/ops", label: "Ops", icon: "ops" },
  { href: "/config", label: "Config", icon: "config" },
] as const;

export default function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className={styles.shell}>
      <AuroraBackground />
      <nav className={styles.sidebar} aria-label="Primary">
        <div className={styles.brand}>
          <span className={styles.brandMark} aria-hidden />
          Caseline
        </div>
        {NAV.map((item) => (
          <NavItem key={item.href} href={item.href} label={item.label} icon={item.icon} />
        ))}
        <div className={styles.sidebarSpacer} />
        <SignOutButton />
      </nav>
      <main className={styles.content}>{children}</main>
    </div>
  );
}
