"use client";

// Voice studio: list branded/cloned voice profiles, create a new one (consent
// is structural — the API refuses without it), and assign a ready profile to
// the firm's agent. All calls go through BFF routes; the firm token stays
// server-side.
//
// The sample can be supplied three ways: record it in-browser (MediaRecorder),
// upload an audio file, or paste a pre-hosted http(s) URL. Recorded/uploaded
// audio is sent inline as a base64 data URI (`sample_data`); the URL path
// sends `sample_uri`. The backend accepts exactly one.
import { useEffect, useRef, useState } from "react";
import { Mic, Square, Upload, Link2, Wand2, Trash2 } from "lucide-react";
import type { LibraryVoice, VoiceProfile } from "@/lib/api";
import Card from "@/components/Card";
import SoftButton from "@/components/SoftButton";
import SoftInput from "@/components/inputs/SoftInput";
import SoftSelect from "@/components/inputs/SoftSelect";
import Toggle from "@/components/Toggle";
import Pill, { type PillTone } from "@/components/Pill";
import Notice from "@/components/Notice";
import DataTable, { type Column } from "@/components/DataTable";
import EmptyState from "@/components/EmptyState";

function statusTone(s: string): PillTone {
  if (s === "ready") return "ok";
  if (s === "failed") return "bad";
  return "warn";
}

type SampleMode = "record" | "upload" | "url";

const MAX_SAMPLE_BYTES = 15 * 1024 * 1024; // 15 MB — plenty for a clean clip

function blobToDataUri(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Could not read the audio file"));
    reader.onload = () => resolve(String(reader.result));
    reader.readAsDataURL(blob);
  });
}

