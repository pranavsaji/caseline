import { getCall } from "@/lib/api";

export const dynamic = "force-dynamic";

type Turn = { role: string; text: string; ts?: string | null };
type TurnMetric = {
  speech_id: string;
  eou_delay_ms: number;
  llm_ttft_ms: number;
  tts_ttfb_ms: number;
  total_ms: number;
};

export default async function CallDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const call = await getCall(decodeURIComponent(id));
  const transcript: Turn[] = call.transcript ?? [];
  const metrics: TurnMetric[] = call.turn_metrics ?? [];

  return (
    <main>
      <h1>Call {call.id}</h1>
      <p>
        {call.outcome && <span className="pill">{call.outcome}</span>}{" "}
        {call.latency_p95_ms != null && (
          <span className={`pill ${call.latency_p95_ms <= 800 ? "ok" : "bad"}`}>
            {Math.round(call.latency_p95_ms)} ms p95 {call.latency_p95_ms <= 800 ? "(within budget)" : "(over budget)"}
          </span>
        )}{" "}
        {call.recording_uri ? (
          <a href={call.recording_uri}>recording</a>
        ) : (
          <span className="pill muted">no recording</span>
        )}
      </p>
      {call.summary && <p className="notice">{call.summary}</p>}

      <h2>Transcript</h2>
      {transcript.length === 0 ? (
        <div className="empty">No transcript captured for this call.</div>
      ) : (
        transcript.map((t, i) => (
          <div key={i} className={`turn ${t.role === "assistant" ? "assistant" : ""}`}>
            <div className="role">{t.role}</div>
            <div>{t.text}</div>
          </div>
        ))
      )}

      <h2>Per-turn latency</h2>
      {metrics.length === 0 ? (
        <div className="empty">No latency samples.</div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Turn</th>
              <th>EOU delay</th>
              <th>LLM first token</th>
              <th>TTS first byte</th>
              <th>Total</th>
            </tr>
          </thead>
          <tbody>
            {metrics.map((m) => (
              <tr key={m.speech_id}>
                <td>{m.speech_id}</td>
                <td>{Math.round(m.eou_delay_ms)} ms</td>
                <td>{Math.round(m.llm_ttft_ms)} ms</td>
                <td>{Math.round(m.tts_ttfb_ms)} ms</td>
                <td>
                  <span className={`pill ${m.total_ms <= 800 ? "ok" : "bad"}`}>
                    {Math.round(m.total_ms)} ms
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
