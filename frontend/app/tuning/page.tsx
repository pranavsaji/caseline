import { getTuningSuggestions } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function Tuning() {
  const report = await getTuningSuggestions(90);
  const decisions = Object.keys(report.matrix);

  return (
    <main>
      <h1>Qualification Tuning</h1>
      <p>
        Attorney verdicts on {report.reviews} reviewed lead
        {report.reviews === 1 ? "" : "s"} (last {report.days} days)
        {report.agreement_rate != null && (
          <>
            {" "}
            — engine/attorney agreement{" "}
            <span className={`pill ${report.agreement_rate >= 0.8 ? "ok" : "warn"}`}>
              {Math.round(report.agreement_rate * 100)}%
            </span>
          </>
        )}
        . Suggestions are advisory: apply the proposed rules from the Config
        Studio when an attorney signs off.
      </p>

      <h2>Engine decision vs attorney verdict</h2>
      {decisions.length === 0 ? (
        <div className="empty">
          No reviews yet. Attorneys record accept/reject verdicts on leads via
          the API (<code>POST /v1/leads/&#123;id&#125;/review</code>).
        </div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Engine decision</th>
              <th>Attorney accepted</th>
              <th>Attorney rejected</th>
            </tr>
          </thead>
          <tbody>
            {decisions.map((d) => (
              <tr key={d}>
                <td>
                  <span className="pill">{d}</span>
                </td>
                <td>{report.matrix[d].accepted ?? 0}</td>
                <td>{report.matrix[d].rejected ?? 0}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h2>Suggestions</h2>
      {report.suggestions.length === 0 ? (
        <div className="empty">
          Nothing to suggest — either the rules match attorney behavior or
          there are not enough verdicts yet (5+ per pattern required).
        </div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Change</th>
              <th>Why</th>
            </tr>
          </thead>
          <tbody>
            {report.suggestions.map((s) => (
              <tr key={s.kind + s.detail}>
                <td>
                  <span className="pill warn">{s.kind.replaceAll("_", " ")}</span>
                </td>
                <td>{s.detail}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {report.proposed_rules && (
        <>
          <h2>Proposed qualification rules</h2>
          <p>
            Review with an attorney, then apply via the Config Studio (or{" "}
            <code>PUT /v1/agents/&#123;id&#125;/config</code>).
          </p>
          <pre>{JSON.stringify(report.proposed_rules, null, 2)}</pre>
        </>
      )}
    </main>
  );
}
