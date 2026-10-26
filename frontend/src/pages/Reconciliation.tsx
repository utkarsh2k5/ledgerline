import { useState } from "react";
import { api, post } from "../api";
import { useAuth } from "../auth";
import { Loading, Page, Panel, Segmented, Status, useAsync } from "../components/ui";
import { dateTime, monthLabel, pct } from "../format";
import { useScheme } from "../scheme";

type Break = {
  id: number; fund_code: string; fund_name: string; month: string; break_type: string; severity: string; status: string;
  custodian_value: number | null; manager_value: number | null; diff_bps: number | null; resolution: string | null;
  resolved_value: number | null; reason: string | null; resolved_by: string | null; resolved_at: string | null;
};

const TYPE_TEXT: Record<string, string> = {
  value_mismatch: "Returns disagree",
  missing_manager: "Manager figure missing",
  missing_custodian: "Custodian figure missing",
};

export default function Reconciliation() {
  const { scheme, version, refresh } = useScheme();
  const { can } = useAuth();
  const [filter, setFilter] = useState<"open" | "resolved" | "all">("open");
  const breaks = useAsync<Break[]>(() => api(`/schemes/${scheme!.id}/recon/breaks?status=${filter}`), [scheme?.id, filter, version]);
  const runs = useAsync<any[]>(() => api(`/schemes/${scheme!.id}/recon/runs`), [scheme?.id, version]);
  const [running, setRunning] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const rerun = async () => {
    setRunning(true);
    try {
      const r = await post(`/schemes/${scheme!.id}/recon/run`);
      setMessage(`Compared ${r.compared} fund-months: ${r.matched} matched, ${r.open_material} material and ${r.open_minor} minor differences open.`);
      refresh();
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setRunning(false);
    }
  };

  const last = runs.data?.[0];
  return (
    <Page
      title="Reconciliation"
      intro="Every month, the custodian's valuations (which we turn into returns) are checked against what each fund manager reports. Differences above tolerance need a decision before they can go into a client report."
      actions={can("analyst") && <button className="btn" onClick={rerun} disabled={running}>{running ? "Running…" : "Run reconciliation"}</button>}
    >
      {message && <div className="callout callout-info">{message}</div>}
      {last && (
        <div className="recon-summary">
          <div><span className="big">{last.compared}</span> fund-months compared</div>
          <div><span className="big">{last.matched}</span> matched within {last.tolerance_bps} bps</div>
          <div><span className="big">{last.breaks}</span> differences (material above {last.material_bps} bps)</div>
          <div className="muted small">Last run {dateTime(last.run_at)} by {last.run_by}</div>
        </div>
      )}
      <Panel
        title="Differences"
        actions={<Segmented label="Show" value={filter} onChange={setFilter} options={[{ value: "open", label: "Open" }, { value: "resolved", label: "Resolved" }, { value: "all", label: "All, incl. superseded" }]} />}
      >
        {!breaks.data ? <Loading error={breaks.error} /> : breaks.data.length === 0 ? (
          <p className="empty">{filter === "open" ? "Nothing to resolve. Reports for every period can be generated." : "No differences here."}</p>
        ) : (
          <div className="break-list">
            {breaks.data.map((b) => <BreakCard key={b.id} b={b} canResolve={can("analyst")} onDone={refresh} />)}
          </div>
        )}
      </Panel>
    </Page>
  );
}

function BreakCard({ b, canResolve, onDone }: { b: Break; canResolve: boolean; onDone: () => void }) {
  const [choice, setChoice] = useState<"custodian" | "manager" | "override">(b.custodian_value !== null ? "custodian" : "manager");
  const [reason, setReason] = useState("");
  const [override, setOverride] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const resolve = async () => {
    setBusy(true);
    setError(null);
    try {
      await post(`/recon/breaks/${b.id}/resolve`, {
        resolution: choice,
        reason,
        override_value: choice === "override" ? Number(override) / 100 : undefined,
      });
      onDone();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <article className={`break ${b.status} sev-${b.severity}`}>
      <div className="break-head">
        <div>
          <h3>{b.fund_name} · {monthLabel(b.month)}</h3>
          <p className="muted">{TYPE_TEXT[b.break_type]}</p>
        </div>
        {b.status === "open" ? (
          <Status kind={b.severity === "material" ? "bad" : "warn"}>{b.severity === "material" ? "Blocks reports" : "Minor"}</Status>
        ) : b.status === "resolved" ? (
          <Status kind="good">Resolved</Status>
        ) : (
          <Status kind="info">Superseded by newer data</Status>
        )}
      </div>
      <div className="compare">
        <div><span>Custodian</span><strong>{pct(b.custodian_value)}</strong></div>
        <div><span>Manager</span><strong>{pct(b.manager_value)}</strong></div>
        <div><span>Difference</span><strong>{b.diff_bps === null ? "–" : `${b.diff_bps.toFixed(1)} bps`}</strong></div>
      </div>
      {b.status === "resolved" && (
        <p className="resolution">
          Used the <strong>{b.resolution}</strong> figure ({pct(b.resolved_value)}). “{b.reason}” {b.resolved_by} · {b.resolved_at && dateTime(b.resolved_at)}
        </p>
      )}
      {b.status === "open" && canResolve && (
        <div className="resolve">
          <div className="resolve-choices" role="radiogroup" aria-label="Which figure is right?">
            {b.custodian_value !== null && <label><input type="radio" checked={choice === "custodian"} onChange={() => setChoice("custodian")} /> Custodian is right</label>}
            {b.manager_value !== null && <label><input type="radio" checked={choice === "manager"} onChange={() => setChoice("manager")} /> Manager is right</label>}
            <label><input type="radio" checked={choice === "override"} onChange={() => setChoice("override")} /> Enter corrected figure</label>
            {choice === "override" && (
              <input className="pct-input" inputMode="decimal" placeholder="e.g. 1.23" value={override} onChange={(e) => setOverride(e.target.value)} aria-label="Corrected return in percent" />
            )}
          </div>
          <input className="reason" placeholder="Reason (kept in the audit trail and shown in the report)" value={reason} onChange={(e) => setReason(e.target.value)} />
          <button className="btn primary" onClick={resolve} disabled={busy || reason.trim().length < 5}>Resolve</button>
          {error && <p className="error">{error}</p>}
        </div>
      )}
    </article>
  );
}
