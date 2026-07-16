"use client";

// Config studio v1 (Phase 3): self-serve script, routing, hours, and
// qualification editing with a test-call preview that runs the *same brain*
// the live channels use — verify an edit before it ever meets a caller.
// Raw JSON power-editing stays available on the Agent Config page.

import { useEffect, useState } from "react";
import type { PreviewResult } from "@/lib/api";

type Sections = {
  script: Record<string, unknown>;
  qualification: Record<string, unknown>;
  routing: Record<string, unknown>;
  guardrails: Record<string, unknown>;
};

const EMPTY: Sections = { script: {}, qualification: {}, routing: {}, guardrails: {} };

const SAMPLE_CALLER = [
  "It was about two weeks ago",
  "Broken arm from a car accident",
  "yes",
  "yes",
  "1",
].join("\n");

export default function StudioPage() {
  const [agentId, setAgentId] = useState<string | null>(null);
  const [sections, setSections] = useState<Sections>(EMPTY);
  const [status, setStatus] = useState<{ kind: "ok" | "bad"; text: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const [callerScript, setCallerScript] = useState(SAMPLE_CALLER);
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [previewing, setPreviewing] = useState(false);

  useEffect(() => {
    fetch("/api/config")
      .then(async (res) => {
        if (!res.ok) throw new Error(await res.text());
        return res.json();
      })
      .then((config) => {
        setAgentId(config.agent_id);
        setSections({
          script: config.script ?? {},
          qualification: config.qualification ?? {},
          routing: config.routing ?? {},
          guardrails: config.guardrails ?? {},
        });
      })
      .catch((e) => setStatus({ kind: "bad", text: `Failed to load config: ${e}` }));
  }, []);

  const set = (section: keyof Sections, key: string, value: unknown) =>
    setSections((s) => ({ ...s, [section]: { ...s[section], [key]: value } }));

  const text = (section: keyof Sections, key: string) =>
    String(sections[section][key] ?? "");

  const list = (section: keyof Sections, key: string) =>
    Array.isArray(sections[section][key]) ? (sections[section][key] as string[]) : [];

  async function save() {
    if (!agentId) return;
    setSaving(true);
    setStatus(null);
    try {
      const res = await fetch("/api/config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          agent_id: agentId,
          script_config: sections.script,
          qualification_rules: sections.qualification,
          routing_rules: sections.routing,
          guardrails: sections.guardrails,
        }),
      });
      if (!res.ok) setStatus({ kind: "bad", text: `Rejected: ${await res.text()}` });
      else setStatus({ kind: "ok", text: "Saved. Live within seconds on the next call or text." });
    } finally {
      setSaving(false);
    }
  }

  async function runPreview() {
    if (!agentId) return;
    setPreviewing(true);
    setStatus(null);
    try {
      const res = await fetch("/api/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          agent_id: agentId,
          messages: callerScript.split("\n").filter((l) => l.trim()),
          script_config: sections.script,
          qualification_rules: sections.qualification,
          guardrails: sections.guardrails,
        }),
      });
      if (!res.ok) {
        setStatus({ kind: "bad", text: `Preview rejected: ${await res.text()}` });
        setPreview(null);
      } else {
        setPreview(await res.json());
      }
    } finally {
      setPreviewing(false);
    }
  }

  return (
    <main>
      <h1>Config studio</h1>
      <p style={{ color: "var(--muted)" }}>
        Edit what your agent says and how it qualifies — then run a test conversation below
        before saving. These settings drive voice calls, SMS threads, and the lead chaser alike.
      </p>
      {status && <div className={`notice ${status.kind}`}>{status.text}</div>}

      <h2>Script</h2>
      <div className="notice">
        <label>
          Practice area{" "}
          <input
            value={text("script", "practice_area")}
            onChange={(e) => set("script", "practice_area", e.target.value)}
          />
        </label>
        <br />
        <label>
          Firm state (2 letters, drives recording-consent rules){" "}
          <input
            maxLength={2}
            value={text("script", "firm_state")}
            onChange={(e) => set("script", "firm_state", e.target.value.toUpperCase() || null)}
          />
        </label>
        <br />
        <label>
          <input
            type="checkbox"
            checked={Boolean(sections.script.recording_disclosure ?? true)}
            onChange={(e) => set("script", "recording_disclosure", e.target.checked)}
          />{" "}
          Recording &amp; AI disclosure line (forced on when two-party consent rules apply)
        </label>
        <br />
        <label>
          Extra instructions
          <textarea
            style={{ minHeight: 70 }}
            value={text("script", "extra_instructions")}
            onChange={(e) => set("script", "extra_instructions", e.target.value)}
          />
        </label>
      </div>

      <h2>Qualification</h2>
      <div className="notice">
        <label>
          Statute-of-limitations gate (days){" "}
          <input
            type="number"
            value={Number(sections.qualification.statute_of_limitations_days ?? 730)}
            onChange={(e) =>
              set("qualification", "statute_of_limitations_days", Number(e.target.value))
            }
          />
        </label>
        <br />
        <label>
          Refer-out injuries (comma separated){" "}
          <input
            style={{ width: "60%" }}
            value={list("qualification", "refer_out_injuries").join(", ")}
            onChange={(e) =>
              set(
                "qualification",
                "refer_out_injuries",
                e.target.value.split(",").map((s) => s.trim()).filter(Boolean),
              )
            }
          />
        </label>
      </div>

      <h2>Routing</h2>
      <div className="notice">
        <label>
          Transfer number{" "}
          <input
            value={text("routing", "transfer_number")}
            onChange={(e) => set("routing", "transfer_number", e.target.value || null)}
          />
        </label>
        <br />
        <label>
          After-hours behavior{" "}
          <select
            value={text("routing", "after_hours_behavior") || "take_message"}
            onChange={(e) => set("routing", "after_hours_behavior", e.target.value)}
          >
            <option value="take_message">take a message</option>
            <option value="voicemail">voicemail</option>
          </select>
        </label>
      </div>

      <h2>Guardrails</h2>
      <div className="notice">
        <label>
          Deflection line
          <textarea
            style={{ minHeight: 50 }}
            value={text("guardrails", "deflection_line")}
            onChange={(e) => set("guardrails", "deflection_line", e.target.value)}
          />
        </label>
        <label>
          Extra blocked patterns (one regex per line)
          <textarea
            style={{ minHeight: 50 }}
            value={list("guardrails", "extra_blocked_patterns").join("\n")}
            onChange={(e) =>
              set(
                "guardrails",
                "extra_blocked_patterns",
                e.target.value.split("\n").map((s) => s.trim()).filter(Boolean),
              )
            }
          />
        </label>
      </div>

      <p>
        <button onClick={save} disabled={saving || !agentId}>
          {saving ? "Saving…" : "Save config"}
        </button>
      </p>

      <h2>Test-call preview</h2>
      <p style={{ color: "var(--muted)" }}>
        Caller replies, one per line — previewed against the edits above (saved or not),
        with zero side effects.
      </p>
      <textarea value={callerScript} onChange={(e) => setCallerScript(e.target.value)} />
      <p>
        <button onClick={runPreview} disabled={previewing || !agentId}>
          {previewing ? "Running…" : "Run preview"}
        </button>
      </p>

      {preview && (
        <>
          {preview.turns.map((t, i) => (
            <div key={i} className={`turn ${t.role === "agent" ? "assistant" : ""}`}>
              <div className="role">
                {t.role}
                {t.guardrail_tripped ? ` · guardrail: ${t.guardrail_tripped}` : ""}
              </div>
              {t.text}
            </div>
          ))}
          <div className="notice">
            <strong>Outcome:</strong> {preview.closed_reason ?? `in progress (${preview.final_step})`}
            {preview.actions.length > 0 && (
              <>
                {" · "}
                <strong>Actions:</strong>{" "}
                {preview.actions
                  .map((a) => `${a.kind}${a.decision ? ` → ${a.decision}` : ""}`)
                  .join(", ")}
              </>
            )}
          </div>
        </>
      )}
    </main>
  );
}
