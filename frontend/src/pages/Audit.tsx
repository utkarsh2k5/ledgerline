import { api } from "../api";
import { Loading, Page, Panel, useAsync } from "../components/ui";
import { dateTime } from "../format";
import { useScheme } from "../scheme";

const ACTIONS: Record<string, string> = {
  "dataset.load": "Loaded a dataset",
  "recon.run": "Ran reconciliation",
  "recon.resolve": "Resolved a difference",
  "report.request": "Requested a report",
  "report.generate": "Generated a report",
  "report.reproduce": "Re-ran a report",
};

export default function Audit() {
  const { version } = useScheme();
  const { data, error } = useAsync<any[]>(() => api("/audit?limit=200"), [version]);
  return (
    <Page title="Audit trail" intro="Every load, decision and report, with who did it and when. Append-only.">
      <Panel>
        {!data ? <Loading error={error} /> : (
          <div className="table-wrap">
            <table className="data">
              <thead><tr><th>When</th><th>Who</th><th>What</th><th>Details</th></tr></thead>
              <tbody>
                {data.map((a) => (
                  <tr key={a.id}>
                    <td className="muted nowrap">{dateTime(a.at)}</td>
                    <td>{a.actor}</td>
                    <td>{ACTIONS[a.action] ?? a.action} <span className="muted">#{a.entity_id}</span></td>
                    <td className="details">
                      {Object.entries(a.details).map(([k, v]) => (
                        <span key={k}><em>{k.replace(/_/g, " ")}</em> {typeof v === "number" ? Number(v.toPrecision(6)) : String(v)}</span>
                      ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </Page>
  );
}
