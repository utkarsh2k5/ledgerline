import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, api, download, openHtml, post } from "../api";
import { useAuth } from "../auth";
import { FactValue } from "../components/Trace";
import { Loading, Page, Panel, Status, useAsync } from "../components/ui";
import { dateTime, monthLabel } from "../format";
import { useScheme } from "../scheme";

type Spec = { name: string; title: string; description: string; audience: string; formats: string[]; sections: string[]; yaml: string };
type Run = {
  id: number; spec: string; period_end: string; status: string; fingerprint: string | null; commentary_status: string | null;
  commentary_provider: string | null; commentary_issues: any[]; commentary_text: string | null; formats: string[];
  gate_overridden: boolean; error: string | null; created_by: string; created_at: string;
};

export default function Reports() {
  const { scheme, periodEnd, version } = useScheme();
  const { can, user } = useAuth();
  const specs = useAsync<Spec[]>(() => api("/report-specs"), []);
  const runs = useAsync<Run[]>(() => api(`/reports?scheme_id=${scheme!.id}`), [scheme?.id, version]);
  const [spec, setSpec] = useState("quarterly_trustee_report");
  const [override, setOverride] = useState(false);
  const [blocked, setBlocked] = useState<any[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [compare, setCompare] = useState<number[]>([]);
  const [showYaml, setShowYaml] = useState(false);

  const pending = runs.data?.some((r) => r.status === "queued" || r.status === "running");
  useEffect(() => {
    if (!pending) return;
    const t = setInterval(runs.reload, 1500);
    return () => clearInterval(t);
  }, [pending]); // eslint-disable-line react-hooks/exhaustive-deps

  const generate = async () => {
    setError(null);
    setBlocked(null);
    try {
      const r = await post<Run>(`/schemes/${scheme!.id}/reports`, { spec, period_end: periodEnd, override_gate: override });
      setSelected(r.id);
      runs.reload();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setBlocked((e.detail as any)?.breaks ?? []);
      else setError((e as Error).message);
    }
  };

  const current = runs.data?.find((r) => r.id === selected) ?? runs.data?.find((r) => r.status === "done");
  const chosen = specs.data?.find((s) => s.name === spec);

  return (
    <Page
      title="Reports"
      intro="Each report layout is a YAML spec. The same numbers render to Word, PowerPoint and an interactive web page, and every figure keeps a record of where it came from."
    >
      <div className="grid-2 reports-top">
        <Panel title={`Generate for ${periodEnd ? monthLabel(periodEnd) : "…"}`}>
          {!specs.data ? <Loading error={specs.error} /> : (
            <div className="spec-list" role="radiogroup" aria-label="Report layout">
              {specs.data.map((s) => (
                <label key={s.name} className={`spec ${spec === s.name ? "on" : ""}`}>
                  <input type="radio" checked={spec === s.name} onChange={() => setSpec(s.name)} />
                  <span>
                    <strong>{s.title}</strong>
                    <span className="muted">{s.description}</span>
                  </span>
                </label>
              ))}
            </div>
          )}
          {user?.role === "admin" && (
            <label className="check">
              <input type="checkbox" checked={override} onChange={(e) => setOverride(e.target.checked)} />
              Release even if material differences are unresolved (the report will carry a warning)
            </label>
          )}
          <div className="row">
            <button className="btn primary" onClick={generate} disabled={!can("analyst")}>Generate report</button>
            {chosen && <button className="link-btn" onClick={() => setShowYaml((v) => !v)}>{showYaml ? "Hide" : "View"} spec</button>}
          </div>
          {!can("analyst") && <p className="muted small">Read-only accounts can download reports but not create them.</p>}
          {error && <p className="error">{error}</p>}
          {blocked && (
            <div className="callout callout-bad">
              <strong>Blocked: {blocked.length} unresolved material difference{blocked.length === 1 ? "" : "s"}.</strong>
              <ul>{blocked.map((b) => <li key={b.id}>{b.fund_name}, {monthLabel(b.month)}</li>)}</ul>
              <Link to="/reconciliation" className="btn small">Resolve them</Link>
            </div>
          )}
          {showYaml && chosen && <pre className="yaml">{chosen.yaml}</pre>}
        </Panel>
        {current ? <RunDetail run={current} onChanged={runs.reload} /> : <Panel title="Latest report"><p className="empty">No reports yet. Generate one to see it here.</p></Panel>}
      </div>

      <Panel title="History" actions={compare.length === 2 && <CompareButton ids={compare} />}>
        {!runs.data ? <Loading error={runs.error} /> : runs.data.length === 0 ? <p className="empty">No reports generated yet.</p> : (
          <div className="table-wrap">
            <table className="data">
              <thead><tr><th aria-label="Compare" /><th>#</th><th>Layout</th><th>Period</th><th>Status</th><th>Commentary</th><th>Fingerprint</th><th>Created</th><th /></tr></thead>
              <tbody>
                {runs.data.map((r) => (
                  <tr key={r.id} className={current?.id === r.id ? "selected" : ""}>
                    <td>
                      <input type="checkbox" aria-label={`Compare report ${r.id}`} disabled={r.status !== "done"}
                        checked={compare.includes(r.id)}
                        onChange={(e) => setCompare((c) => (e.target.checked ? [...c, r.id].slice(-2) : c.filter((x) => x !== r.id)))} />
                    </td>
                    <td>{r.id}</td>
                    <td>{specs.data?.find((s) => s.name === r.spec)?.title ?? r.spec}</td>
                    <td>{monthLabel(r.period_end)}</td>
                    <td><RunStatus r={r} /></td>
                    <td>{r.commentary_status && <CommentaryBadge r={r} />}</td>
                    <td className="code">{r.fingerprint?.slice(0, 10) ?? "–"}</td>
                    <td className="muted">{dateTime(r.created_at)}</td>
                    <td><button className="link-btn" onClick={() => setSelected(r.id)}>Open</button></td>
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

function RunStatus({ r }: { r: Run }) {
  if (r.status === "done") return r.gate_overridden ? <Status kind="warn">Released with warning</Status> : <Status kind="good">Ready</Status>;
  if (r.status === "failed" || r.status === "blocked") return <Status kind="bad">{r.status === "blocked" ? "Blocked" : "Failed"}</Status>;
  return <Status kind="info">{r.status === "queued" ? "Queued" : "Generating…"}</Status>;
}

function CommentaryBadge({ r }: { r: Run }) {
  if (r.commentary_status === "verified")
    return <Status kind="good">{r.commentary_provider === "template" ? "Rule-based" : "AI, verified"}</Status>;
  const busy = r.commentary_issues.length > 0 && r.commentary_issues.every((i) => i.kind === "provider_error");
  return busy
    ? <Status kind="info">AI busy, standard text used</Status>
    : <Status kind="warn">AI draft rejected, standard text used</Status>;
}

function RunDetail({ run, onChanged }: { run: Run; onChanged: () => void }) {
  const [repro, setRepro] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const { can } = useAuth();
  const { scheme } = useScheme();
  const base = `${scheme?.code ?? "report"}_${run.spec}_${run.period_end.slice(0, 7)}`;

  const reproduce = async () => {
    setBusy(true);
    try {
      setRepro(await post(`/reports/${run.id}/reproduce`));
      onChanged();
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel title={`Report #${run.id}`} actions={<RunStatus r={run} />}>
      {run.status !== "done" ? (
        run.error ? <p className="error">{run.error}</p> : <p className="muted">Generating Word, PowerPoint and web versions…</p>
      ) : (
        <>
          <div className="row wrap">
            {run.formats.includes("docx") && <button className="btn" onClick={() => download(`/reports/${run.id}/download/docx`, `${base}.docx`)}>Download Word</button>}
            {run.formats.includes("pptx") && <button className="btn" onClick={() => download(`/reports/${run.id}/download/pptx`, `${base}.pptx`)}>Download PowerPoint</button>}
            {run.formats.includes("html") && <button className="btn" onClick={() => openHtml(`/reports/${run.id}/download/html`)}>Open interactive version</button>}
          </div>
          {run.commentary_text && (
            <div className="commentary-box">
              <h3>Commentary</h3>
              <p>{run.commentary_text}</p>
              <CommentaryBadge r={run} />
              {run.commentary_issues.length > 0 && (
                <details>
                  <summary>Fact-checker log ({run.commentary_issues.length})</summary>
                  <ul className="issues">
                    {run.commentary_issues.map((i, n) => (
                      <li key={n}><strong>{i.attempt ? `Draft ${i.attempt}: ` : ""}</strong>{i.message}{i.resolved_on_retry ? " (fixed on retry)" : ""}</li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
          )}
          <FactSearch reportId={run.id} />
          {can("analyst") && (
            <div className="repro">
              <button className="btn" onClick={reproduce} disabled={busy}>{busy ? "Rebuilding…" : "Re-run from today's data and compare"}</button>
              {repro && (repro.blocked ? <p className="error">{repro.blocked}</p> : repro.identical ? (
                <p><Status kind="good">Identical</Status> Rebuilt from current data, the content fingerprint matches exactly.</p>
              ) : (
                <div>
                  <p><Status kind="warn">Changed</Status> {repro.n_changed_facts} figure(s) differ from the published report{repro.commentary_still_valid === false ? ", and the published commentary no longer matches the numbers" : ""}.</p>
                  <ChangeTable changes={repro.changed_facts.slice(0, 12)} />
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </Panel>
  );
}

function FactSearch({ reportId }: { reportId: number }) {
  const [q, setQ] = useState("perf.TOTAL");
  const { data } = useAsync<any[]>(() => api(`/reports/${reportId}/facts?q=${encodeURIComponent(q)}&limit=12`), [reportId, q]);
  return (
    <div className="fact-search">
      <h3>Trace any figure in this report</h3>
      <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search figures, e.g. funding, GEQ, attr.1y" aria-label="Search figures" />
      <ul>
        {data?.map((f) => (
          <li key={f.fact_id}>
            <span>{f.label}</span>
            <FactValue id={f.fact_id} reportId={reportId}>{f.display}</FactValue>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ChangeTable({ changes }: { changes: any[] }) {
  return (
    <table className="data compact">
      <thead><tr><th>Figure</th><th className="num">Before</th><th className="num">After</th></tr></thead>
      <tbody>
        {changes.map((c) => (
          <tr key={c.fact_id}><td className="code">{c.label ?? c.fact_id}</td><td className="num">{c.before?.toFixed(6) ?? "–"}</td><td className="num">{c.after?.toFixed(6) ?? "–"}</td></tr>
        ))}
      </tbody>
    </table>
  );
}

function CompareButton({ ids }: { ids: number[] }) {
  const [res, setRes] = useState<any>(null);
  return (
    <div className="compare-wrap">
      <button className="btn small" onClick={async () => setRes(await api(`/reports/compare?a=${ids[0]}&b=${ids[1]}`))}>Compare #{ids[0]} and #{ids[1]}</button>
      {res && (
        <div className="compare-pop">
          <button className="icon-btn" onClick={() => setRes(null)} aria-label="Close">×</button>
          {res.changes.length === 0 ? <p>Same numbers in both reports.</p> : (
            <>
              <p>{res.changes.length} figure(s) differ between report #{res.a} and #{res.b}.</p>
              <ChangeTable changes={res.changes.slice(0, 15)} />
            </>
          )}
        </div>
      )}
    </div>
  );
}
