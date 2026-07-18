"use client";

// Model studio: pick the LLM provider + model the firm's calls and threads run
// on. The choice persists to the agent's llm_config and reaches the next call
// within seconds (same short-TTL config cache as every other Config Studio
// edit) — no worker restart. An optional fallback provider gives mid-call
// failover if the primary errors or times out.
//
// The value is stored as a `provider:model[,provider:model]` spec — the exact
// format the worker env (CASELINE_LLM_PROVIDERS) uses — so what you select here
// is byte-for-byte what the voice worker builds. All calls go through BFF
// routes; the firm token stays server-side.
import { useEffect, useMemo, useState } from "react";
import { Save } from "lucide-react";
import type { LlmProvider } from "@/lib/api";
import Card from "@/components/Card";
import SoftButton from "@/components/SoftButton";
import SoftInput from "@/components/inputs/SoftInput";
import SoftSelect from "@/components/inputs/SoftSelect";
import Toggle from "@/components/Toggle";
import Pill from "@/components/Pill";
import Notice from "@/components/Notice";

type Slot = { provider: string; model: string };

function parseSpec(spec: string): { primary: Slot; fallback: Slot | null } {
  const parts = spec
    .split(",")
    .map((p) => p.trim())
    .filter(Boolean)
    .map((p) => {
      const [provider, ...rest] = p.split(":");
      return { provider: provider.trim(), model: rest.join(":").trim() };
    });
  return { primary: parts[0] ?? { provider: "", model: "" }, fallback: parts[1] ?? null };
}

function buildSpec(primary: Slot, fallback: Slot | null): string {
  const one = (s: Slot) => (s.provider && s.model ? `${s.provider}:${s.model}` : "");
  return [one(primary), fallback ? one(fallback) : ""].filter(Boolean).join(",");
}

