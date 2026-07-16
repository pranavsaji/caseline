import Link from "next/link";
import { getChaserAnalytics, listThreads } from "@/lib/api";

export const dynamic = "force-dynamic";

function StatusPill({ status, reason }: { status: string; reason: string | null }) {
  if (status === "open") return <span className="pill ok">open</span>;
  const cls = reason === "booked" ? "ok" : reason === "opted_out" ? "bad" : "muted";
  return <span className={`pill ${cls}`}>{reason ?? "closed"}</span>;
}

export default async function ThreadsPage() {
  const [threads, chaser] = await Promise.all([listThreads(), getChaserAnalytics()]);

  return (
    <main>
      <h1>Threads</h1>

      <h2>Speed to lead (last {chaser.days} days)</h2>
      <table>
        <thead>
          <tr>
            <th>Web/ad leads</th>
            <th>Contacted</th>
            <th>First contact p50</th>
            <th>First contact p95</th>
            <th>Under 60 s</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>{chaser.web_ad_leads}</td>
            <td>
              {chaser.contacted}
              {chaser.contact_rate != null && ` (${Math.round(chaser.contact_rate * 100)}%)`}
            </td>
            <td>{chaser.first_contact_p50_seconds != null ? `${chaser.first_contact_p50_seconds}s` : "—"}</td>
            <td>
              {chaser.first_contact_p95_seconds != null ? (
                <span className={`pill ${chaser.first_contact_p95_seconds <= chaser.slo_seconds ? "ok" : "bad"}`}>
                  {chaser.first_contact_p95_seconds}s
                </span>
              ) : (
                "—"
              )}
            </td>
            <td>{chaser.under_60s_rate != null ? `${Math.round(chaser.under_60s_rate * 100)}%` : "—"}</td>
          </tr>
        </tbody>
      </table>

      <h2>Conversations</h2>
      {threads.length === 0 ? (
        <div className="empty">No threads yet. Webform leads and inbound texts land here.</div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Thread</th>
              <th>Channel</th>
              <th>Goal</th>
              <th>Status</th>
              <th>Last inbound</th>
              <th>Last outbound</th>
            </tr>
          </thead>
          <tbody>
            {threads.map((t) => (
              <tr key={t.id}>
                <td>
                  <Link href={`/threads/${encodeURIComponent(t.id)}`}>{t.id.slice(0, 8)}</Link>
                </td>
                <td>{t.channel}</td>
                <td>{t.goal === "treatment_tracker" ? "treatment tracker" : t.goal}</td>
                <td>
                  <StatusPill status={t.status} reason={t.closed_reason} />
                </td>
                <td>{t.last_inbound_at ? t.last_inbound_at.slice(0, 19) : "—"}</td>
                <td>{t.last_outbound_at ? t.last_outbound_at.slice(0, 19) : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
