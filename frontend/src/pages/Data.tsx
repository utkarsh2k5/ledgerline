import { useState, type FormEvent } from "react";
import { ApiError, api } from "../api";
import { useAuth } from "../auth";
import { Loading, Page, Panel, Status, useAsync } from "../components/ui";
import { dateTime } from "../format";
import { useScheme } from "../scheme";

type Adapter = { name: string; source: string; description: string };
type Issue = { severity: string; message: string; row_ref: string | null; column: string | null };

export default function Data() {
  const { scheme, version, refresh } = useScheme();
  const { can } = useAuth();
  const adapters = useAsync<Adapter[]>(() => api("/adapters"), []);
  const datasets = useAsync<any[]>(() => api(`/schemes/${scheme!.id}/datasets`), [scheme?.id, version]);
  const [adapter, setAdapter] = useState("custodian_csv");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [errors, setErrors] = useState<Issue[] | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const upload = async (e: FormEvent) => {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setResult(null);
    setErrors(null);
    setMessage(null);
    const fd = new FormData();
    fd.append("adapter", adapter);
    fd.append("file", file);
    try {
      const r = await api(`/schemes/${scheme!.id}/datasets`, { method: "POST", body: fd });
      setResult(r);
      refresh();
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        setErrors((err.detail as any)?.validation?.errors ?? []);
        setMessage((err.detail as any)?.message);
      } else setMessage((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Page
      title="Data"
      intro="Source files from the custodian, fund managers, index providers and the scheme actuary. Each upload is checked against a data contract, stored as a new version, and never overwrites history."
    >
      {can("analyst") && (
        <Panel title="Upload a file" note="Sample files are in data/sample/. Try examples_with_errors/custodian_with_errors.csv to see validation, or custodian_correction_PRP_2026-07.csv to watch a correction clear two differences.">
          <form className="upload" onSubmit={upload}>
            <label>
              File type
              <select value={adapter} onChange={(e) => setAdapter(e.target.value)}>
                {adapters.data?.map((a) => <option key={a.name} value={a.name}>{a.description}</option>)}
              </select>
            </label>
            <label>
              File
              <input type="file" accept=".csv,.xlsx,.xls" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            </label>
            <button className="btn primary" disabled={!file || busy}>{busy ? "Checking…" : "Upload and validate"}</button>
          </form>
          {message && <div className="callout callout-bad">{message}</div>}
          {errors && (
            <div className="table-wrap">
              <table className="data compact">
                <thead><tr><th>Where</th><th>Problem</th></tr></thead>
                <tbody>{errors.map((i, n) => <tr key={n}><td className="code">{i.row_ref ?? "file"}</td><td>{i.message}</td></tr>)}</tbody>
              </table>
            </div>
          )}
          {result && (
            <div className="callout callout-info">
              {result.duplicate
                ? <>This exact data is already loaded (dataset v{result.dataset_version_id}), so nothing changed.</>
                : <>Loaded {result.rows} rows as dataset v{result.dataset_version_id}.{" "}
                  {result.reconciliation && <>Reconciliation re-ran: {result.reconciliation.open_material} material and {result.reconciliation.open_minor} minor differences open.</>}</>}
              {result.validation.warnings.length > 0 && <> {result.validation.warnings.length} warning(s) recorded.</>}
            </div>
          )}
        </Panel>
      )}
      <Panel title="Dataset versions">
        {!datasets.data ? <Loading error={datasets.error} /> : (
          <div className="table-wrap">
            <table className="data">
              <thead><tr><th>Version</th><th>Source</th><th>File</th><th className="num">Rows</th><th>Content hash</th><th>Checks</th><th>Loaded</th></tr></thead>
              <tbody>
                {datasets.data.map((d) => (
                  <tr key={d.id}>
                    <td>v{d.id}</td>
                    <td>{d.source}</td>
                    <td>{d.filename}</td>
                    <td className="num">{d.rows}</td>
                    <td className="code">{d.hash}</td>
                    <td>{d.warnings.length ? <Status kind="warn">{d.warnings.length} warnings</Status> : <Status kind="good">Passed</Status>}</td>
                    <td className="muted">{dateTime(d.loaded_at)} · {d.loaded_by}</td>
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
