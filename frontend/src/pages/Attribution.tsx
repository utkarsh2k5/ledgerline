import { useState } from "react";
import { Bar } from "react-chartjs-2";
import { api } from "../api";
import { pctTick } from "../components/charts";
import { FactValue } from "../components/Trace";
import { Loading, Page, Panel, Segmented, useAsync } from "../components/ui";
import { pct, signedPct, tone } from "../format";
import { useScheme } from "../scheme";
import { useChartColors, useTheme } from "../theme";

type Seg = { code: string; name: string; allocation: number; selection: number; interaction: number; total: number };
type Method = { segments: Seg[]; totals: Record<string, number>; explained: number; residual: number };
type Attr = {
  period: string; label: string; portfolio_return: number; benchmark_return: number; excess_return: number;
  methods: Record<"carino" | "grap" | "sum", Method>;
};

const EFFECTS = ["allocation", "selection", "interaction"] as const;
const METHOD_TEXT = {
  carino: "Carino: each month's effects are scaled by a log-based factor so they compound correctly.",
  grap: "GRAP: each month's effects are scaled by the fund's growth before and the benchmark's growth after.",
  sum: "Naive sum: monthly effects simply added up. Shown to make the point: it doesn't reconcile.",
};

export default function Attribution() {
  const { scheme, periodEnd, version } = useScheme();
  const [period, setPeriod] = useState("1y");
  const [method, setMethod] = useState<"carino" | "grap" | "sum">("carino");
  const c = useChartColors();
  const { theme } = useTheme();
  const { data, error } = useAsync<Attr>(
    () => api(`/schemes/${scheme!.id}/attribution?period=${period}&period_end=${periodEnd}`),
    [scheme?.id, periodEnd, period, version],
  );
  if (!data) return <Loading error={error} />;
  const m = data.methods[method];
  const linkedIds = method === "carino"; // stored facts use the scheme's chosen (Carino) linking

  return (
    <Page
      title="Attribution"
      intro="Why the fund beat or lagged its benchmark, split into allocation (how much we held of each asset class versus the strategy) and selection (how each manager did against its own benchmark)."
      actions={
        <Segmented label="Period" value={period} onChange={setPeriod} options={[{ value: "3m", label: "Quarter" }, { value: "1y", label: "1 year" }, { value: "3y", label: "3 years" }]} />
      }
    >
      <div className="equation" aria-label="Attribution reconciliation">
        <div><span>Fund</span><strong>{pct(data.portfolio_return)}</strong></div>
        <em>−</em>
        <div><span>Benchmark</span><strong>{pct(data.benchmark_return)}</strong></div>
        <em>=</em>
        <div className={tone(data.excess_return)}><span>Relative return</span><strong>{signedPct(data.excess_return)}</strong></div>
        <em>=</em>
        {EFFECTS.map((e, i) => (
          <div key={e} className="eq-term">
            {i > 0 && <em>+</em>}
            <div><span>{e[0].toUpperCase() + e.slice(1)}</span><strong className={tone(m.totals[e])}>{signedPct(m.totals[e])}</strong></div>
          </div>
        ))}
        <div className={`residual ${Math.abs(m.residual) > 1e-8 ? "bad" : "ok"}`}>
          <span>Unexplained</span>
          <strong>{Math.abs(m.residual) > 1e-8 ? `${(m.residual * 10000).toFixed(1)} bps` : "0.0 bps"}</strong>
        </div>
      </div>

      <Panel
        title="Linking months together"
        actions={<Segmented label="Linking method" value={method} onChange={setMethod} options={[{ value: "carino", label: "Carino" }, { value: "grap", label: "GRAP" }, { value: "sum", label: "Naive sum" }]} />}
        note={METHOD_TEXT[method]}
      >
        <div className="chart-box tall">
          <Bar key={theme}
            data={{
              labels: m.segments.map((s) => s.name),
              datasets: EFFECTS.map((e, i) => ({
                label: e[0].toUpperCase() + e.slice(1),
                data: m.segments.map((s) => s[e]),
                backgroundColor: c.series[i],
                borderRadius: 3,
                barPercentage: 0.75,
                categoryPercentage: 0.7,
              })),
            }}
            options={{
              indexAxis: "y",
              scales: { x: { ticks: { callback: pctTick(1) } }, y: { grid: { display: false } } },
              plugins: { legend: { position: "top", align: "start" }, tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${signedPct(c.raw as number)}` } } },
            }}
          />
        </div>
        <div className="table-wrap">
          <table className="data">
            <thead><tr><th>Mandate</th>{EFFECTS.map((e) => <th key={e} className="num">{e[0].toUpperCase() + e.slice(1)}</th>)}<th className="num">Total</th></tr></thead>
            <tbody>
              {m.segments.map((s) => (
                <tr key={s.code}>
                  <td>{s.name}</td>
                  {[...EFFECTS, "total" as const].map((e) => (
                    <td key={e} className={`num ${tone(s[e])}`}>
                      <FactValue id={linkedIds ? `attr.${period}.${s.code}.${e}` : null}>{signedPct(s[e])}</FactValue>
                    </td>
                  ))}
                </tr>
              ))}
              <tr className="total">
                <td>Total</td>
                {EFFECTS.map((e) => <td key={e} className={`num ${tone(m.totals[e])}`}><FactValue id={linkedIds ? `attr.${period}.TOTAL.${e}` : null}>{signedPct(m.totals[e])}</FactValue></td>)}
                <td className={`num ${tone(m.explained)}`}><FactValue id={linkedIds ? `attr.${period}.TOTAL.total` : null}>{signedPct(m.explained)}</FactValue></td>
              </tr>
            </tbody>
          </table>
        </div>
      </Panel>
    </Page>
  );
}
