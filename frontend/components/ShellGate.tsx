"use client";

import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import AppShell from "./AppShell";

/**
 * Chooses the chrome for a route. The cinematic marketing experience under
 * `/experience` and the auth screens (`/login`, `/signup`) are full-bleed and
 * provide their own layout, so they escape the dashboard's <AppShell> (sidebar
 * + aurora). Every other route keeps the shell. Client component purely to read
 * the active pathname.
 */
const BARE_PREFIXES = ["/experience", "/login", "/signup"];

export default function ShellGate({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const bare = BARE_PREFIXES.some((p) => pathname?.startsWith(p));
  if (bare) return <>{children}</>;
  return <AppShell>{children}</AppShell>;
}
