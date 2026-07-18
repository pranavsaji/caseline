"use client";

// Sidebar footer: shows who's signed in and signs them out. Reads the email
// from /api/auth/me (the session cookie is httpOnly, so the client can't read
// it directly), then POSTs /api/auth/logout and returns to the login screen.

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { LogOut } from "lucide-react";
import SoftButton from "./SoftButton";

export default function SignOutButton() {
  const router = useRouter();
  const [email, setEmail] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    fetch("/api/auth/me")
      .then((r) => (r.ok ? r.json() : { email: null }))
      .then((d) => alive && setEmail(d.email))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  async function signOut() {
    setBusy(true);
    try {
      await fetch("/api/auth/logout", { method: "POST" });
    } finally {
      router.replace("/login");
      router.refresh();
    }
  }

  return (
    <div style={{ display: "grid", gap: 8, padding: "0 4px" }}>
      {email ? (
        <span
          style={{ fontSize: 12, color: "var(--muted)", overflow: "hidden", textOverflow: "ellipsis" }}
          title={email}
        >
          {email}
        </span>
      ) : null}
      <SoftButton size="sm" onClick={signOut} disabled={busy}>
        <LogOut size={14} /> {busy ? "Signing out…" : "Sign out"}
      </SoftButton>
    </div>
  );
}
