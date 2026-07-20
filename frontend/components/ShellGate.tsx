"use client";

import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import AppShell from "./AppShell";

/**
 * Chooses the chrome for a route. The cinematic marketing landing (`/`, and
 * `/experience` which forwards to it) and the auth screens (`/login`,
 * `/signup`) are full-bleed and provide their own layout, so they escape the
 * dashboard's <AppShell> (sidebar + aurora). Every other route keeps the shell.
 * Client component purely to read the active pathname.
 */
// `/` must match EXACTLY — as a prefix it would strip the shell from every
// route in the app.
const BARE_EXACT = ["/"];
const BARE_PREFIXES = ["/experience", "/login", "/signup"];

export default function ShellGate({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const bare =
    BARE_EXACT.includes(pathname ?? "") ||
    BARE_PREFIXES.some((p) => pathname?.startsWith(p));
  if (bare) return <>{children}</>;
  return <AppShell>{children}</AppShell>;
}
