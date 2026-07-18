"use client";

// Manual call-disposition override (POST /v1/calls/{id}/outcome via the BFF).
// The agent classifies every call; this is the human correction. Preset the
// common outcomes but allow any label the firm uses.
import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { PencilLine, Check } from "lucide-react";
import SoftButton from "@/components/SoftButton";
import SoftSelect from "@/components/inputs/SoftSelect";
import SoftInput from "@/components/inputs/SoftInput";
import Notice from "@/components/Notice";

const PRESETS = [
  "qualified",
  "refer_out",
  "decline",
  "booked",
  "transferred",
  "voicemail",
  "no_answer",
  "wrong_number",
  "spam",
  "abandoned",
];

export default function CallDisposition({
  callId,
  current,
}: {
  callId: string;
  current: string | null;
}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const [outcome, setOutcome] = useState(current ?? "qualified");
  const [custom, setCustom] = useState("");
  const [note, setNote] = useState("");
  const [msg, setMsg] = useState<{ tone: "ok" | "bad"; text: string } | null>(null);

  async function save() {
    const value = (outcome === "__custom" ? custom : outcome).trim();
    if (!value) {
      setMsg({ tone: "bad", text: "Pick or type an outcome." });
      return;
    }
    setBusy(true);
    setMsg(null);
    try {
      const res = await fetch(`/api/calls/${encodeURIComponent(callId)}/outcome`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ outcome: value, note: note.trim() || undefined }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "update failed");
      setMsg({ tone: "ok", text: `Outcome set to “${value}”.` });
      setOpen(false);
      startTransition(() => router.refresh());
    } catch (e) {
      setMsg({ tone: "bad", text: String(e) });
    } finally {
      setBusy(false);
    }
  }

  const disabled = busy || pending;

  if (!open) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <div>
          <SoftButton size="sm" onClick={() => setOpen(true)}>
            <PencilLine size={14} aria-hidden /> {current ? "Override outcome" : "Set outcome"}
          </SoftButton>
        </div>
        {msg ? <Notice tone={msg.tone}>{msg.text}</Notice> : null}
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div className="formGrid">
        <SoftSelect
          label="Outcome"
          value={outcome}
          onChange={(e) => setOutcome(e.target.value)}
        >
          {PRESETS.map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
          <option value="__custom">Custom…</option>
        </SoftSelect>
        {outcome === "__custom" ? (
          <SoftInput
            label="Custom outcome"
            value={custom}
            onChange={(e) => setCustom(e.target.value)}
            placeholder="e.g. callback_scheduled"
          />
        ) : null}
        <SoftInput
          label="Note (optional)"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Why the override"
        />
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <SoftButton variant="primary" onClick={save} disabled={disabled}>
          <Check size={14} aria-hidden /> {disabled ? "Saving…" : "Save outcome"}
        </SoftButton>
        <SoftButton size="sm" onClick={() => setOpen(false)} disabled={disabled}>
          Cancel
        </SoftButton>
      </div>
      {msg ? <Notice tone={msg.tone}>{msg.text}</Notice> : null}
    </div>
  );
}
