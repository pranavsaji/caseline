"use client";

// Attorney verdict on a lead — the qualification-tuning training signal
// (POST /v1/leads/{id}/review via the BFF). Accept / reject, then refresh.
import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { ThumbsUp, ThumbsDown } from "lucide-react";
import SoftButton from "@/components/SoftButton";
import Pill from "@/components/Pill";

export default function LeadReview({ leadId }: { leadId: string }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function review(verdict: "accepted" | "rejected") {
    setBusy(true);
    setErr(null);
    try {
      const res = await fetch(`/api/leads/${encodeURIComponent(leadId)}/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ verdict }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "review failed");
      setDone(verdict);
      startTransition(() => router.refresh());
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  if (done) return <Pill tone={done === "accepted" ? "ok" : "bad"}>{done}</Pill>;

  return (
    <span style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
      <SoftButton size="sm" disabled={busy || pending} onClick={() => review("accepted")}>
        <ThumbsUp size={13} aria-hidden />
      </SoftButton>
      <SoftButton size="sm" variant="danger" disabled={busy || pending} onClick={() => review("rejected")}>
        <ThumbsDown size={13} aria-hidden />
      </SoftButton>
      {err ? <span style={{ color: "var(--bad-ink)", fontSize: 12 }}>{err}</span> : null}
    </span>
  );
}
