import { Share2, Building2 } from "lucide-react";
import {
  listReferralPartners,
  listReferrals,
  type Referral,
  type ReferralPartner,
} from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import TileRow from "@/components/TileRow";
import StatTile from "@/components/StatTile";
import Card from "@/components/Card";
import DataTable, { type Column } from "@/components/DataTable";
import Pill, { type PillTone } from "@/components/Pill";
import EmptyState from "@/components/EmptyState";
import ReferralActions from "@/components/ReferralActions";
import PartnerForm from "@/components/PartnerForm";

export const dynamic = "force-dynamic";

function statusTone(status: string): PillTone {
  if (status === "accepted") return "ok";
  if (status === "declined") return "bad";
  if (status === "sent") return "warn";
  return "muted";
}

const referralColumns: Column<Referral>[] = [
  { key: "contact_name", header: "Client", render: (r) => r.contact_name ?? "—" },
  { key: "practice_area", header: "Practice area", render: (r) => r.practice_area ?? "—" },
  { key: "partner_name", header: "Partner" },
  {
    key: "match_reasons",
    header: "Match",
    render: (r) =>
      (r.match_reasons ?? []).length ? (
        <span style={{ display: "inline-flex", flexWrap: "wrap", gap: 6 }}>
          {r.match_reasons.map((reason, i) => (
            <Pill key={i} tone="info">
              {reason}
            </Pill>
          ))}
        </span>
      ) : (
        "—"
      ),
  },
  { key: "status", header: "Status", render: (r) => <Pill tone={statusTone(r.status)}>{r.status}</Pill> },
  { key: "created_at", header: "Proposed", render: (r) => r.created_at?.slice(0, 19) ?? "—" },
  {
    key: "actions",
    header: "Actions",
    align: "right",
    render: (r) => <ReferralActions referralId={r.id} status={r.status} />,
  },
];

const partnerColumns: Column<ReferralPartner>[] = [
  { key: "name", header: "Firm" },
  {
    key: "practice_areas",
    header: "Practice areas",
    render: (p) => (p.practice_areas.length ? p.practice_areas.join(", ") : "all"),
  },
  { key: "states", header: "States", render: (p) => (p.states.length ? p.states.join(", ") : "any") },
  { key: "contact", header: "Contact", render: (p) => p.contact_email ?? p.contact_phone ?? "—" },
  {
    key: "active",
    header: "Active",
    render: (p) => <Pill tone={p.active ? "ok" : "muted"}>{p.active ? "active" : "inactive"}</Pill>,
  },
];

export default async function Referrals() {
  const [referrals, partners] = await Promise.all([listReferrals(), listReferralPartners()]);
  const sent = referrals.filter((r) => r.status !== "proposed").length;

  return (
    <>
      <PageHeader
        title="Smart referrals"
        subtitle="Declined-but-viable leads matched to your partner network — nothing is shared until a person sends it with the client's consent."
      />

      <TileRow>
        <StatTile label="Referrals proposed" value={referrals.length} footer={`${sent} sent`} />
        <StatTile label="Partner firms" value={partners.length} footer={`${partners.filter((p) => p.active).length} active`} />
      </TileRow>

      <Card title="Referrals" className="stackCard">
        <DataTable
          columns={referralColumns}
          rows={referrals}
          getRowKey={(r) => r.id}
          empty={
            <EmptyState icon={Share2} title="No referrals proposed yet">
              {partners.length === 0
                ? "Register a partner firm to switch referrals on — no partners, no proposals."
                : "Refer-out leads will be matched to your partner network automatically."}
            </EmptyState>
          }
        />
      </Card>

      <Card title="Partner network" className="stackCard">
        <DataTable
          columns={partnerColumns}
          rows={partners}
          getRowKey={(p) => p.id}
          empty={
            <EmptyState icon={Building2} title="No partners yet">
              Register a partner firm below to start matching refer-out leads.
            </EmptyState>
          }
        />
      </Card>

      <Card title="Register a partner firm" className="stackCard">
        <PartnerForm />
      </Card>
    </>
  );
}
