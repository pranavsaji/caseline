import Link from "next/link";
import { MessagesSquare } from "lucide-react";
import { getChaserAnalytics, listThreads, type Thread } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import TileRow from "@/components/TileRow";
import PulseTile, { pulseStatus } from "@/components/PulseTile";
import StatTile from "@/components/StatTile";
import Card from "@/components/Card";
import DataTable, { type Column } from "@/components/DataTable";
import Pill, { type PillTone } from "@/components/Pill";
import EmptyState from "@/components/EmptyState";
import TrackerEnroll from "@/components/TrackerEnroll";

export const dynamic = "force-dynamic";

function statusTone(status: string, reason: string | null): { tone: PillTone; label: string } {
  if (status === "open") return { tone: "ok", label: "open" };
  if (reason === "booked") return { tone: "ok", label: "booked" };
  if (reason === "opted_out") return { tone: "bad", label: "opted out" };
  return { tone: "muted", label: reason ?? "closed" };
}

const columns: Column<Thread>[] = [
  {
    key: "id",
    header: "Thread",
    render: (t) => <Link href={`/threads/${encodeURIComponent(t.id)}`}>{t.id.slice(0, 8)}</Link>,
  },
  { key: "channel", header: "Channel", render: (t) => <Pill tone="info">{t.channel}</Pill> },
  {
    key: "goal",
    header: "Goal",
    render: (t) => (t.goal === "treatment_tracker" ? "treatment tracker" : t.goal),
  },
  {
    key: "status",
    header: "Status",
    render: (t) => {
      const s = statusTone(t.status, t.closed_reason);
      return <Pill tone={s.tone}>{s.label}</Pill>;
    },
  },
  {
    key: "last_inbound_at",
    header: "Last inbound",
    render: (t) => (t.last_inbound_at ? t.last_inbound_at.slice(0, 19) : "—"),
  },
  {
    key: "last_outbound_at",
    header: "Last outbound",
    render: (t) => (t.last_outbound_at ? t.last_outbound_at.slice(0, 19) : "—"),
  },
];

export default async function ThreadsPage() {
  const [threads, chaser] = await Promise.all([listThreads(), getChaserAnalytics()]);

  const p95 = chaser.first_contact_p95_seconds;
  const p95Status = p95 == null ? null : pulseStatus(p95, chaser.slo_seconds);

  return (
    <>
      <PageHeader
        title="Threads"
        subtitle="Webform leads and inbound texts, and how fast the chaser reaches them."
      />

      <TileRow>
        <PulseTile
          label="Speed to lead (p95)"
          value={p95 ?? "—"}
          unit={p95 != null ? "s" : undefined}
          status={p95Status}
          hint={`${chaser.slo_seconds}s first-contact SLO · last ${chaser.days}d`}
        />
        <StatTile
          label="Contact rate"
          value={chaser.contact_rate != null ? `${Math.round(chaser.contact_rate * 100)}%` : "—"}
          footer={`${chaser.contacted} of ${chaser.web_ad_leads} web/ad leads`}
        />
        <StatTile
          label="Reached under 60 s"
          value={chaser.under_60s_rate != null ? `${Math.round(chaser.under_60s_rate * 100)}%` : "—"}
          footer={
            chaser.first_contact_p50_seconds != null
              ? `median ${chaser.first_contact_p50_seconds}s`
              : "—"
          }
        />
      </TileRow>

      <Card title="Conversations" className="stackCard">
        <DataTable
          columns={columns}
          rows={threads}
          getRowKey={(t) => t.id}
          empty={
            <EmptyState icon={MessagesSquare} title="No threads yet">
              Webform leads and inbound texts land here — the chaser opens a
              thread and starts working every one within seconds.
            </EmptyState>
          }
        />
      </Card>

      <Card
        title="Enroll in treatment tracker"
        className="stackCard"
      >
        <p style={{ margin: "0 0 14px", color: "var(--muted)", fontSize: 14 }}>
          Enroll a signed client for automated check-ins. Consent rides on the
          representation agreement; a STOP reply always opts them out. Enrolled
          clients open a thread above with goal “treatment tracker”.
        </p>
        <TrackerEnroll />
      </Card>
    </>
  );
}
