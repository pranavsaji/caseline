import { getLatencyAnalytics, getOutcomeAnalytics } from "@/lib/api";

export const dynamic = "force-dynamic";

function pct(rate: number | null): string {
  return rate == null ? "—" : `${Math.round(rate * 100)}%`;
}

function SloPill({ p95, slo }: { p95: number | null; slo: number }) {
  if (p95 == null) return <span className="pill muted">no data</span>;
  const cls = p95 <= 650 ? "ok" : p95 <= slo ? "warn" : "bad";
  return <span className={`pill ${cls}`}>{Math.round(p95)} ms</span>;
}

export default async function Analytics() {
  const [outcomes, latency] = await Promise.all([
    getOutcomeAnalytics(30),
    getLatencyAnalytics(7),
  ]);

  const stats: [string, string][] = [
    ["Calls (30d)", String(outcomes.calls)],
    ["Qualification rate", pct(outcomes.qualification_rate)],
    ["Booking rate", pct(outcomes.booking_rate)],
    ["Transfer rate", pct(outcomes.transfer_rate)],
    ["Abandonment", pct(outcomes.abandonment_rate)],
    ["Consults booked", String(outcomes.consults_booked)],
  ];

  return (
    <main>
      <h1>Analytics</h1>

      <h2>Intake funnel (last {outcomes.days} days)</h2>
      <table>
        <thead>
          <tr>{stats.map(([label]) => <th key={label}>{label}</th>)}</tr>
        </thead>
        <tbody>
          <tr>{stats.map(([label, value]) => <td key={label}>{value}</td>)}</tr>
        </tbody>
      </table>

      <h2>Call outcomes</h2>
      {outcomes.outcomes.length === 0 ? (
        <div className="empty">No calls yet.</div>
      ) : (
        <table>
          <thead>
            <tr><th>Outcome</th><th>Calls</th></tr>
          </thead>
          <tbody>
            {outcomes.outcomes.map((o) => (
              <tr key={o.outcome}>
                <td><span className="pill">{o.outcome}</span></td>
                <td>{o.n}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h2>Turn latency by day (last {latency.days} days, SLO {latency.slo_ms} ms p95)</h2>
      {latency.by_day.length === 0 ? (
        <div className="empty">No turn metrics yet.</div>
      ) : (
        <table>
          <thead>
            <tr><th>Day</th><th>Turns</th><th>p50</th><th>p95</th></tr>
          </thead>
          <tbody>
            {latency.by_day.map((d) => (
              <tr key={d.day}>
                <td>{d.day}</td>
                <td>{d.turns}</td>
                <td>{Math.round(d.p50_ms)} ms</td>
                <td><SloPill p95={d.p95_ms} slo={latency.slo_ms} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h2>Latency by provider</h2>
      {latency.by_provider.length === 0 ? (
        <div className="empty">No provider-tagged turns yet.</div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>LLM</th>
              <th>TTS</th>
              <th>Turns</th>
              <th>LLM TTFT p95</th>
              <th>TTS TTFB p95</th>
              <th>Total p95</th>
            </tr>
          </thead>
          <tbody>
            {latency.by_provider.map((p) => (
              <tr key={`${p.llm_provider}|${p.tts_provider}`}>
                <td>{p.llm_provider}</td>
                <td>{p.tts_provider}</td>
                <td>{p.turns}</td>
                <td>{Math.round(p.llm_ttft_p95_ms)} ms</td>
                <td>{Math.round(p.tts_ttfb_p95_ms)} ms</td>
                <td><SloPill p95={p.total_p95_ms} slo={latency.slo_ms} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
