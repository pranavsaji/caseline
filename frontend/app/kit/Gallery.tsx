"use client";

import { useState } from "react";
import {
  Bot,
  Phone,
  PhoneMissed,
  Play,
  ShieldAlert,
} from "lucide-react";
import Card, { Well } from "@/components/Card";
import DataTable, { type Column } from "@/components/DataTable";
import EmptyState from "@/components/EmptyState";
import Notice from "@/components/Notice";
import PageHeader from "@/components/PageHeader";
import Pill from "@/components/Pill";
import PulseTile from "@/components/PulseTile";
import SoftButton from "@/components/SoftButton";
import StatTile from "@/components/StatTile";
import Toggle from "@/components/Toggle";
import TranscriptTurn, { TranscriptList } from "@/components/TranscriptTurn";
import SoftInput from "@/components/inputs/SoftInput";
import SoftSelect from "@/components/inputs/SoftSelect";
import SoftTextarea from "@/components/inputs/SoftTextarea";
import styles from "@/components/kit.module.css";

type Row = { id: string; outcome: string; p95: number; synced: boolean };

const ROWS: Row[] = [
  { id: "call_a1", outcome: "booked", p95: 612, synced: true },
  { id: "call_b2", outcome: "qualified", p95: 744, synced: true },
  { id: "call_c3", outcome: "transferred", p95: 910, synced: false },
];

const COLUMNS: Column<Row>[] = [
  { key: "id", header: "Call", render: (r) => <code>{r.id}</code> },
  { key: "outcome", header: "Outcome", render: (r) => <Pill tone="info">{r.outcome}</Pill> },
  {
    key: "p95",
    header: "Answer speed",
    align: "right",
    render: (r) => (
      <Pill tone={r.p95 <= 650 ? "ok" : r.p95 <= 800 ? "warn" : "bad"}>{r.p95} ms</Pill>
    ),
  },
  {
    key: "synced",
    header: "CMS",
    render: (r) => (r.synced ? <Pill tone="ok" dot>synced</Pill> : <Pill tone="muted">pending</Pill>),
  },
];

/**
 * Dev-only component gallery (uiplan.md §Phase 1). Exercises every kit
 * component with realistic props. Rendered twice by app/kit/page.tsx — once
 * per theme — so we can eyeball light and dark side by side.
 */
export default function Gallery() {
  const [disclosed, setDisclosed] = useState(true);
  const [json, setJson] = useState('{ "sol_days": 730 }');
  const jsonValid = (() => {
    try {
      JSON.parse(json);
      return true;
    } catch {
      return false;
    }
  })();

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 22 }}>
      <PageHeader
        title="Intake overview"
        subtitle="Every Phase 1 component, one realistic screen."
        actions={<SoftButton variant="primary">New agent</SoftButton>}
      />

      <div className={styles.tileRow}>
        <PulseTile label="Answer speed (p95)" value={612} unit="ms" budget={800} hint="800 ms budget" />
        <PulseTile label="Speed to lead (p95)" value={78} unit="s" budget={60} hint="60 s SLO" />
        <PulseTile
          label="Contact rate"
          value={94}
          unit="%"
          budget={90}
          higherIsBetter
          hint="≥ 90% target"
        />
        <StatTile label="Booked today" value={12} footer="+3 vs yesterday" />
        <StatTile label="Qualification rate" value={68} unit="%" footer="last 30 days" />
      </div>

      <Card title="Recent calls" actions={<SoftButton size="sm">Export</SoftButton>}>
        <DataTable
          columns={COLUMNS}
          rows={ROWS}
          getRowKey={(r) => r.id}
          empty={<EmptyState title="No calls yet">Once your number is live, calls land here within seconds.</EmptyState>}
        />
      </Card>

      <Card title="Pills & buttons">
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 16 }}>
          <Pill tone="ok" dot>within SLO</Pill>
          <Pill tone="warn">near budget</Pill>
          <Pill tone="bad">over budget</Pill>
          <Pill tone="info">neutral</Pill>
          <Pill tone="muted">pending</Pill>
        </div>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
          <SoftButton variant="primary">
            <Play size={15} aria-hidden /> Run preview
          </SoftButton>
          <SoftButton>Secondary</SoftButton>
          <SoftButton variant="danger">Opt out</SoftButton>
          <SoftButton disabled>Disabled</SoftButton>
          <SoftButton size="sm">Small</SoftButton>
        </div>
      </Card>

      <Card title="Form controls">
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 16 }}>
          <SoftInput label="Firm name" placeholder="Acme Injury Law" defaultValue="Acme Injury Law" />
          <SoftInput label="Transfer number" placeholder="+1…" error="Not a valid E.164 number" defaultValue="555" />
          <SoftSelect label="After hours" defaultValue="voicemail">
            <option value="voicemail">Take a voicemail</option>
            <option value="transfer">Transfer to on-call</option>
          </SoftSelect>
        </div>
        <div style={{ marginTop: 16 }}>
          <SoftTextarea
            label="Qualification rules (JSON)"
            value={json}
            onChange={(e) => setJson(e.target.value)}
            invalid={!jsonValid}
            error={jsonValid ? undefined : "Invalid JSON — check for a trailing comma."}
            rows={3}
          />
        </div>
        <div style={{ marginTop: 16 }}>
          <Toggle
            label="Recording disclosure spoken to every caller"
            checked={disclosed}
            onChange={(e) => setDisclosed(e.target.checked)}
          />
        </div>
      </Card>

      <Card title="Transcript">
        <TranscriptList>
          <TranscriptTurn role="agent" meta="0.6s answer" tag={<Pill tone="ok" dot>on brand</Pill>}>
            Thanks for calling Acme Injury Law — how can I help today?
          </TranscriptTurn>
          <TranscriptTurn role="caller" meta="00:04">
            I was in a car accident two weeks ago and broke my arm.
          </TranscriptTurn>
          <TranscriptTurn role="agent" meta="0.7s answer" tag={<Pill tone="bad">guardrail</Pill>}>
            I can’t give legal advice, but I can get you booked with an attorney today.
          </TranscriptTurn>
        </TranscriptList>
      </Card>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 16 }}>
        <div>
          <Notice tone="ok" title="Published">Your changes are live on the intake line.</Notice>
          <Notice tone="warn" title="Near budget">p95 answer speed is within 20% of the 800 ms ceiling.</Notice>
          <Notice tone="bad" title="Preview couldn’t run">Check the caller script isn’t empty and try again.</Notice>
          <Notice tone="info" title="State">
            <pre>{JSON.stringify({ step: "qualify", sol_ok: true }, null, 2)}</pre>
          </Notice>
        </div>
        <Card title="Nesting rule">
          <p style={{ color: "var(--muted)", fontSize: 13, marginTop: 0 }}>
            Raised card → inset well → raised control:
          </p>
          <Well>
            <div style={{ display: "flex", gap: 8, padding: 8 }}>
              <SoftButton size="sm">
                <Phone size={14} aria-hidden /> Call
              </SoftButton>
              <SoftButton size="sm">
                <Bot size={14} aria-hidden /> Agent
              </SoftButton>
            </div>
          </Well>
        </Card>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 16 }}>
        <EmptyState icon={PhoneMissed} title="No calls yet" action={<SoftButton size="sm">Open Studio</SoftButton>}>
          Once your number is live, every call shows up here within seconds.
        </EmptyState>
        <EmptyState icon={ShieldAlert} title="Benchmarks suppressed">
          We need at least 5 firms in your cohort before showing comparisons.
        </EmptyState>
      </div>
    </div>
  );
}
