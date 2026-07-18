"use client";

// Apply the engine's proposed qualification rules to the live intake agent
// (POST /v1/tuning/apply via the BFF). The backend recomputes the proposal
// server-side, so there's nothing to pass — one click, then refresh.
import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Wand2, Check } from "lucide-react";
import SoftButton from "@/components/SoftButton";
import Notice from "@/components/Notice";

export default function ApplyTuningRules({ days = 90 }: { days?: number }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [done, setDone] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function apply() {
    setBusy(true);
    setErr(null);
    try {
      const res = await fetch(`/api/tuning/apply?days=${days}`, { method: "POST" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "apply failed");
      setDone(true);
      setConfirm(false);
      startTransition(() => router.refresh());
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <Notice tone="ok" title="Applied">
        The proposed rules are now live on the intake agent — they take effect on
        the next call, SMS thread, and chased lead.
      </Notice>
    );
  }

  const disabled = busy || pending;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {!confirm ? (
        <div>
          <SoftButton variant="primary" onClick={() => setConfirm(true)} disabled={disabled}>
            <Wand2 size={15} aria-hidden /> Apply proposed rules
          </SoftButton>
        </div>
      ) : (
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <span style={{ fontSize: 13 }}>
            This overwrites the live qualification rules. Reviewed with an attorney?
          </span>
          <SoftButton variant="primary" onClick={apply} disabled={disabled}>
            <Check size={14} aria-hidden /> {disabled ? "Applying…" : "Confirm apply"}
          </SoftButton>
          <SoftButton size="sm" onClick={() => setConfirm(false)} disabled={disabled}>
            Cancel
          </SoftButton>
        </div>
      )}
      {err ? (
        <Notice tone="bad" title="Error">
          {err}
        </Notice>
      ) : null}
    </div>
  );
}
