"use client";

// Per-referral actions: send to the partner (client PII leaves only here, and
// only with recorded consent) and resolve the outcome. Posts to the BFF route
// handlers so the firm token stays server-side, then refreshes server data.
import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Send, Check, X } from "lucide-react";
import SoftButton from "@/components/SoftButton";

export default function ReferralActions({
  referralId,
  status,
}: {
  referralId: string;
  status: string;
}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [busy, setBusy] = useState(false);
  const [consent, setConsent] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function post(path: string, body: unknown) {
    setBusy(true);
    setErr(null);
    try {
      const res = await fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "action failed");
      startTransition(() => router.refresh());
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  const disabled = busy || pending;

  if (status === "proposed") {
    return (
      <span style={{ display: "inline-flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <label style={{ display: "inline-flex", gap: 5, alignItems: "center", fontSize: 12 }}>
          <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
          consent
        </label>
        <SoftButton
          size="sm"
          variant="primary"
          disabled={disabled || !consent}
          onClick={() => post(`/api/referrals/${encodeURIComponent(referralId)}/send`, { client_consent: consent })}
        >
          <Send size={13} aria-hidden /> Send
        </SoftButton>
        {err ? <span style={{ color: "var(--bad-ink)", fontSize: 12 }}>{err}</span> : null}
      </span>
    );
  }

  if (status === "sent") {
    return (
      <span style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
        <SoftButton
          size="sm"
          disabled={disabled}
          onClick={() => post(`/api/referrals/${encodeURIComponent(referralId)}/status`, { status: "accepted" })}
        >
          <Check size={13} aria-hidden /> Accept
        </SoftButton>
        <SoftButton
          size="sm"
          variant="danger"
          disabled={disabled}
          onClick={() => post(`/api/referrals/${encodeURIComponent(referralId)}/status`, { status: "declined" })}
        >
          <X size={13} aria-hidden /> Decline
        </SoftButton>
        {err ? <span style={{ color: "var(--bad-ink)", fontSize: 12 }}>{err}</span> : null}
      </span>
    );
  }

  return <span style={{ color: "var(--muted)", fontSize: 12 }}>—</span>;
}
