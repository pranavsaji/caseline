import { Radio, ListTree, CalendarCheck } from "lucide-react";
import { getCall } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import TileRow from "@/components/TileRow";
import PulseTile, { pulseStatus } from "@/components/PulseTile";
import StatTile from "@/components/StatTile";
import Card from "@/components/Card";
import Pill from "@/components/Pill";
import Notice from "@/components/Notice";
import EmptyState from "@/components/EmptyState";
import SoftButton from "@/components/SoftButton";
import DataTable, { type Column } from "@/components/DataTable";
import TranscriptTurn, { TranscriptList } from "@/components/TranscriptTurn";
import CallDisposition from "@/components/CallDisposition";

export const dynamic = "force-dynamic";

const LATENCY_BUDGET_MS = 800;

type Turn = { role: string; text: string; ts?: string | null };
type TurnMetric = {
  speech_id: string;
  eou_delay_ms: number;
  llm_ttft_ms: number;
  tts_ttfb_ms: number;
  total_ms: number;
};

const metricColumns: Column<TurnMetric>[] = [
  { key: "speech_id", header: "Turn" },
  {
    key: "eou_delay_ms",
    header: "EOU delay",
    align: "right",
    render: (m) => `${Math.round(m.eou_delay_ms)} ms`,
  },
  {
    key: "llm_ttft_ms",
    header: "LLM first token",
    align: "right",
    render: (m) => `${Math.round(m.llm_ttft_ms)} ms`,
  },
  {
    key: "tts_ttfb_ms",
    header: "TTS first byte",
    align: "right",
    render: (m) => `${Math.round(m.tts_ttfb_ms)} ms`,
  },
  {
    key: "total_ms",
    header: "Total",
    align: "right",
    render: (m) => (
      <Pill tone={pulseStatus(m.total_ms, LATENCY_BUDGET_MS, { warnRatio: 650 / LATENCY_BUDGET_MS }) ?? "muted"}>
        {Math.round(m.total_ms)} ms
      </Pill>
    ),
  },
];

export default async function CallDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const call = await getCall(decodeURIComponent(id));
  const transcript: Turn[] = call.transcript ?? [];
  const metrics: TurnMetric[] = call.turn_metrics ?? [];
  const p95: number | null = call.latency_p95_ms ?? null;
  const p95Status = p95 == null ? null : pulseStatus(p95, LATENCY_BUDGET_MS, { warnRatio: 650 / LATENCY_BUDGET_MS });

  return (
    <>
      <PageHeader
        title={`Call ${call.id}`}
        subtitle={call.started_at ? `Started ${String(call.started_at).slice(0, 19)}` : undefined}
        actions={
          <>
            {call.outcome ? <Pill tone="info">{call.outcome}</Pill> : null}
            {call.booked ? (
              <Pill tone="ok" dot>
                <CalendarCheck size={13} aria-hidden />{" "}
                {call.consult_slot_at
                  ? `Consult ${String(call.consult_slot_at).slice(0, 16).replace("T", " ")}`
                  : "Consult booked"}
              </Pill>
            ) : null}
            {call.recording_uri ? (
              <a href={call.recording_uri}>
                <SoftButton size="sm">
                  <Radio size={15} aria-hidden /> Recording
                </SoftButton>
              </a>
            ) : (
              <Pill tone="muted">no recording</Pill>
            )}
          </>
        }
      />

      <TileRow>
        <PulseTile
          label="Answer speed (p95)"
          value={p95 ?? "—"}
          unit={p95 != null ? "ms" : undefined}
          status={p95Status}
          hint={`${LATENCY_BUDGET_MS} ms per-turn budget`}
        />
        <StatTile label="Turns" value={transcript.length} footer="conversation exchanges" />
        <StatTile label="Latency samples" value={metrics.length} footer="metered turns" />
      </TileRow>

      {call.summary ? (
        <Notice tone="info" title="Summary">
          {call.summary}
        </Notice>
      ) : null}

      <Card title="Disposition" className="stackCard">
        <CallDisposition callId={call.id} current={call.outcome ?? null} />
      </Card>

      <Card title="Transcript" className="stackCard">
        {transcript.length === 0 ? (
          <EmptyState title="No transcript captured">
            This call has no recorded transcript — it may have ended before the
            agent spoke.
          </EmptyState>
        ) : (
          <TranscriptList>
            {transcript.map((t, i) => (
              <TranscriptTurn key={i} role={t.role} meta={t.ts ? String(t.ts).slice(0, 19) : undefined}>
                {t.text}
              </TranscriptTurn>
            ))}
          </TranscriptList>
        )}
      </Card>

      <Card title="Per-turn latency" className="stackCard">
        <DataTable
          columns={metricColumns}
          rows={metrics}
          getRowKey={(m) => m.speech_id}
          empty={
            <EmptyState icon={ListTree} title="No latency samples">
              Per-turn answer-speed metrics appear here once the call is metered.
            </EmptyState>
          }
        />
      </Card>
    </>
  );
}