export default function VoiceManager() {
  const [agentId, setAgentId] = useState<string | null>(null);
  const [profiles, setProfiles] = useState<VoiceProfile[]>([]);
  const [library, setLibrary] = useState<LibraryVoice[]>([]);
  const [currentVoiceId, setCurrentVoiceId] = useState<string | null>(null);
  const [assigning, setAssigning] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: "ok" | "bad"; text: string } | null>(null);

  // Sample input: the active mode plus whichever source it produced.
  const [mode, setMode] = useState<SampleMode>("record");
  const [sampleUri, setSampleUri] = useState("");
  const [sample, setSample] = useState<{ blob: Blob; url: string; label: string } | null>(null);

  // Recording state.
  const [recording, setRecording] = useState(false);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);

  async function refresh() {
    const res = await fetch("/api/voice-profiles");
    if (res.ok) setProfiles(await res.json());
  }

  useEffect(() => {
    fetch("/api/config")
      .then((r) => (r.ok ? r.json() : null))
      .then((c) => {
        if (!c) return;
        setAgentId(c.agent_id ?? null);
        setCurrentVoiceId(c.voice_id ?? null);
      })
      .catch(() => {});
    fetch("/api/voice-library")
      .then((r) => (r.ok ? r.json() : []))
      .then((v) => Array.isArray(v) && setLibrary(v))
      .catch(() => {});
    refresh().catch(() => {});
  }, []);

  // Revoke the last preview URL when it's replaced or the component unmounts.
  useEffect(() => {
    return () => {
      if (sample) URL.revokeObjectURL(sample.url);
    };
  }, [sample]);

  function setSampleFromBlob(blob: Blob, label: string) {
    if (blob.size > MAX_SAMPLE_BYTES) {
      setMsg({ tone: "bad", text: "Audio is over 15 MB — trim it to a short, clean clip." });
      return;
    }
    setSample((prev) => {
      if (prev) URL.revokeObjectURL(prev.url);
      return { blob, url: URL.createObjectURL(blob), label };
    });
    setMsg(null);
  }

  function clearSample() {
    setSample((prev) => {
      if (prev) URL.revokeObjectURL(prev.url);
      return null;
    });
  }

  async function startRecording() {
    setMsg(null);
    if (!navigator.mediaDevices?.getUserMedia) {
      setMsg({ tone: "bad", text: "This browser can't record audio. Upload a file or paste a URL instead." });
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      chunksRef.current = [];
      const rec = new MediaRecorder(stream);
      rec.ondataavailable = (e) => e.data.size > 0 && chunksRef.current.push(e.data);
      rec.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunksRef.current, { type: rec.mimeType || "audio/webm" });
        setSampleFromBlob(blob, "Recorded sample");
        setRecording(false);
      };
      recorderRef.current = rec;
      rec.start();
      setRecording(true);
    } catch {
      setMsg({ tone: "bad", text: "Microphone access was denied. Allow it, upload a file, or paste a URL." });
    }
  }

  function stopRecording() {
    recorderRef.current?.stop();
  }

  function switchMode(next: SampleMode) {
    if (recording) stopRecording();
    setMode(next);
    setMsg(null);
    // Recorded/uploaded audio and a pasted URL are mutually exclusive inputs.
    if (next === "url") clearSample();
    else setSampleUri("");
  }

  const hasSample = mode === "url" ? Boolean(sampleUri.trim()) : Boolean(sample);

  async function create() {
    setBusy(true);
    setMsg(null);
    try {
      const body: {
        name: string;
        consent_confirmed: boolean;
        description?: string;
        sample_uri?: string;
        sample_data?: string;
      } = {
        name: name.trim(),
        consent_confirmed: consent,
        description: description.trim() || undefined,
      };
      if (mode === "url") body.sample_uri = sampleUri.trim();
      else if (sample) body.sample_data = await blobToDataUri(sample.blob);

      const res = await fetch("/api/voice-profiles", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "create failed");
      setMsg({ tone: "ok", text: `Created “${name}”.` });
      setName("");
      setSampleUri("");
      setDescription("");
      setConsent(false);
      clearSample();
      await refresh();
    } catch (e) {
      setMsg({ tone: "bad", text: String(e) });
    } finally {
      setBusy(false);
    }
  }

  // Set the agent's voice. `which` is either a cloned profile or a preset id;
  // the one voice applies to every call — web console and phone alike.
  async function setAgentVoice(which: { voice_profile_id: string } | { voice_id: string }) {
    if (!agentId) return;
    setAssigning(true);
    setMsg(null);
    try {
      const res = await fetch(`/api/agents/${encodeURIComponent(agentId)}/voice`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(which),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "assign failed");
      setCurrentVoiceId(data.voice_id ?? null);
      setMsg({ tone: "ok", text: "Voice updated — the next call (web or phone) uses it." });
    } catch (e) {
      setMsg({ tone: "bad", text: String(e) });
    } finally {
      setAssigning(false);
    }
  }

  // Picker option values are prefixed so a cloned profile assigns by its
  // profile id (works even for mock/non-UUID ids) and a library voice by its
  // raw provider voice id.
  function onPickVoice(value: string) {
    if (!value) return;
    const i = value.indexOf(":");
    const kind = value.slice(0, i);
    const id = value.slice(i + 1);
    setAgentVoice(kind === "profile" ? { voice_profile_id: id } : { voice_id: id });
  }

  const columns: Column<VoiceProfile>[] = [
    { key: "name", header: "Voice" },
    { key: "provider", header: "Provider" },
    { key: "status", header: "Status", render: (p) => <Pill tone={statusTone(p.status)}>{p.status}</Pill> },
    {
      key: "assign",
      header: "",
      align: "right",
      render: (p) =>
        p.status === "ready" && agentId ? (
          <SoftButton size="sm" disabled={assigning} onClick={() => setAgentVoice({ voice_profile_id: p.id })}>
            {currentVoiceId && p.provider_voice_id === currentVoiceId ? "In use" : "Use"}
          </SoftButton>
        ) : p.error ? (
          <span style={{ color: "var(--bad-ink)", fontSize: 12 }}>{p.error}</span>
        ) : (
          "—"
        ),
    },
  ];

  const modeTabs: { id: SampleMode; label: string; icon: typeof Mic }[] = [
    { id: "record", label: "Record", icon: Mic },
    { id: "upload", label: "Upload", icon: Upload },
    { id: "url", label: "From URL", icon: Link2 },
  ];

  const readyProfiles = profiles.filter((p) => p.status === "ready" && p.provider_voice_id);
  // Reflect the agent's current voice in the picker: match it to a cloned
  // profile (by provider voice id) or a library voice.
  const currentProfile = readyProfiles.find((p) => p.provider_voice_id === currentVoiceId);
  const currentLibrary = library.find((v) => v.id === currentVoiceId);
  const selectValue = currentProfile
    ? `profile:${currentProfile.id}`
    : currentLibrary
      ? `library:${currentLibrary.id}`
      : "";

  return (
    <Card title="Voice studio" className="stackCard">
      <p style={{ color: "var(--muted)", fontSize: 13, marginTop: 0 }}>
        Pick the voice your agent speaks in — one voice for every call, web and
        phone alike. Choose a branded voice you cloned or a provider library
        voice, or clone a new one below.
      </p>

      {/* Agent voice picker — applies to web + phone calls */}
      <div className="formRow">
        <SoftSelect
          label="Agent voice (web + phone calls)"
          value={selectValue}
          disabled={!agentId || assigning}
          hint={
            currentVoiceId
              ? "Applies to every call. Changes take effect on the next call."
              : "No voice set — the agent uses the platform default until you choose one."
          }
          onChange={(e) => onPickVoice(e.target.value)}
        >
          <option value="">{assigning ? "Updating…" : "— Select a voice —"}</option>
          {readyProfiles.length ? (
            <optgroup label="Your cloned voices">
              {readyProfiles.map((p) => (
                <option key={p.id} value={`profile:${p.id}`}>
                  {p.name}
                </option>
              ))}
            </optgroup>
          ) : null}
          {library.length ? (
            <optgroup label="Provider library">
              {library.map((v) => (
                <option key={v.id} value={`library:${v.id}`}>
                  {v.name}
                  {v.description ? ` — ${v.description}` : ""}
                </option>
              ))}
            </optgroup>
          ) : null}
        </SoftSelect>
      </div>

      <h3 style={{ fontSize: 14, margin: "18px 0 2px" }}>Clone a new branded voice</h3>
      <p style={{ color: "var(--muted)", fontSize: 13, marginTop: 0 }}>
        Record here, upload an audio file, or paste a hosted URL — cloning
        requires the voice owner&apos;s recorded consent.
      </p>

      <div className="formGrid">
        <SoftInput label="Voice name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Front desk – warm" />
        <SoftInput label="Description (optional)" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Calm, professional" />
      </div>

      {/* Sample source: record / upload / URL */}
      <div className="formRow" style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {modeTabs.map((t) => (
          <SoftButton
            key={t.id}
            size="sm"
            variant={mode === t.id ? "primary" : undefined}
            onClick={() => switchMode(t.id)}
          >
            <t.icon size={14} aria-hidden /> {t.label}
          </SoftButton>
        ))}
      </div>

      {mode === "record" ? (
        <div className="formRow" style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          {!recording ? (
            <SoftButton size="sm" onClick={startRecording}>
              <Mic size={14} aria-hidden /> {sample ? "Re-record" : "Start recording"}
            </SoftButton>
          ) : (
            <SoftButton size="sm" variant="primary" onClick={stopRecording}>
              <Square size={14} aria-hidden /> Stop
            </SoftButton>
          )}
          {recording ? <span style={{ color: "var(--bad-ink)", fontSize: 13 }}>● Recording…</span> : null}
        </div>
      ) : null}

      {mode === "upload" ? (
        <div className="formRow">
          <input
            type="file"
            accept="audio/*,.mp3,.wav,.ogg,.oga,.opus,.flac,.webm"
            aria-label="Upload audio sample"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) setSampleFromBlob(f, f.name);
            }}
          />
          <p style={{ color: "var(--muted)", fontSize: 12, margin: "6px 0 0" }}>
            mp3, wav, ogg/opus (incl. WhatsApp voice notes), flac, or webm. m4a/aac
            aren&apos;t supported — convert those first.
          </p>
        </div>
      ) : null}

      {mode === "url" ? (
        <div className="formRow">
          <SoftInput
            label="Sample audio URL"
            value={sampleUri}
            onChange={(e) => setSampleUri(e.target.value)}
            placeholder="https://…/voice-sample.wav"
          />
        </div>
      ) : null}

      {/* Preview for recorded/uploaded audio */}
      {mode !== "url" && sample ? (
        <div className="formRow" style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <audio src={sample.url} controls style={{ height: 36 }} />
          <span style={{ color: "var(--muted)", fontSize: 12 }}>{sample.label}</span>
          <SoftButton size="sm" onClick={clearSample}>
            <Trash2 size={14} aria-hidden /> Clear
          </SoftButton>
        </div>
      ) : null}

      <div className="formRow">
        <Toggle checked={consent} onChange={(e) => setConsent(e.target.checked)} label="I have the voice owner's recorded consent" />
      </div>
      <div className="formRow">
        <SoftButton variant="primary" onClick={create} disabled={busy || !name.trim() || !hasSample || !consent}>
          <Wand2 size={15} aria-hidden /> {busy ? "Cloning…" : "Create voice"}
        </SoftButton>
      </div>
      {msg ? (
        <div className="formRow">
          <Notice tone={msg.tone} title={msg.tone === "ok" ? "Done" : "Error"}>{msg.text}</Notice>
        </div>
      ) : null}

      <div className="formRow">
        <DataTable
          columns={columns}
          rows={profiles}
          getRowKey={(p) => p.id}
          empty={<EmptyState icon={Mic} title="No voices yet">Create a branded voice above.</EmptyState>}
        />
      </div>
    </Card>
  );
}
