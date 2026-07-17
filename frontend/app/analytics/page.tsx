import { BarChart3, Gauge, Users2 } from "lucide-react";
import {
  getBenchmarks,
  getLatencyAnalytics,
  getOutcomeAnalytics,
  type BenchmarkMetric,
  type LatencyAnalytics,
} from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import TileRow from "@/components/TileRow";
import StatTile from "@/components/StatTile";
import PulseTile, { pulseStatus } from "@/components/PulseTile";
import Card from "@/components/Card";
import DataTable, { type Column } from "@/components/DataTable";
import Pill from "@/components/Pill";
import Notice from "@/components/Notice";
import EmptyState from "@/components/EmptyState";

export const dynamic = "force-dynamic";

function pct(rate: number | null): string {
  return rate == null ? "—" : `${Math.round(rate * 100)}%`;
}

function SloPill({ p95, slo }: { p95: number | null; slo: number }) {
  if (p95 == null) return <Pill tone="muted">no data</Pill>;
  const status = pulseStatus(p95, slo, { warnRatio: 650 / slo });
  return <Pill tone={status ?? "muted"}>{Math.round(p95)} ms</Pill>;
}

type OutcomeRow = { outcome: string; n: number };
type DayRow = LatencyAnalytics["by_day"][number];
type ProviderRow = LatencyAnalytics["by_provider"][number];
type BenchRow = { key: string; metric: BenchmarkMetric };

export default async function Analytics() {
  const [outcomes, latency, benchmarks] = await Promise.all([
    getOutcomeAnalytics(30),
    getLatencyAnalytics(7),
    getBenchmarks(30),
  ]);

  const worstP95 = latency.by_day.length
    ? Math.round(Math.max(...latency.by_day.map((d) => d.p95_ms)))
    : null;

  const outcomeColumns: Column<OutcomeRow>[] = [
    { key: "outcome", header: "Outcome", render: (o) => <Pill tone="info">{o.outcome}</Pill> },
    { key: "n", header: "Calls", align: "right" },
  ];

  const dayColumns: Column<DayRow>[] = [
    { key: "day", header: "Day" },
    { key: "turns", header: "Turns", align: "right" },
    { key: "p50_ms", header: "p50", align: "right", render: (d) => `${Math.round(d.p50_ms)} ms` },
    {
      key: "p95_ms",
      header: "p95",
      align: "right",
      render: (d) => <SloPill p95={d.p95_ms} slo={latency.slo_ms} />,
    },
  ];

  const providerColumns: Column<ProviderRow>[] = [
    { key: "llm_provider", header: "LLM" },
    { key: "tts_provider", header: "TTS" },
    { key: "turns", header: "Turns", align: "right" },
    {
      key: "llm_ttft_p95_ms",
      header: "LLM TTFT p95",
      align: "right",
      render: (p) => `${Math.round(p.llm_ttft_p95_ms)} ms`,
    },
    {
      key: "tts_ttfb_p95_ms",
      header: "TTS TTFB p95",
      align: "right",
      render: (p) => `${Math.round(p.tts_ttfb_p95_ms)} ms`,
    },
    {
      key: "total_p95_ms",
      header: "Total p95",
      align: "right",
      render: (p) => <SloPill p95={p.total_p95_ms} slo={latency.slo_ms} />,
    },
  ];

  const benchColumns: Column<BenchRow>[] = [
    { key: "label", header: "Metric", render: (r) => r.metric.label },
    { key: "own", header: "Your firm", align: "right", render: (r) => r.metric.own ?? "—" },
    { key: "p25", header: "Cohort p25", align: "right", render: (r) => r.metric.cohort?.p25 ?? "—" },
    { key: "p50", header: "Cohort median", align: "right", render: (r) => r.metric.cohort?.p50 ?? "—" },
    { key: "p75", header: "Cohort p75", align: "right", render: (r) => r.metric.cohort?.p75 ?? "—" },
    {
      key: "percentile",
      header: "Your percentile",
      align: "right",
      render: (r) =>
        r.metric.percentile_rank == null ? (
          <Pill tone="muted">no data</Pill>
        ) : (
          <Pill tone={r.metric.percentile_rank >= 0.5 ? "ok" : "warn"}>
            {Math.round(r.metric.percentile_rank * 100)}th
          </Pill>
        ),
    },
  ];

  const benchRows: BenchRow[] = Object.entries(benchmarks.metrics).map(([key, metric]) => ({
    key,
    metric,
  }));

  return (
    <>
      <PageHeader
        title="Analytics"
        subtitle={`Intake funnel, answer speed, and peer benchmarks — last ${outcomes.days} days.`}
      />

      <TileRow>
        <PulseTile
          label="Answer speed (p95)"
          value={worstP95 ?? "—"}
          unit={worstP95 != null ? "ms" : undefined}
          status={worstP95 == null ? null : pulseStatus(worstP95, latency.slo_ms, { warnRatio: 650 / latency.slo_ms })}
          hint={`${latency.slo_ms} ms SLO · worst of last ${latency.days}d`}
        />
        <StatTile label="Calls" value={outcomes.calls} footer={`last ${outcomes.days} days`} />
        <StatTile label="Qualification rate" value={pct(outcomes.qualification_rate)} footer={`${outcomes.leads} leads`} />
        <StatTile label="Booking rate" value={pct(outcomes.booking_rate)} footer={`${outcomes.consults_booked} booked`} />
      </TileRow>

      <Card title="Call outcomes" className="stackCard">
        <DataTable
          columns={outcomeColumns}
          rows={outcomes.outcomes}
          getRowKey={(o) => o.outcome}
          empty={<EmptyState icon={BarChart3} title="No calls yet">Outcomes break down here as calls come in.</EmptyState>}
        />
      </Card>

      <Card
        title="Turn latency by day"
        actions={<Pill tone="muted">SLO {latency.slo_ms} ms p95</Pill>}
        className="stackCard"
      >
        <DataTable
          columns={dayColumns}
          rows={latency.by_day}
          getRowKey={(d) => d.day}
          empty={<EmptyState icon={Gauge} title="No turn metrics yet">Answer-speed trends appear once calls are metered.</EmptyState>}
        />
      </Card>

      <Card title="Latency by provider" className="stackCard">
        <DataTable
          columns={providerColumns}
          rows={latency.by_provider}
          getRowKey={(p) => `${p.llm_provider}|${p.tts_provider}`}
          empty={<EmptyState icon={Gauge} title="No provider-tagged turns yet">Per-provider answer speed shows up here as turns are tagged.</EmptyState>}
        />
      </Card>

      <Card title="Peer benchmarks" className="stackCard">
        {benchmarks.suppressed ? (
          <Notice tone="info" title="Benchmarks locked">
            {benchmarks.suppressed_reason ??
              "Benchmarks unlock once enough peer firms are active — this keeps every firm's numbers anonymous."}
          </Notice>
        ) : (
          <DataTable
            columns={benchColumns}
            rows={benchRows}
            getRowKey={(r) => r.key}
            empty={<EmptyState icon={Users2} title="No benchmark metrics">Nothing to compare against your cohort yet.</EmptyState>}
          />
        )}
      </Card>
    </>
  );
}
