"use client";

// Raw-but-safe config editing (plan.md Workstream D): each jsonb section is
// an editable JSON form, validated client-side before submit and again by
// pydantic on the server. The polished config studio is Phase 3.

import { useEffect, useState } from "react";

const SECTIONS = [
  ["script", "script_config", "Script (template, greeting, practice area, disclosure)"],
  ["qualification", "qualification_rules", "Qualification rules (SOL days, refer-out injuries)"],
  ["routing", "routing_rules", "Routing (transfer number, after-hours behavior)"],
  ["guardrails", "guardrails", "Guardrails (extra blocked patterns, deflection line)"],
] as const;

export default function ConfigPage() {
  const [agentId, setAgentId] = useState<string | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [instructions, setInstructions] = useState("");
  const [status, setStatus] = useState<{ kind: "ok" | "bad"; text: string } | null>(null);
  const [saving, setSaving] = useState(false);

  async function load() {
    const res = await fetch("/api/config");
    if (!res.ok) {
      setStatus({ kind: "bad", text: `Failed to load config: ${await res.text()}` });
      return;
    }
    const config = await res.json();
    setAgentId(config.agent_id);
    setInstructions(config.instructions ?? "");
    const next: Record<string, string> = {};
    for (const [readKey] of SECTIONS) {
      next[readKey] = JSON.stringify(config[readKey] ?? {}, null, 2);
    }
    setValues(next);
  }

  useEffect(() => {
    load().catch((e) => setStatus({ kind: "bad", text: String(e) }));
  }, []);

  async function save() {
    if (!agentId) return;
    const body: Record<string, unknown> = { agent_id: agentId };
    for (const [readKey, writeKey] of SECTIONS) {
      try {
        body[writeKey] = JSON.parse(values[readKey] ?? "{}");
      } catch {
        setStatus({ kind: "bad", text: `"${readKey}" is not valid JSON — fix it and retry.` });
        return;
      }
    }
    setSaving(true);
    setStatus(null);
    try {
      const res = await fetch("/api/config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        setStatus({ kind: "bad", text: `Rejected: ${await res.text()}` });
      } else {
        setStatus({ kind: "ok", text: "Saved. Live within seconds on the next call." });
        await load();
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <main>
      <h1>Agent config</h1>
      {status && <div className={`notice ${status.kind}`}>{status.text}</div>}
      {SECTIONS.map(([readKey, , label]) => (
        <section key={readKey}>
          <h2>{label}</h2>
          <textarea
            value={values[readKey] ?? ""}
            onChange={(e) => setValues((v) => ({ ...v, [readKey]: e.target.value }))}
            spellCheck={false}
          />
        </section>
      ))}
      <p>
        <button onClick={save} disabled={saving || !agentId}>
          {saving ? "Saving…" : "Save config"}
        </button>
      </p>
      <h2>Compiled instructions (what the agent actually runs)</h2>
      <div className="notice" style={{ whiteSpace: "pre-wrap" }}>{instructions}</div>
    </main>
  );
}
