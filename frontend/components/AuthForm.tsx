"use client";

// Sign-in card for the dashboard gate. Self-serve signup is disabled — accounts
// are provisioned by an admin (scripts/create_dashboard_user.py), so this only
// posts to /api/auth/login, which sets the session cookie and lets middleware
// through. On success it navigates to ?next= (or the dashboard home).
// Full-bleed screen over the aurora — no <AppShell> chrome.

import { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { LogIn } from "lucide-react";
import AuroraBackground from "@/components/AuroraBackground";
import SoftButton from "@/components/SoftButton";
import SoftInput from "@/components/inputs/SoftInput";
import Notice from "@/components/Notice";
import styles from "@/components/kit.module.css";

export default function AuthForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error ?? "Something went wrong");
      // Only follow same-origin relative paths from ?next= (avoid open redirect).
      const next = params.get("next");
      const dest = next && next.startsWith("/") && !next.startsWith("//") ? next : "/";
      router.replace(dest);
      router.refresh();
    } catch (err) {
      setError(String((err as Error).message ?? err));
      setBusy(false);
    }
  }

  return (
    <div
      style={{
        minHeight: "100dvh",
        display: "grid",
        placeItems: "center",
        padding: 24,
        position: "relative",
      }}
    >
      <AuroraBackground />
      <div
        style={{
          position: "relative",
          width: "100%",
          maxWidth: 400,
          background: "var(--panel, rgba(255,255,255,0.03))",
          border: "1px solid var(--hairline, rgba(255,255,255,0.08))",
          borderRadius: 20,
          padding: 32,
          boxShadow: "0 24px 60px rgba(0,0,0,0.45)",
          backdropFilter: "blur(10px)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
          <span className={styles.brandMark} aria-hidden />
          <strong style={{ fontSize: 18, letterSpacing: "-0.01em" }}>Caseline</strong>
        </div>
        <h1 style={{ fontSize: 22, margin: "12px 0 4px" }}>Welcome back</h1>
        <p style={{ color: "var(--muted)", fontSize: 13, margin: "0 0 20px" }}>
          Sign in to access the intake dashboard.
        </p>

        <form onSubmit={submit} style={{ display: "grid", gap: 14 }}>
          <SoftInput
            label="Email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@firm.com"
          />
          <SoftInput
            label="Password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Your password"
          />

          {error ? (
            <Notice tone="bad" title="Could not sign in">
              {error}
            </Notice>
          ) : null}

          <SoftButton type="submit" variant="primary" block disabled={busy}>
            <LogIn size={16} />
            {busy ? "Please wait…" : "Sign in"}
          </SoftButton>
        </form>
      </div>
    </div>
  );
}
