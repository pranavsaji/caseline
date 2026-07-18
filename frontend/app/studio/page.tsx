"use client";

// Config studio v1 (Phase 3): self-serve script, routing, hours, and
// qualification editing with a test-call preview that runs the *same brain*
// the live channels use — verify an edit before it ever meets a caller.
// Raw JSON power-editing stays available on the Agent Config page.
// Phase 2 UI: neomorphic component kit (Cards, SoftInput/Toggle/SoftSelect,
// primary SoftButton + toast, TranscriptTurn preview panel).

import { useEffect, useState } from "react";
import { PlayCircle } from "lucide-react";
import type { PreviewResult } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import Card from "@/components/Card";
import SoftButton from "@/components/SoftButton";
import SoftInput from "@/components/inputs/SoftInput";
import SoftTextarea from "@/components/inputs/SoftTextarea";
import SoftSelect from "@/components/inputs/SoftSelect";
import Toggle from "@/components/Toggle";
import Pill from "@/components/Pill";
import Notice from "@/components/Notice";
import TranscriptTurn, { TranscriptList } from "@/components/TranscriptTurn";
import VoiceManager from "@/components/VoiceManager";
import ModelManager from "@/components/ModelManager";

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

  // Auto-dismiss the success toast; leave errors up until the next action.
  useEffect(() => {
    if (status?.kind !== "ok") return;
    const t = setTimeout(() => setStatus(null), 4000);
    return () => clearTimeout(t);
  }, [status]);

  const set = (section: keyof Sections, key: string, value: unknown) =>
    setSections((s) => ({ ...s, [section]: { ...s[section], [key]: value } }));

  const text = (section: keyof Sections, key: string) => String(sections[section][key] ?? "");

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
      else setStatus({ kind: "ok", text: "Published. Live within seconds on the next call or text." });
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
        setStatus({ kind: "bad", text: `Preview couldn't run. ${await res.text()}` });
        setPreview(null);
      } else {
        setPreview(await res.json());
      }
    } finally {
      setPreviewing(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Config studio"
        subtitle="Edit what your agent says and how it qualifies — then run a test conversation before publishing. These settings drive voice calls, SMS threads, and the lead chaser alike."
        actions={
          <SoftButton variant="primary" onClick={save} disabled={saving || !agentId}>
            {saving ? "Publishing…" : "Publish changes"}
          </SoftButton>
        }
      />

      {status && (
        <Notice tone={status.kind === "ok" ? "ok" : "bad"} title={status.kind === "ok" ? "Published" : "Not saved"}>
          {status.text}
        </Notice>
      )}

      <Card title="Script" className="stackCard">
        <div className="formGrid">
          <SoftInput
            label="Practice area"
            value={text("script", "practice_area")}
            onChange={(e) => set("script", "practice_area", e.target.value)}
          />
          <SoftInput
            label="Firm state (2 letters — drives recording-consent rules)"
            maxLength={2}
            value={text("script", "firm_state")}
            onChange={(e) => set("script", "firm_state", e.target.value.toUpperCase() || null)}
          />
        </div>
        <div className="formRow">
          <Toggle
            label="Recording & AI disclosure line (forced on when two-party consent rules apply)"
            checked={Boolean(sections.script.recording_disclosure ?? true)}
            onChange={(e) => set("script", "recording_disclosure", e.target.checked)}
          />
        </div>
        <div className="formRow">
          <SoftTextarea
            label="Extra instructions"
            mono={false}
            value={text("script", "extra_instructions")}
            onChange={(e) => set("script", "extra_instructions", e.target.value)}
          />
        </div>
      </Card>

      <Card title="Qualification" className="stackCard">
        <div className="formGrid">
          <SoftInput
            label="Statute-of-limitations gate (days)"
            type="number"
            value={Number(sections.qualification.statute_of_limitations_days ?? 730)}
            onChange={(e) => set("qualification", "statute_of_limitations_days", Number(e.target.value))}
          />
          <SoftInput
            label="Refer-out injuries (comma separated)"
            value={list("qualification", "refer_out_injuries").join(", ")}
            onChange={(e) =>
              set(
                "qualification",
                "refer_out_injuries",
                e.target.value.split(",").map((s) => s.trim()).filter(Boolean),
              )
            }
          />
        </div>
      </Card>

      <Card title="Routing" className="stackCard">
        <div className="formGrid">
          <SoftInput
            label="Transfer number"
            value={text("routing", "transfer_number")}
            onChange={(e) => set("routing", "transfer_number", e.target.value || null)}
          />
          <SoftSelect
            label="After-hours behavior"
            value={text("routing", "after_hours_behavior") || "take_message"}
            onChange={(e) => set("routing", "after_hours_behavior", e.target.value)}
          >
            <option value="take_message">take a message</option>
            <option value="voicemail">voicemail</option>
          </SoftSelect>
        </div>
      </Card>

      <Card title="Guardrails" className="stackCard">
        <div className="formRow">
          <SoftTextarea
            label="Deflection line"
            mono={false}
            value={text("guardrails", "deflection_line")}
            onChange={(e) => set("guardrails", "deflection_line", e.target.value)}
          />
        </div>
        <div className="formRow">
          <SoftTextarea
            label="Extra blocked patterns (one regex per line)"
            value={list("guardrails", "extra_blocked_patterns").join("\n")}
            onChange={(e) =>
              set(
                "guardrails",
                "extra_blocked_patterns",
                e.target.value.split("\n").map((s) => s.trim()).filter(Boolean),
              )
            }
          />
        </div>
      </Card>

      <Card
        title="Test-call preview"
        className="stackCard"
        actions={
          <SoftButton onClick={runPreview} disabled={previewing || !agentId}>
            <PlayCircle size={16} aria-hidden /> {previewing ? "Running…" : "Run preview"}
          </SoftButton>
        }
      >
        <SoftTextarea
          label="Caller replies, one per line — previewed against the edits above (saved or not), with zero side effects."
          value={callerScript}
          onChange={(e) => setCallerScript(e.target.value)}
        />

        {preview && (
          <div className="stackCard">
            <TranscriptList>
              {preview.turns.map((t, i) => (
                <TranscriptTurn
                  key={i}
                  role={t.role}
                  speaker={t.role === "agent" ? "agent" : "caller"}
                  tag={t.guardrail_tripped ? <Pill tone="bad">guardrail: {t.guardrail_tripped}</Pill> : undefined}
                >
                  {t.text}
                </TranscriptTurn>
              ))}
            </TranscriptList>
            <Notice tone="info" title="Result">
              {preview.closed_reason ?? `in progress (${preview.final_step})`}
              {preview.actions.length > 0 &&
                ` · actions: ${preview.actions
                  .map((a) => `${a.kind}${a.decision ? ` → ${a.decision}` : ""}`)
                  .join(", ")}`}
            </Notice>
          </div>
        )}
      </Card>

      <ModelManager />

      <VoiceManager />
    </>
  );
}