export default function ModelManager() {
  const [agentId, setAgentId] = useState<string | null>(null);
  const [catalog, setCatalog] = useState<LlmProvider[]>([]);
  const [primary, setPrimary] = useState<Slot>({ provider: "", model: "" });
  const [fallbackOn, setFallbackOn] = useState(false);
  const [fallback, setFallback] = useState<Slot>({ provider: "", model: "" });
  // "Custom" mode reveals a free-text field for a model id not in the dropdown.
  const [primaryCustom, setPrimaryCustom] = useState(false);
  const [fallbackCustom, setFallbackCustom] = useState(false);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<{ tone: "ok" | "bad"; text: string } | null>(null);

  useEffect(() => {
    Promise.all([
      fetch("/api/config").then((r) => (r.ok ? r.json() : Promise.reject(r))),
      fetch("/api/llm-providers").then((r) => (r.ok ? r.json() : Promise.reject(r))),
    ])
      .then(([config, providers]) => {
        setAgentId(config.agent_id ?? null);
        const list: LlmProvider[] = providers.providers ?? [];
        setCatalog(list);
        const modelsOf = (p: string) => list.find((x) => x.provider === p)?.models ?? [];
        const spec: string = config?.llm?.providers ?? "";
        if (spec) {
          const { primary: p, fallback: f } = parseSpec(spec);
          setPrimary(p);
          setPrimaryCustom(Boolean(p.model) && !modelsOf(p.provider).includes(p.model));
          if (f) {
            setFallbackOn(true);
            setFallback(f);
            setFallbackCustom(Boolean(f.model) && !modelsOf(f.provider).includes(f.model));
          }
        } else if (list.length) {
          // Default the picker to the first provider that already has a key.
          const seed = list.find((p) => p.key_present) ?? list[0];
          setPrimary({ provider: seed.provider, model: seed.default_model });
        }
      })
      .catch(() => setMsg({ tone: "bad", text: "Could not load model settings." }));
  }, []);

  const byProvider = useMemo(
    () => Object.fromEntries(catalog.map((p) => [p.provider, p])),
    [catalog],
  );

  const CUSTOM = "__custom__";

  function pickProvider(slot: "primary" | "fallback", provider: string) {
    const entry = byProvider[provider];
    const next: Slot = { provider, model: entry?.default_model ?? "" };
    if (slot === "primary") {
      setPrimary(next);
      setPrimaryCustom(false);
    } else {
      setFallback(next);
      setFallbackCustom(false);
    }
  }

  // A model dropdown selection: a real model id sets it; the "Custom…" sentinel
  // flips the slot into free-text mode.
  function pickModel(
    value: string,
    setSlot: (fn: (s: Slot) => Slot) => void,
    setCustom: (b: boolean) => void,
  ) {
    if (value === CUSTOM) {
      setCustom(true);
      setSlot((s) => ({ ...s, model: "" }));
    } else {
      setCustom(false);
      setSlot((s) => ({ ...s, model: value }));
    }
  }

  const spec = buildSpec(primary, fallbackOn ? fallback : null);
  const primaryEntry = byProvider[primary.provider];
  const fallbackEntry = byProvider[fallback.provider];
  const missingKey =
    (primary.provider && primaryEntry && !primaryEntry.key_present ? primaryEntry : null) ||
    (fallbackOn && fallback.provider && fallbackEntry && !fallbackEntry.key_present
      ? fallbackEntry
      : null);

  async function save() {
    if (!agentId || !primary.provider || !primary.model) return;
    setSaving(true);
    setMsg(null);
    try {
      const res = await fetch("/api/config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ agent_id: agentId, llm_config: { providers: spec } }),
      });
      if (!res.ok) throw new Error(await res.text());
      setMsg({ tone: "ok", text: `Saved — calls now run on ${spec}.` });
    } catch (err) {
      setMsg({ tone: "bad", text: `Save failed: ${String(err)}` });
    } finally {
      setSaving(false);
    }
  }

  const slotRow = (
    slot: "primary" | "fallback",
    value: Slot,
    setSlot: (fn: (s: Slot) => Slot) => void,
    custom: boolean,
    setCustom: (b: boolean) => void,
  ) => {
    const models = byProvider[value.provider]?.models ?? [];
    return (
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <SoftSelect
          label="Provider"
          value={value.provider}
          onChange={(e) => pickProvider(slot, e.target.value)}
        >
          <option value="">Select…</option>
          {catalog.map((p) => (
            <option key={p.provider} value={p.provider}>
              {p.label}
              {p.key_present ? "" : " — no key"}
            </option>
          ))}
        </SoftSelect>
        <div>
          <SoftSelect
            label="Model"
            value={custom ? CUSTOM : value.model}
            onChange={(e) => pickModel(e.target.value, setSlot, setCustom)}
            disabled={!value.provider}
          >
            {models.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
            <option value={CUSTOM}>Custom model id…</option>
          </SoftSelect>
          {custom ? (
            <div style={{ marginTop: 8 }}>
              <SoftInput
                placeholder="e.g. gpt-5.4-nano"
                value={value.model}
                onChange={(e) => setSlot((s) => ({ ...s, model: e.target.value }))}
                hint="Any model id the provider supports."
              />
            </div>
          ) : null}
        </div>
      </div>
    );
  };

  return (
    <Card title="Conversation model" className="stackCard">
      <p style={{ color: "var(--muted)", fontSize: 14, margin: "0 0 16px" }}>
        Choose the LLM that reasons and speaks on every call and SMS thread.
        Switching here lets you compare providers on latency and quality without
        touching code — the next call picks it up within seconds.
      </p>

      {slotRow("primary", primary, setPrimary, primaryCustom, setPrimaryCustom)}

      <div style={{ marginTop: 16 }}>
        <Toggle
          checked={fallbackOn}
          onChange={(e) => setFallbackOn(e.target.checked)}
          label="Add a fallback model (mid-call failover if the primary errors)"
        />
      </div>
      {fallbackOn ? (
        <div style={{ marginTop: 12 }}>
          {slotRow("fallback", fallback, setFallback, fallbackCustom, setFallbackCustom)}
        </div>
      ) : null}

      {missingKey ? (
        <Notice tone="warn" title={`${missingKey.label} has no API key`}>
          Add <code>{missingKey.env_key}</code> to the worker&apos;s <code>.env</code> and
          restart it. Until then, calls fall back to the next configured provider
          (or the worker default).
        </Notice>
      ) : null}

      <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 16 }}>
        <SoftButton
          variant="primary"
          onClick={save}
          disabled={saving || !agentId || !primary.provider || !primary.model}
        >
          <Save size={15} aria-hidden style={{ marginRight: 6 }} />
          {saving ? "Saving…" : "Save model"}
        </SoftButton>
        {spec ? <Pill tone="info">{spec}</Pill> : null}
      </div>

      {msg ? (
        <div style={{ marginTop: 12 }}>
          <Notice tone={msg.tone === "ok" ? "ok" : "bad"}>{msg.text}</Notice>
        </div>
      ) : null}
    </Card>
  );
}
