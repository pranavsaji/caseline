"use client";

// Replay a single dead-lettered event via the admin BFF route. On success it
// refreshes server data so the row disappears from the dead-letter list.
import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { RefreshCw } from "lucide-react";
import SoftButton from "@/components/SoftButton";

export default function EventReplay({ eventId }: { eventId: string }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function replay() {
    setBusy(true);
    setErr(null);
    try {
      const res = await fetch("/api/ops/replay", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ event_id: eventId }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "replay failed");
      startTransition(() => router.refresh());
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <span style={{ display: "inline-flex", gap: 8, alignItems: "center" }}>
      <SoftButton size="sm" onClick={replay} disabled={busy || pending}>
        <RefreshCw size={14} aria-hidden /> {busy || pending ? "Replaying…" : "Replay"}
      </SoftButton>
      {err ? <span style={{ color: "var(--bad-ink)", fontSize: 12 }}>{err}</span> : null}
    </span>
  );
}
