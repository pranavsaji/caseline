import Link from "next/link";
import { listCalls, listConsults, listLeads } from "@/lib/api";

export const dynamic = "force-dynamic";

function LatencyPill({ p95 }: { p95: number | null }) {
  if (p95 == null) return <span className="pill muted">no data</span>;
  const cls = p95 <= 650 ? "ok" : p95 <= 800 ? "warn" : "bad";
  return <span className={`pill ${cls}`}>{Math.round(p95)} ms p95</span>;
}

export default async function Home() {
  const [calls, leads, consults] = await Promise.all([
    listCalls(),
    listLeads(),
    listConsults(),
  ]);

  return (
    <main>
      <h1>Intake overview</h1>

      <h2>Calls</h2>
      {calls.length === 0 ? (
        <div className="empty">No calls yet.</div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Call</th>
              <th>Started</th>
              <th>Outcome</th>
              <th>Summary</th>
              <th>Turn latency</th>
            </tr>
          </thead>
          <tbody>
            {calls.map((c) => (
              <tr key={c.id}>
                <td><Link href={`/calls/${encodeURIComponent(c.id)}`}>{c.id}</Link></td>
                <td>{c.started_at?.slice(0, 19)}</td>
                <td>{c.outcome ? <span className="pill">{c.outcome}</span> : "—"}</td>
                <td>{c.summary ?? "—"}</td>
                <td><LatencyPill p95={c.latency_p95_ms} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h2>Leads</h2>
      {leads.length === 0 ? (
        <div className="empty">No leads yet.</div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Contact</th>
              <th>Status</th>
              <th>Practice area</th>
              <th>Call</th>
              <th>CMS</th>
              <th>Created</th>
            </tr>
          </thead>
          <tbody>
            {leads.map((l) => (
              <tr key={l.id}>
                <td>{l.contact_name ?? "Unknown"} {l.contact_phone ? `(${l.contact_phone})` : ""}</td>
                <td><span className="pill">{l.status}</span></td>
                <td>{l.practice_area ?? "—"}</td>
                <td>{l.call_id ? <Link href={`/calls/${encodeURIComponent(l.call_id)}`}>{l.call_id}</Link> : "—"}</td>
                <td>{l.external_cms_id ? <span className="pill ok">synced</span> : <span className="pill muted">pending</span>}</td>
                <td>{l.created_at?.slice(0, 19)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h2>Booked consults</h2>
      {consults.length === 0 ? (
        <div className="empty">No consults booked yet.</div>
      ) : (
        <table>
          <thead>
            <tr><th>Name</th><th>Phone</th><th>Slot</th></tr>
          </thead>
          <tbody>
            {consults.map((c: { id: string; name: string; phone: string; slot_at: string }) => (
              <tr key={c.id}>
                <td>{c.name}</td>
                <td>{c.phone}</td>
                <td>{c.slot_at?.slice(0, 19)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
