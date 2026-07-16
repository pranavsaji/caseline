// Server-side API client for the Caseline v1 backend.
// The firm token stays on the server: pages and route handlers call these
// helpers; the browser never sees the credential.

const BASE = process.env.CASELINE_API_URL ?? "http://localhost:8000";
const TOKEN = process.env.CASELINE_FIRM_TOKEN ?? "";

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
  transfers: number;
  qualification_rate: number | null;
  booking_rate: number | null;
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
