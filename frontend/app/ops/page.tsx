import { Activity } from "lucide-react";
import {
  adminEnabled,
  getOpsOverview,
  getOpsAlerts,
  getOnboarding,
  getDeadEvents,
  listMessages,
  listEvents,
  type Message,
} from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import Card from "@/components/Card";
import TileRow from "@/components/TileRow";
import StatTile from "@/components/StatTile";
import DataTable, { type Column } from "@/components/DataTable";
import Pill from "@/components/Pill";
import Notice from "@/components/Notice";
import EmptyState from "@/components/EmptyState";
import EventReplay from "@/components/EventReplay";

export const dynamic = "force-dynamic";

type DeadEvent = Record<string, unknown> & { id: string | number };

async function safe<T>(p: () => Promise<T>): Promise<{ data: T | null; error: string | null }> {
  try {
    return { data: await p(), error: null };
  } catch (e) {
    return { data: null, error: String(e) };
  }
}

const deadColumns: Column<DeadEvent>[] = [
  { key: "id", header: "ID", render: (r) => String(r.id) },
  { key: "type", header: "Type", render: (r) => String(r.type ?? "—") },
  { key: "attempts", header: "Attempts", align: "right", render: (r) => String(r.attempts ?? "—") },
  {
    key: "error",
    header: "Error",
    render: (r) => <span style={{ color: "var(--bad-ink)" }}>{String(r.error ?? "—")}</span>,
  },
  { key: "created_at", header: "Created", render: (r) => String(r.created_at ?? "").slice(0, 19) },
  {
    key: "action",
    header: "",
    align: "right",
    render: (r) => <EventReplay eventId={String(r.id)} />,
  },
];

const messageColumns: Column<Message>[] = [
  { key: "channel", header: "Channel", render: (m) => <Pill tone="info">{m.channel}</Pill> },
  { key: "direction", header: "Dir", render: (m) => m.direction },
  { key: "address", header: "Address" },
  { key: "body", header: "Body", render: (m) => m.body },
  { key: "created_at", header: "At", render: (m) => String(m.created_at ?? "").slice(0, 19) },
];

export default async function OpsPage() {
  // Firm-scoped observability (always available with the firm token).
  const [messages, events] = await Promise.all([
    safe<Message[]>(listMessages),
    safe<Record<string, unknown>[]>(listEvents as () => Promise<Record<string, unknown>[]>),
  ]);

  // Admin-scoped views (only when the deploy secret is configured).
  const [overview, alerts, onboarding, dead] = adminEnabled
    ? await Promise.all([
        safe(getOpsOverview),
        safe(getOpsAlerts),
        safe(getOnboarding),
        safe<DeadEvent[]>(getDeadEvents as () => Promise<DeadEvent[]>),
      ])
    : [null, null, null, null];

  const queue = (overview?.data as { queue?: Record<string, number> } | null)?.queue ?? {};
  const firing = (alerts?.data as { firing?: number } | null)?.firing ?? 0;
  const alertList = (alerts?.data as { alerts?: Record<string, unknown>[] } | null)?.alerts ?? [];
  const deadRows = dead?.data ?? [];
  const eventRows = events.data ?? [];

  return (
    <>
      <PageHeader
        title="Ops & observability"
        subtitle="Messages, the event log, queue health, alerts, and the dead-letter queue."
      />

      <Card title="Messages" className="stackCard">
        {messages.error ? (
          <Notice tone="bad" title="Could not load messages">{messages.error}</Notice>
        ) : (
          <DataTable
            columns={messageColumns}
            rows={messages.data ?? []}
            getRowKey={(m) => m.id}
            empty={<EmptyState icon={Activity} title="No messages">No SMS/email messages yet.</EmptyState>}
          />
        )}
      </Card>

      <Card title="Event log" className="stackCard">
        {events.error ? (
          <Notice tone="bad" title="Could not load events">{events.error}</Notice>
        ) : eventRows.length === 0 ? (
          <EmptyState icon={Activity} title="No events">The event log is empty.</EmptyState>
        ) : (
          <Notice tone="info" title={`${eventRows.length} recent events`}>
            <pre>{JSON.stringify(eventRows.slice(0, 25), null, 2)}</pre>
          </Notice>
        )}
      </Card>

      {!adminEnabled ? (
        <Notice tone="warn" title="Admin views disabled">
          Set <code>CASELINE_ADMIN_TOKEN</code> in the dashboard&apos;s server
          environment to enable platform-admin views (queue, alerts, dead-letter
          replay, onboarding). They are gated by the deploy-level shared secret,
          never a firm token.
        </Notice>
      ) : (
      <>
      <TileRow>
        <StatTile label="Firing alerts" value={firing} footer="live evaluation" />
        <StatTile label="Dead-lettered" value={deadRows.length} footer="awaiting replay" />
        {Object.entries(queue).slice(0, 3).map(([k, v]) => (
          <StatTile key={k} label={`Queue · ${k}`} value={String(v)} />
        ))}
      </TileRow>

      <Card title="Firing alerts" className="stackCard">
        {alerts?.error ? (
          <Notice tone="bad" title="Could not load alerts">{alerts.error}</Notice>
        ) : alertList.length === 0 ? (
          <EmptyState icon={Activity} title="All clear">No alerts firing.</EmptyState>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {alertList.map((a, i) => (
              <Notice key={i} tone="warn" title={String(a.name ?? a.title ?? `Alert ${i + 1}`)}>
                <pre>{JSON.stringify(a, null, 2)}</pre>
              </Notice>
            ))}
          </div>
        )}
      </Card>

      <Card title="Dead-letter queue" className="stackCard">
        {dead?.error ? (
          <Notice tone="bad" title="Could not load dead events">{dead.error}</Notice>
        ) : (
          <DataTable
            columns={deadColumns}
            rows={deadRows}
            getRowKey={(r) => String(r.id)}
            empty={<EmptyState icon={Activity} title="Empty">No dead-lettered events.</EmptyState>}
          />
        )}
      </Card>

      <Card title="Onboarding funnel" className="stackCard">
        {onboarding?.error ? (
          <Notice tone="bad" title="Could not load onboarding">{onboarding.error}</Notice>
        ) : (
          <Notice tone="info" title="Time-to-first-live-call per firm">
            <pre>{JSON.stringify(onboarding?.data, null, 2)}</pre>
          </Notice>
        )}
      </Card>
      </>
      )}
    </>
  );
}
