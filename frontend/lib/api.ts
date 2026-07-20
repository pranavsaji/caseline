// Server-side API client for the Caseline v1 backend.
// The firm token stays on the server: pages and route handlers call these
// helpers; the browser never sees the credential.

const BASE = process.env.CASELINE_API_URL ?? "http://localhost:8000";
const TOKEN = process.env.CASELINE_FIRM_TOKEN ?? "";
const ADMIN_TOKEN = process.env.CASELINE_ADMIN_TOKEN ?? "";

async function api(path: string, init?: RequestInit) {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${TOKEN}`,
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`${init?.method ?? "GET"} ${path} -> ${res.status}: ${await res.text()}`);
  }
  return res.json();
}

// Admin-scoped client — uses the deploy-level shared secret (X-Admin-Token),
// never the firm token. Only reachable server-side; the token never ships to
// the browser. `adminEnabled` lets pages hide admin surfaces when unset.
export const adminEnabled = ADMIN_TOKEN.length > 0;

async function adminApi(path: string, init?: RequestInit) {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "X-Admin-Token": ADMIN_TOKEN,
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`${init?.method ?? "GET"} ${path} -> ${res.status}: ${await res.text()}`);
  }
  return res.json();
}

export type Call = {
  id: string;
  direction: string;
  from_number: string | null;
  started_at: string;
  ended_at: string;
  outcome: string | null;
  caller_type: string | null;
  summary: string | null;
  latency_p50_ms: number | null;
  latency_p95_ms: number | null;
  recording_uri: string | null;
  // Booking is tracked separately from `outcome`: a call can be qualified AND
  // have a consult booked. Derived server-side from the consults table.
  booked?: boolean;
  consult_slot_at?: string | null;
};

export type Lead = {
  id: string;
  source: string;
  status: string;
  practice_area: string | null;
  qualification: Record<string, unknown> | null;
  call_id: string | null;
  external_cms_id: string | null;
  created_at: string;
  contact_name: string | null;
  contact_phone: string | null;
};

export type OutcomeAnalytics = {
  days: number;
  calls: number;
  outcomes: { outcome: string; n: number }[];
  leads: number;
  qualified_leads: number;
  consults_booked: number;
  calls_booked: number;
  transfers: number;
  qualification_rate: number | null;
  booking_rate: number | null;
  call_booking_rate: number | null;
  transfer_rate: number | null;
  abandonment_rate: number | null;
};

export type LatencyAnalytics = {
  days: number;
  slo_ms: number;
  by_day: { day: string; turns: number; p50_ms: number; p95_ms: number }[];
  by_provider: {
    llm_provider: string;
    tts_provider: string;
    turns: number;
    llm_ttft_p95_ms: number;
    tts_ttfb_p95_ms: number;
    total_p95_ms: number;
  }[];
};

export const listCalls = () => api("/v1/calls") as Promise<Call[]>;
export const getCall = (id: string) => api(`/v1/calls/${encodeURIComponent(id)}`);
export const listLeads = () => api("/v1/leads") as Promise<Lead[]>;
export const listConsults = () => api("/v1/consults");
export const getAgentConfig = () => api("/v1/agent-config");
export const getOutcomeAnalytics = (days = 30) =>
  api(`/v1/analytics/outcomes?days=${days}`) as Promise<OutcomeAnalytics>;
export const getLatencyAnalytics = (days = 7) =>
  api(`/v1/analytics/latency?days=${days}`) as Promise<LatencyAnalytics>;
export const putAgentConfig = (agentId: string, body: unknown) =>
  api(`/v1/agents/${agentId}/config`, { method: "PUT", body: JSON.stringify(body) });

// --- LLM model selection (Config Studio) ---

export type LlmProvider = {
  provider: string;
  label: string;
  env_key: string | null;
  /** What the operator must set for this provider to work (API key env var, or
   *  OLLAMA_BASE_URL for a local Ollama server). */
  requires: string | null;
  /** Whether that requirement is satisfied — i.e. this provider can actually
   *  serve a call. Unconfigured providers are shown but not selectable. */
  configured: boolean;
  default_model: string;
  models: string[];
};

export const getLlmProviders = () =>
  api("/v1/llm-providers") as Promise<{ providers: LlmProvider[] }>;

// --- Phase 3: omnichannel ---

export type Thread = {
  id: string;
  channel: string;
  address: string;
  goal: string;
  status: string;
  closed_reason: string | null;
  lead_id: string | null;
  created_at: string;
  updated_at: string;
  last_inbound_at: string;
  last_outbound_at: string;
};

export type ThreadDetail = Thread & {
  state: Record<string, unknown>;
  messages: { direction: string; body: string; ts: string }[];
};

export type ChaserAnalytics = {
  days: number;
  slo_seconds: number;
  web_ad_leads: number;
  contacted: number;
  contact_rate: number | null;
  first_contact_p50_seconds: number | null;
  first_contact_p95_seconds: number | null;
  under_60s_rate: number | null;
};

export type PreviewResult = {
  turns: { role: string; text: string; guardrail_tripped?: string | null }[];
  actions: Record<string, unknown>[];
  closed_reason: string | null;
  final_step: string | null;
  instructions: string;
};

export const listThreads = () => api("/v1/threads") as Promise<Thread[]>;
export const getThread = (id: string) =>
  api(`/v1/threads/${encodeURIComponent(id)}`) as Promise<ThreadDetail>;
export const getChaserAnalytics = (days = 30) =>
  api(`/v1/analytics/chaser?days=${days}`) as Promise<ChaserAnalytics>;
export const previewTestCall = (agentId: string, body: unknown) =>
  api(`/v1/agents/${agentId}/preview`, {
    method: "POST",
    body: JSON.stringify(body),
  }) as Promise<PreviewResult>;

// --- Phase 4: differentiation ---

export type BenchmarkMetric = {
  label: string;
  own: number | null;
  higher_is_better: boolean;
  cohort: { p25: number; p50: number; p75: number; firms: number } | null;
  percentile_rank: number | null;
};

export type BenchmarkReport = {
  days: number;
  own_leads: number;
  cohort_firms: number;
  suppressed: boolean;
  suppressed_reason: string | null;
  metrics: Record<string, BenchmarkMetric>;
};

export type TuningSuggestion = {
  kind: string;
  detail: string;
  evidence: Record<string, unknown>;
};

export type TuningReport = {
  days: number;
  reviews: number;
  agreement_rate: number | null;
  matrix: Record<string, Record<string, number>>;
  suggestions: TuningSuggestion[];
  current_rules: Record<string, unknown>;
  proposed_rules: Record<string, unknown> | null;
};

export type Referral = {
  id: string;
  lead_id: string;
  status: string;
  match_reasons: string[];
  client_consent: boolean;
  sent_at: string | null;
  created_at: string;
  partner_name: string;
  contact_name: string | null;
  practice_area: string | null;
};

export type ReferralPartner = {
  id: string;
  name: string;
  practice_areas: string[];
  states: string[];
  contact_email: string | null;
  contact_phone: string | null;
  active: boolean;
  notes: string | null;
  created_at: string;
};

export type VoiceProfile = {
  id: string;
  name: string;
  provider: string;
  provider_voice_id: string | null;
  status: string;
  sample_uri: string | null;
  error: string | null;
  created_at: string;
};

export const getBenchmarks = (days = 30) =>
  api(`/v1/analytics/benchmarks?days=${days}`) as Promise<BenchmarkReport>;
export const getTuningSuggestions = (days = 90) =>
  api(`/v1/tuning/suggestions?days=${days}`) as Promise<TuningReport>;
export const listReferrals = () => api("/v1/referrals") as Promise<Referral[]>;
export const listReferralPartners = () =>
  api("/v1/referral-partners") as Promise<ReferralPartner[]>;
export const listVoiceProfiles = () => api("/v1/voice-profiles") as Promise<VoiceProfile[]>;

export type LibraryVoice = {
  id: string;
  name: string;
  description: string | null;
  language: string | null;
  gender: string | null;
};

// Provider preset/library voices, selectable alongside the firm's own clones.
export const listVoiceLibrary = () => api("/v1/voice-library") as Promise<LibraryVoice[]>;

// --- Outbound calling (operator-initiated) ---

export type DialResult = {
  call_id: string;
  room: string;
  to_number: string;
  dialer: string;
  provider_id: string;
  placed: boolean;
  note: string | null;
};

export const dialCall = (body: {
  to_number: string;
  agent_id?: string;
  purpose?: string;
}) =>
  api("/v1/calls/dial", { method: "POST", body: JSON.stringify(body) }) as Promise<DialResult>;

export type HangupResult = { status: "ended" | "already_ended"; call_id: string };

// Operator hang up: tear down the call's LiveKit room (ends the SIP leg + agent).
export const hangupCall = (callId: string) =>
  api(`/v1/calls/${encodeURIComponent(callId)}/hangup`, { method: "POST" }) as Promise<HangupResult>;

// Browser voice test: server mints a LiveKit token; the browser joins the room
// and talks to the intake agent over WebRTC (no phone, no telephony charge).
export type WebSession = {
  room: string;
  url: string;
  token: string;
  identity: string;
};

export const startWebSession = () =>
  api("/v1/calls/web-session", { method: "POST" }) as Promise<WebSession>;

// --- dashboard operator auth (server-side; the firm token authenticates the
// call to the backend, the browser only ever talks to the Next auth routes).
// Self-serve signup is disabled — accounts are provisioned via
// scripts/create_dashboard_user.py, so only login is exposed here. ---

export const loginUser = (email: string, password: string) =>
  api("/v1/dashboard/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  }) as Promise<{ ok: boolean; email: string }>;

// --- Write actions surfacing existing backend endpoints ---

export const createVoiceProfile = (body: {
  name: string;
  // One of sample_uri (pre-hosted http(s) URL) or sample_data (inline
  // base64 data URI from an in-browser recording / file upload) is required.
  sample_uri?: string;
  sample_data?: string;
  consent_confirmed: boolean;
  description?: string;
}) => api("/v1/voice-profiles", { method: "POST", body: JSON.stringify(body) });

export type DeleteVoiceResult = { status: string; voice_profile_id: string; cleared_agent_voice: boolean };

// Remove a cloned voice profile. If it was the agent's current voice, the
// backend clears that assignment (next call reverts to the default).
export const deleteVoiceProfile = (id: string) =>
  api(`/v1/voice-profiles/${encodeURIComponent(id)}`, { method: "DELETE" }) as Promise<DeleteVoiceResult>;

// Assign a voice to the agent: either a cloned profile or a preset voice id.
export const assignAgentVoice = (
  agentId: string,
  which: { voice_profile_id: string } | { voice_id: string },
) =>
  api(`/v1/agents/${encodeURIComponent(agentId)}/voice`, {
    method: "POST",
    body: JSON.stringify(which),
  });

export const reviewLead = (
  leadId: string,
  body: { verdict: string; reviewer?: string; reason?: string },
) =>
  api(`/v1/leads/${encodeURIComponent(leadId)}/review`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const createReferralPartner = (body: {
  name: string;
  practice_areas?: string[];
  states?: string[];
  contact_email?: string;
  contact_phone?: string;
  notes?: string;
}) => api("/v1/referral-partners", { method: "POST", body: JSON.stringify(body) });

export const sendReferral = (referralId: string, clientConsent: boolean) =>
  api(`/v1/referrals/${encodeURIComponent(referralId)}/send`, {
    method: "POST",
    body: JSON.stringify({ client_consent: clientConsent }),
  });

export const setReferralStatus = (referralId: string, status: string) =>
  api(`/v1/referrals/${encodeURIComponent(referralId)}/status`, {
    method: "POST",
    body: JSON.stringify({ status }),
  });

export const enrollTracker = (body: {
  name: string;
  phone: string;
  matter_description?: string;
  cadence_days?: number;
}) => api("/v1/tracker/enroll", { method: "POST", body: JSON.stringify(body) });

// Apply the engine's proposed qualification rules to the live intake agent.
// The backend recomputes proposed rules server-side, so no payload is needed.
export const applyTuning = (days = 90) =>
  api(`/v1/tuning/apply?days=${days}`, { method: "POST" }) as Promise<{
    status: string;
    agent_id: string;
    applied_rules: Record<string, unknown>;
  }>;

// Manual disposition override on a call.
export const setCallOutcome = (callId: string, outcome: string, note?: string) =>
  api(`/v1/calls/${encodeURIComponent(callId)}/outcome`, {
    method: "POST",
    body: JSON.stringify({ outcome, note }),
  });

// Staff-authored follow-up on an open thread (the manual chaser override).
export const sendThreadMessage = (threadId: string, body: string) =>
  api(`/v1/threads/${encodeURIComponent(threadId)}/message`, {
    method: "POST",
    body: JSON.stringify({ body }),
  });

// --- Messaging / events (firm-scoped reads) ---

export type Message = {
  id: string;
  channel: string;
  direction: string;
  address: string;
  body: string;
  created_at: string;
};
export const listMessages = () => api("/v1/messages") as Promise<Message[]>;
export const listEvents = () => api("/v1/events");

// --- Admin ops (admin-token scoped) ---

export const getOpsOverview = () => adminApi("/v1/admin/ops/overview");
export const getOpsAlerts = () => adminApi("/v1/admin/ops/alerts");
export const getOnboarding = () => adminApi("/v1/admin/ops/onboarding");
export const getDeadEvents = () => adminApi("/v1/admin/events/dead");
export const replayEvent = (eventId: string) =>
  adminApi(`/v1/admin/events/${encodeURIComponent(eventId)}/replay`, { method: "POST" });
