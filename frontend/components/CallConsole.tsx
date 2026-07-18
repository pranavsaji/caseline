"use client";

// Calls hub interactive island: place a REAL outbound call (operator-initiated,
// runs the firm's intake agent) and run a text-simulated test call through the
// same brain with zero side effects. Both keep the firm token server-side by
// posting to the BFF route handlers (/api/calls/dial, /api/preview).

import { useEffect, useState } from "react";
import { PhoneOutgoing, PlayCircle } from "lucide-react";
import type { DialResult, PreviewResult } from "@/lib/api";
import Card from "@/components/Card";
import SoftButton from "@/components/SoftButton";
import SoftInput from "@/components/inputs/SoftInput";
import SoftTextarea from "@/components/inputs/SoftTextarea";
import Pill from "@/components/Pill";
import Notice from "@/components/Notice";
import TranscriptTurn, { TranscriptList } from "@/components/TranscriptTurn";

// Coerce a loosely typed number to E.164, forgiving spaces/dashes/parens, a
// leading "1", or a bare 10-digit US number. Mirrors the backend normalizer in
// api/routes_v1.py so the UI and API agree on what's dialable. Returns null if
// it can't be confidently normalized.
function normalizeE164(raw: string): string | null {
  const s = raw.trim();
  if (!s) return null;
  const digits = s.replace(/\D/g, "");
  let candidate: string;
  if (s.startsWith("+")) candidate = "+" + digits;
  else if (digits.length === 10) candidate = "+1" + digits;
  else candidate = "+" + digits;
  return /^\+[1-9]\d{6,14}$/.test(candidate) ? candidate : null;
}

const SAMPLE_CALLER = [
  "Hi, I was in a car accident about two weeks ago",
  "I broke my arm",
  "yes, I'm seeing a doctor",
  "yes I have insurance",
  "tomorrow afternoon works",
].join("\n");

export default function CallConsole() {
  const [agentId, setAgentId] = useState<string | null>(null);

  // place-call state
  const [toNumber, setToNumber] = useState("");
  const [purpose, setPurpose] = useState("");
  const [dialing, setDialing] = useState(false);
  const [dialResult, setDialResult] = useState<DialResult | null>(null);
  const [dialError, setDialError] = useState<string | null>(null);

  // simulate state
  const [callerScript, setCallerScript] = useState(SAMPLE_CALLER);
  const [previewing, setPreviewing] = useState(false);
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/config")
      .then((r) => (r.ok ? r.json() : null))
      .then((c) => c && setAgentId(c.agent_id ?? null))
      .catch(() => {});
  }, []);

  async function placeCall() {
    setDialing(true);
    setDialError(null);
    setDialResult(null);
    try {
      const normalized = normalizeE164(toNumber);
      if (!normalized) {
        throw new Error("Enter a valid phone number, e.g. +14155550123 or 4155550123 (US).");
      }
      const res = await fetch("/api/calls/dial", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ to_number: normalized, purpose: purpose.trim() || undefined }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "dial failed");
      setDialResult(data as DialResult);
    } catch (err) {
      setDialError(String(err));
    } finally {
      setDialing(false);
    }
  }

  async function simulate() {
    if (!agentId) {
      setPreviewError("No agent loaded yet.");
      return;
    }
    setPreviewing(true);
    setPreviewError(null);
    setPreview(null);
    try {
      const messages = callerScript
        .split("\n")
        .map((l) => l.trim())
        .filter(Boolean);
      const res = await fetch("/api/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ agent_id: agentId, messages }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "preview failed");
      setPreview(data as PreviewResult);
    } catch (err) {
      setPreviewError(String(err));
    } finally {
      setPreviewing(false);
    }
  }

  return (
    <div className="formGrid">
      {/* Place a real outbound call */}
      <Card title="Place a call">
        <p className="stackCard" style={{ color: "var(--muted)", fontSize: 13, marginTop: 0 }}>
          Dial any number and the intake agent runs the call live. US numbers can
          be entered bare (4155550123); others need a country code (+44…). Requires
          a SIP outbound trunk + the agent worker running.
        </p>
        <div className="formRow">
          <SoftInput
            label="Destination number"
            placeholder="+14155550123"
            value={toNumber}
            onChange={(e) => setToNumber(e.target.value)}
            inputMode="tel"
          />
        </div>
        <div className="formRow">
          <SoftInput
            label="Purpose (optional)"
            placeholder="Call partner firm about referral"
            value={purpose}
            onChange={(e) => setPurpose(e.target.value)}
          />
        </div>
        <div className="formRow">
          <SoftButton
            variant="primary"
            onClick={placeCall}
            disabled={dialing || !toNumber.trim()}
          >
            <PhoneOutgoing size={16} aria-hidden /> {dialing ? "Dialing…" : "Place call"}
          </SoftButton>
        </div>
        {dialError ? (
          <div className="formRow">
            <Notice tone="bad" title="Could not place call">
              {dialError}
            </Notice>
          </div>
        ) : null}
        {dialResult ? (
          <div className="formRow">
            <Notice
              tone={dialResult.placed ? "ok" : "warn"}
              title={dialResult.placed ? "Ringing" : "Recorded (dry-run)"}
            >
              <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                <Pill tone={dialResult.placed ? "ok" : "warn"} dot>
                  {dialResult.placed ? "real call" : `dialer: ${dialResult.dialer}`}
                </Pill>
                <a href={`/calls/${encodeURIComponent(dialResult.call_id)}`}>
                  {dialResult.call_id}
                </a>
              </div>
              {dialResult.note ? (
                <p style={{ margin: "8px 0 0" }}>{dialResult.note}</p>
              ) : null}
            </Notice>
          </div>
        ) : null}
      </Card>

      {/* Simulated test call */}
      <Card title="Simulate a test call">
        <p style={{ color: "var(--muted)", fontSize: 13, marginTop: 0 }}>
          Run caller lines through the same brain the live channels use — no
          telephony, no side effects. Verify a script before it meets a caller.
        </p>
        <div className="formRow">
          <SoftTextarea
            label="Caller lines (one per line)"
            mono={false}
            value={callerScript}
            onChange={(e) => setCallerScript(e.target.value)}
          />
        </div>
        <div className="formRow">
          <SoftButton onClick={simulate} disabled={previewing || !agentId}>
            <PlayCircle size={16} aria-hidden /> {previewing ? "Running…" : "Run simulation"}
          </SoftButton>
        </div>
        {previewError ? (
          <div className="formRow">
            <Notice tone="bad" title="Simulation failed">
              {previewError}
            </Notice>
          </div>
        ) : null}
        {preview ? (
          <div className="formRow">
            <TranscriptList>
              {preview.turns.map((t, i) => (
                <TranscriptTurn
                  key={i}
                  role={t.role}
                  tag={
                    t.guardrail_tripped ? <Pill tone="bad">guardrail</Pill> : undefined
                  }
                >
                  {t.text}
                </TranscriptTurn>
              ))}
            </TranscriptList>
            {preview.closed_reason ? (
              <Notice tone="info" title="Outcome">
                {preview.closed_reason}
              </Notice>
            ) : null}
          </div>
        ) : null}
      </Card>
    </div>
  );
}
