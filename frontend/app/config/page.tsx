"use client";

// Raw-but-safe config editing (plan.md Workstream D): each jsonb section is
// an editable JSON form, validated client-side before submit and again by
// pydantic on the server. The polished self-serve editor is the Config Studio.
// Phase 2 UI: neomorphic kit — SoftTextarea with a live red inset validation
// ring, compiled instructions in a read-only Notice.

import { useEffect, useState } from "react";
import { getConfigError } from "@/lib/json";
import PageHeader from "@/components/PageHeader";
import Card from "@/components/Card";
import SoftButton from "@/components/SoftButton";
import SoftTextarea from "@/components/inputs/SoftTextarea";
import Notice from "@/components/Notice";

const SECTIONS = [
  ["script", "script_config", "Script", "Template, greeting, practice area, disclosure"],
  ["qualification", "qualification_rules", "Qualification rules", "SOL days, refer-out injuries"],
  ["routing", "routing_rules", "Routing", "Transfer number, after-hours behavior"],
  ["guardrails", "guardrails", "Guardrails", "Extra blocked patterns, deflection line"],
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

  useEffect(() => {
    if (status?.kind !== "ok") return;
    const t = setTimeout(() => setStatus(null), 4000);
    return () => clearTimeout(t);
  }, [status]);

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
        setStatus({ kind: "ok", text: "Published. Live within seconds on the next call." });
        await load();
      }
    } finally {
      setSaving(false);
    }
  }

  const anyInvalid = SECTIONS.some(([readKey]) => getConfigError(values[readKey]) != null);

  return (
    <>
      <PageHeader
        title="Agent config"
        subtitle="Raw JSON power-editing for each config section. Validated as you type and again by the server before it goes live."
        actions={
          <SoftButton variant="primary" onClick={save} disabled={saving || !agentId || anyInvalid}>
            {saving ? "Publishing…" : "Publish changes"}
          </SoftButton>
        }
      />

      {status && (
        <Notice tone={status.kind === "ok" ? "ok" : "bad"} title={status.kind === "ok" ? "Published" : "Not saved"}>
          {status.text}
        </Notice>
      )}

      {SECTIONS.map(([readKey, , label, desc]) => {
        const error = getConfigError(values[readKey]);
        return (
          <Card key={readKey} title={label} className="stackCard">
            <SoftTextarea
              label={desc}
              value={values[readKey] ?? ""}
              onChange={(e) => setValues((v) => ({ ...v, [readKey]: e.target.value }))}
              spellCheck={false}
              error={error ?? undefined}
            />
          </Card>
        );
      })}

      <Card title="Compiled instructions" className="stackCard">
        <Notice tone="info" icon={false}>
          <pre>{instructions || "—"}</pre>
        </Notice>
      </Card>
    </>
  );
}
