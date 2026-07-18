"use client";

// Register a referral partner firm. Posts to the BFF route so the firm token
// stays server-side, then refreshes the partner table.
import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Building2 } from "lucide-react";
import SoftButton from "@/components/SoftButton";
import SoftInput from "@/components/inputs/SoftInput";
import Notice from "@/components/Notice";

export default function PartnerForm() {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: "ok" | "bad"; text: string } | null>(null);
  const [f, setF] = useState({
    name: "",
    practice_areas: "",
    states: "",
    contact_email: "",
    contact_phone: "",
  });

  function set(k: keyof typeof f) {
    return (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value });
  }

  const csv = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);

  async function submit() {
    setBusy(true);
    setMsg(null);
    try {
      const res = await fetch("/api/referral-partners", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: f.name.trim(),
          practice_areas: csv(f.practice_areas),
          states: csv(f.states),
          contact_email: f.contact_email.trim() || undefined,
          contact_phone: f.contact_phone.trim() || undefined,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "failed");
      setMsg({ tone: "ok", text: `Registered ${f.name}.` });
      setF({ name: "", practice_areas: "", states: "", contact_email: "", contact_phone: "" });
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
        <SoftInput label="Firm name" value={f.name} onChange={set("name")} placeholder="Smith & Co" />
        <SoftInput label="Practice areas (comma-sep)" value={f.practice_areas} onChange={set("practice_areas")} placeholder="workers comp, immigration" />
        <SoftInput label="States (comma-sep)" value={f.states} onChange={set("states")} placeholder="CA, NV" />
        <SoftInput label="Contact email" value={f.contact_email} onChange={set("contact_email")} placeholder="intake@smith.co" />
        <SoftInput label="Contact phone" value={f.contact_phone} onChange={set("contact_phone")} placeholder="+14155550123" />
      </div>
      <div className="formRow">
        <SoftButton variant="primary" onClick={submit} disabled={busy || pending || !f.name.trim()}>
          <Building2 size={15} aria-hidden /> {busy || pending ? "Saving…" : "Register partner"}
        </SoftButton>
      </div>
      {msg ? (
        <div className="formRow">
          <Notice tone={msg.tone} title={msg.tone === "ok" ? "Done" : "Error"}>{msg.text}</Notice>
        </div>
      ) : null}
    </div>
  );
}
