import { SlidersHorizontal, Lightbulb } from "lucide-react";
import { getTuningSuggestions, type TuningSuggestion } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import TileRow from "@/components/TileRow";
import PulseTile, { pulseStatus } from "@/components/PulseTile";
import StatTile from "@/components/StatTile";
import Card from "@/components/Card";
import DataTable, { type Column } from "@/components/DataTable";
import Pill from "@/components/Pill";
import Notice from "@/components/Notice";
import EmptyState from "@/components/EmptyState";

export const dynamic = "force-dynamic";

const AGREEMENT_TARGET = 0.8;

type MatrixRow = { decision: string; accepted: number; rejected: number };

const matrixColumns: Column<MatrixRow>[] = [
  { key: "decision", header: "Engine decision", render: (r) => <Pill tone="info">{r.decision}</Pill> },
  { key: "accepted", header: "Attorney accepted", align: "right" },
  { key: "rejected", header: "Attorney rejected", align: "right" },
];

export default async function Tuning() {
  const report = await getTuningSuggestions(90);
  const matrixRows: MatrixRow[] = Object.keys(report.matrix).map((decision) => ({
    decision,
    accepted: report.matrix[decision].accepted ?? 0,
    rejected: report.matrix[decision].rejected ?? 0,
  }));
  const agreement = report.agreement_rate;
  const agreementStatus =
    agreement == null ? null : pulseStatus(agreement, AGREEMENT_TARGET, { higherIsBetter: true, warnRatio: 0.75 });

  return (
    <>
      <PageHeader
        title="Qualification tuning"
        subtitle="How often the engine's qualification call matches an attorney's verdict — and where to tighten the rules."
      />

      <TileRow>
        <PulseTile
          label="Engine / attorney agreement"
          value={agreement != null ? `${Math.round(agreement * 100)}%` : "—"}
          status={agreementStatus}
          hint={`${Math.round(AGREEMENT_TARGET * 100)}% target · ${report.reviews} reviews · last ${report.days}d`}
        />
        <StatTile label="Reviews" value={report.reviews} footer={`last ${report.days} days`} />
        <StatTile label="Open suggestions" value={report.suggestions.length} footer="advisory rule changes" />
      </TileRow>

      <Card title="Engine decision vs attorney verdict" className="stackCard">
        <DataTable
          columns={matrixColumns}
          rows={matrixRows}
          getRowKey={(r) => r.decision}
          empty={
            <EmptyState icon={SlidersHorizontal} title="No reviews yet">
              Attorneys record accept/reject verdicts on leads via the API
              (POST /v1/leads/&#123;id&#125;/review) — the tuning loop starts once
              a few land.
            </EmptyState>
          }
        />
      </Card>

      <Card title="Suggestions" className="stackCard">
        {report.suggestions.length === 0 ? (
          <EmptyState icon={Lightbulb} title="Nothing to suggest">
            Either the rules already match attorney behavior, or there aren't
            enough verdicts yet (5+ per pattern required).
          </EmptyState>
        ) : (
          <div>
            {report.suggestions.map((s: TuningSuggestion) => (
              <Notice key={s.kind + s.detail} tone="warn" title={s.kind.replaceAll("_", " ")}>
                {s.detail}
              </Notice>
            ))}
          </div>
        )}
      </Card>

      {report.proposed_rules && (
        <Card title="Proposed qualification rules" className="stackCard">
          <Notice tone="info" icon={false}>
            Review with an attorney, then apply from the Config Studio (or PUT
            /v1/agents/&#123;id&#125;/config).
            <pre>{JSON.stringify(report.proposed_rules, null, 2)}</pre>
          </Notice>
        </Card>
      )}
    </>
  );
}
