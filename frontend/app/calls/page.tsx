import Link from "next/link";
import { PhoneCall } from "lucide-react";
import { listCalls, type Call } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import Card from "@/components/Card";
import DataTable, { type Column } from "@/components/DataTable";
import Pill from "@/components/Pill";
import EmptyState from "@/components/EmptyState";
import CallConsole from "@/components/CallConsole";
import WebVoiceConsole from "@/components/WebVoiceConsole";
import { pulseStatus } from "@/components/PulseTile";

export const dynamic = "force-dynamic";

const LATENCY_BUDGET_MS = 800;

function LatencyPill({ p95 }: { p95: number | null }) {
  if (p95 == null) return <Pill tone="muted">no data</Pill>;
  const status = pulseStatus(p95, LATENCY_BUDGET_MS, { warnRatio: 650 / LATENCY_BUDGET_MS });
  return <Pill tone={status ?? "muted"}>{Math.round(p95)} ms p95</Pill>;
}

const callColumns: Column<Call>[] = [
  {
    key: "id",
    header: "Call",
    render: (c) => <Link href={`/calls/${encodeURIComponent(c.id)}`}>{c.id}</Link>,
  },
  {
    key: "direction",
    header: "Dir",
    render: (c) => (
      <Pill tone={c.direction === "out" ? "info" : "ok"}>{c.direction === "out" ? "outbound" : "inbound"}</Pill>
    ),
  },
  { key: "from_number", header: "Number", render: (c) => c.from_number ?? "—" },
  { key: "started_at", header: "Started", render: (c) => c.started_at?.slice(0, 19) ?? "—" },
  {
    key: "outcome",
    header: "Outcome",
    render: (c) => (
      <span style={{ display: "inline-flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
        {c.outcome ? <Pill tone="info">{c.outcome}</Pill> : "—"}
        {c.booked ? <Pill tone="ok">booked</Pill> : null}
      </span>
    ),
  },
  {
    key: "latency",
    header: "Answer speed",
    align: "right",
    render: (c) => <LatencyPill p95={c.latency_p95_ms} />,
  },
];

export default async function CallsPage() {
  const calls = await listCalls();

  return (
    <>
      <PageHeader
        title="Calls"
        subtitle="Place a live call, simulate a test call, and review every conversation your front desk handled."
      />

      <WebVoiceConsole />

      <CallConsole />

      <Card title="Recent calls" className="stackCard">
        <DataTable
          columns={callColumns}
          rows={calls}
          getRowKey={(c) => c.id}
          empty={
            <EmptyState icon={PhoneCall} title="No calls yet">
              Place a call above, or once your number is live every inbound call
              lands here within seconds.
            </EmptyState>
          }
        />
      </Card>
    </>
  );
}
