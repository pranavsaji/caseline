import { listReferralPartners, listReferrals } from "@/lib/api";

export const dynamic = "force-dynamic";

function StatusPill({ status }: { status: string }) {
  const cls =
    status === "accepted" ? "ok" : status === "declined" ? "bad" : status === "sent" ? "warn" : "";
  return <span className={`pill ${cls}`}>{status}</span>;
}

export default async function Referrals() {
  const [referrals, partners] = await Promise.all([listReferrals(), listReferralPartners()]);

  return (
    <main>
      <h1>Smart Referrals</h1>
      <p>
        Declined-but-viable (refer-out) leads matched to your partner network.
        Proposals are automatic; nothing is shared until a person sends the
        referral with the client&apos;s consent recorded.
      </p>

      <h2>Referrals</h2>
      {referrals.length === 0 ? (
        <div className="empty">
          {partners.length === 0
            ? "Register a partner firm to switch referrals on — no partners, no proposals."
            : "No referrals proposed yet."}
        </div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Client</th>
              <th>Practice area</th>
              <th>Partner</th>
              <th>Match</th>
              <th>Status</th>
              <th>Proposed</th>
            </tr>
          </thead>
          <tbody>
            {referrals.map((r) => (
              <tr key={r.id}>
                <td>{r.contact_name ?? "—"}</td>
                <td>{r.practice_area ?? "—"}</td>
                <td>{r.partner_name}</td>
                <td>{(r.match_reasons ?? []).join("; ")}</td>
                <td>
                  <StatusPill status={r.status} />
                </td>
                <td>{r.created_at}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h2>Partner network</h2>
      {partners.length === 0 ? (
        <div className="empty">
          No partners yet. Add one via <code>POST /v1/referral-partners</code>.
        </div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Firm</th>
              <th>Practice areas</th>
              <th>States</th>
              <th>Contact</th>
              <th>Active</th>
            </tr>
          </thead>
          <tbody>
            {partners.map((p) => (
              <tr key={p.id}>
                <td>{p.name}</td>
                <td>{p.practice_areas.length ? p.practice_areas.join(", ") : "all"}</td>
                <td>{p.states.length ? p.states.join(", ") : "any"}</td>
                <td>{p.contact_email ?? p.contact_phone ?? "—"}</td>
                <td>
                  <span className={`pill ${p.active ? "ok" : "muted"}`}>
                    {p.active ? "active" : "inactive"}
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
