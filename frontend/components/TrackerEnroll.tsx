"use client";

// Enroll a signed client in the treatment tracker (POST /v1/tracker/enroll via
// the BFF). Consent for these check-ins rides on the representation agreement;
// STOP still wins server-side. Opens a thread with goal=treatment_tracker.
import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { HeartPulse } from "lucide-react";
import SoftButton from "@/components/SoftButton";
import SoftInput from "@/components/inputs/SoftInput";
import Notice from "@/components/Notice";

export default function TrackerEnroll() {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: "ok" | "bad"; text: string } | null>(null);
  const [f, setF] = useState({
    name: "",
    phone: "",
    matter_description: "",
    cadence_days: "14",
  });

  function set(k: keyof typeof f) {
    return (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value });
  }

  async function submit() {
    setBusy(true);
    setMsg(null);
    try {
      const res = await fetch("/api/tracker/enroll", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: f.name.trim(),
          phone: f.phone.trim(),
          matter_description: f.matter_description.trim() || undefined,
          cadence_days: Number(f.cadence_days) || 14,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "failed");
      setMsg({ tone: "ok", text: `Enrolled ${f.name}. Check-ins every ${f.cadence_days} days.` });
      setF({ name: "", phone: "", matter_description: "", cadence_days: "14" });
      startTransition(() => router.refresh());
    } catch (e) {
      setMsg({ tone: "bad", text: String(e) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <div className="formGrid">
        <SoftInput label="Client name" value={f.name} onChange={set("name")} placeholder="Jane Doe" />
        <SoftInput label="Phone" value={f.phone} onChange={set("phone")} placeholder="+14155550123" />
        <SoftInput
          label="Matter (optional)"
          value={f.matter_description}
          onChange={set("matter_description")}
          placeholder="rear-end collision, PT ongoing"
        />
        <SoftInput
          label="Check-in cadence (days)"
          type="number"
          min={1}
          max={90}
          value={f.cadence_days}
          onChange={set("cadence_days")}
        />
      </div>
      <div className="formRow">
        <SoftButton
          variant="primary"
          onClick={submit}
          disabled={busy || pending || !f.name.trim() || !f.phone.trim()}
        >
          <HeartPulse size={15} aria-hidden /> {busy || pending ? "Enrolling…" : "Enroll in tracker"}
        </SoftButton>
      </div>
      {msg ? (
        <div className="formRow">
          <Notice tone={msg.tone} title={msg.tone === "ok" ? "Done" : "Error"}>
            {msg.text}
          </Notice>
        </div>
      ) : null}
    </div>
  );
}
