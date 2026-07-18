"use client";

// Staff-authored follow-up on an open thread (POST /v1/threads/{id}/message via
// the BFF) — the manual override of the automated chaser. Guardrail-screened
// server-side; sending disarms the pending no-reply nudge.
import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Send } from "lucide-react";
import SoftButton from "@/components/SoftButton";
import SoftTextarea from "@/components/inputs/SoftTextarea";
import Notice from "@/components/Notice";

export default function ThreadReply({ threadId }: { threadId: string }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [busy, setBusy] = useState(false);
  const [body, setBody] = useState("");
  const [msg, setMsg] = useState<{ tone: "ok" | "bad"; text: string } | null>(null);

  async function send() {
    const text = body.trim();
    if (!text) return;
    setBusy(true);
    setMsg(null);
    try {
      const res = await fetch(`/api/threads/${encodeURIComponent(threadId)}/message`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ body: text }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "send failed");
      setBody("");
      setMsg({ tone: "ok", text: "Sent." });
      startTransition(() => router.refresh());
    } catch (e) {
      setMsg({ tone: "bad", text: String(e) });
    } finally {
      setBusy(false);
    }
  }

  const disabled = busy || pending;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <SoftTextarea
        label="Send a follow-up"
        mono={false}
        rows={3}
        value={body}
        onChange={(e) => setBody(e.target.value)}
        placeholder="Type a message — it goes out on this thread's channel and pauses the auto-nudge."
        maxLength={1000}
      />
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <SoftButton variant="primary" onClick={send} disabled={disabled || !body.trim()}>
          <Send size={14} aria-hidden /> {disabled ? "Sending…" : "Send follow-up"}
        </SoftButton>
      </div>
      {msg ? <Notice tone={msg.tone}>{msg.text}</Notice> : null}
    </div>
  );
}
