import Link from "next/link";
import { PhoneCall, Users, CalendarCheck } from "lucide-react";
import {
  listCalls,
  listConsults,
  listLeads,
  getLatencyAnalytics,
  getOutcomeAnalytics,
  type Call,
  type Lead,
} from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import TileRow from "@/components/TileRow";
import StatTile from "@/components/StatTile";
import PulseTile from "@/components/PulseTile";
import Card from "@/components/Card";
import DataTable, { type Column } from "@/components/DataTable";
import Pill from "@/components/Pill";
import EmptyState from "@/components/EmptyState";
import SoftButton from "@/components/SoftButton";
import { pulseStatus } from "@/components/PulseTile";

export const dynamic = "force-dynamic";

const LATENCY_BUDGET_MS = 800;

function LatencyPill({ p95 }: { p95: number | null }) {
  if (p95 == null) return <Pill tone="muted">no data</Pill>;
  const status = pulseStatus(p95, LATENCY_BUDGET_MS, { warnRatio: 650 / LATENCY_BUDGET_MS });
  return <Pill tone={status ?? "muted"}>{Math.round(p95)} ms p95</Pill>;
}

function pct(rate: number | null): string {
  return rate == null ? "—" : `${Math.round(rate * 100)}%`;
}

type Consult = { id: string; name: string; phone: string; slot_at: string };

const callColumns: Column<Call>[] = [
  {
    key: "id",
    header: "Call",
    render: (c) => <Link href={`/calls/${encodeURIComponent(c.id)}`}>{c.id}</Link>,
  },
  { key: "started_at", header: "Started", render: (c) => c.started_at?.slice(0, 19) ?? "—" },
  {
    key: "outcome",
    header: "Outcome",
    render: (c) => (c.outcome ? <Pill tone="info">{c.outcome}</Pill> : "—"),
  },
  { key: "summary", header: "Summary", render: (c) => c.summary ?? "—" },
  {
    key: "latency",
    header: "Answer speed",
    align: "right",
    render: (c) => <LatencyPill p95={c.latency_p95_ms} />,
  },
];

const leadColumns: Column<Lead>[] = [
  {
    key: "contact",
    header: "Contact",
    render: (l) =>
      `${l.contact_name ?? "Unknown"}${l.contact_phone ? ` (${l.contact_phone})` : ""}`,
  },
  { key: "status", header: "Status", render: (l) => <Pill tone="info">{l.status}</Pill> },
  { key: "practice_area", header: "Practice area", render: (l) => l.practice_area ?? "—" },
  {
    key: "call_id",
    header: "Call",
    render: (l) =>
      l.call_id ? (
        <Link href={`/calls/${encodeURIComponent(l.call_id)}`}>{l.call_id}</Link>
      ) : (
        "—"
      ),
  },
  {
    key: "cms",
    header: "CMS",
    render: (l) =>
      l.external_cms_id ? <Pill tone="ok">synced</Pill> : <Pill tone="muted">pending</Pill>,
  },
  { key: "created_at", header: "Created", render: (l) => l.created_at?.slice(0, 19) ?? "—" },
];

const consultColumns: Column<Consult>[] = [
  { key: "name", header: "Name" },
  { key: "phone", header: "Phone" },
  { key: "slot_at", header: "Slot", render: (c) => c.slot_at?.slice(0, 19) ?? "—" },
];

export default async function Home() {
  const [calls, leads, consults, latency, outcomes] = await Promise.all([
    listCalls(),
    listLeads(),
    listConsults() as Promise<Consult[]>,
    getLatencyAnalytics(7),
    getOutcomeAnalytics(30),
  ]);

  // Overall answer speed: the worst (highest) recent daily p95, so the tile
  // reflects the SLO ceiling a caller could hit rather than a flattering mean.
  const p95 = latency.by_day.length
    ? Math.round(Math.max(...latency.by_day.map((d) => d.p95_ms)))
    : null;

  return (
    <>
      <PageHeader
        title="Intake overview"
        subtitle="Every call, lead, and booked consult your front desk handled — at a glance."
      />

      <TileRow>
        <PulseTile
          label="Answer speed (p95)"
          value={p95 ?? "—"}
          unit={p95 != null ? "ms" : undefined}
          status={p95 == null ? null : pulseStatus(p95, LATENCY_BUDGET_MS, { warnRatio: 650 / LATENCY_BUDGET_MS })}
          hint={`${LATENCY_BUDGET_MS} ms per-turn budget · last ${latency.days}d`}
        />
        <StatTile
          label="Consults booked"
          value={outcomes.consults_booked}
          footer={`last ${outcomes.days} days`}
        />
        <StatTile label="Qualification rate" value={pct(outcomes.qualification_rate)} footer={`${outcomes.leads} leads`} />
      </TileRow>

      <Card title="Recent calls" className="stackCard">
        <DataTable
          columns={callColumns}
          rows={calls}
          getRowKey={(c) => c.id}
          empty={
            <EmptyState icon={PhoneCall} title="No calls yet">
              Once your number is live, every call shows up here within seconds —
              with its outcome, summary, and answer speed.
            </EmptyState>
          }
        />
      </Card>

      <Card title="Leads" className="stackCard">
        <DataTable
          columns={leadColumns}
          rows={leads}
          getRowKey={(l) => l.id}
          empty={
            <EmptyState icon={Users} title="No leads yet">
              Qualified callers become leads here and sync to your CMS
              automatically.
            </EmptyState>
          }
        />
      </Card>

      <Card title="Booked consults" className="stackCard">
        <DataTable
          columns={consultColumns}
          rows={consults}
          getRowKey={(c) => c.id}
          empty={
            <EmptyState
              icon={CalendarCheck}
              title="No consults booked yet"
              action={
                <Link href="/studio">
                  <SoftButton>Tune booking in Studio</SoftButton>
                </Link>
              }
            >
              When the agent books a consult, it lands here with the caller and
              their slot.
            </EmptyState>
          }
        />
      </Card>
    </>
  );
}
