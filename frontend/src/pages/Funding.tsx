import { useState } from "react";
import { Chart as ChartJS } from "chart.js";
import { Line } from "react-chartjs-2";
import { api, post, type Fact } from "../api";
import { pctTick } from "../components/charts";
import { FactValue } from "../components/Trace";
import { Figure, Loading, Page, Panel, useAsync } from "../components/ui";
import { money, pct, tone } from "../format";
import { useScheme } from "../scheme";
import { useChartColors, useTheme } from "../theme";

type Stress = { scenario: string; rates_bps: number; equity: number; funding_ratio: number; change_in_funding_ratio: number; change_in_surplus: number };
type FundingData = {
  kpis: Fact[];
  stress: Stress[];
  simulation: { years: number[]; percentiles: Record<string, number[]>; prob_fully_funded_end: number; prob_below_80_end: number; median_end: number; n_paths: number } | null;
  curve: { years: number[]; zero_rates: number[]; par_tenors: number[]; par_yields: number[]; as_of: string };
};

export default function Funding() {
  const { scheme, periodEnd, version } = useScheme();
  const c = useChartColors();
  const { theme } = useTheme();
  const { data, error } = useAsync<FundingData>(() => api(`/schemes/${scheme!.id}/funding?period_end=${periodEnd}`), [scheme?.id, periodEnd, version]);
  if (!data || !scheme) return <Loading error={error} />;
  const k = Object.fromEntries(data.kpis.map((f) => [f.id, f]));
  const sim = data.simulation;

  return (
    <Page
      title="Funding"
      intro="Pensions promised are liabilities: their value today depends on interest rates. The funding ratio compares the scheme's assets with that value, and the hedge ratio says how much of the liabilities' interest-rate risk the assets offset."
    >
      <div className="figures">
        <Figure label="Funding ratio" fact={k["funding.ratio"]} />
        <Figure label="Assets" fact={k["funding.assets"]} />
        <Figure label="Liabilities" fact={k["funding.liabilities"]} sub="present value of promised pensions" />
        <Figure label="Surplus or deficit" fact={k["funding.surplus"]} />
        <Figure label="Interest-rate hedge" fact={k["funding.hedge_ratio"]} sub={<>liability duration <FactValue id="funding.liab_duration">{k["funding.liab_duration"]?.display}</FactValue></>} />
      </div>

      <div className="grid-2">
        <Panel title="Stress tests" note="Instant shocks. Liabilities are revalued on the shifted yield curve; bonds and LDI move with their duration; growth assets take the equity shock.">
          <table className="data">
            <thead><tr><th>Scenario</th><th className="num">Funding ratio after</th><th className="num">Change</th><th className="num">Surplus change</th></tr></thead>
            <tbody>
              {data.stress.map((s, i) => (
                <tr key={s.scenario}>
                  <td>{s.scenario}</td>
                  <td className="num"><FactValue id={`funding.stress.${i}.ratio`}>{pct(s.funding_ratio)}</FactValue></td>
                  <td className={`num ${tone(s.change_in_funding_ratio)}`}><FactValue id={`funding.stress.${i}.change`}>{(s.change_in_funding_ratio * 100).toFixed(1)} pts</FactValue></td>
                  <td className={`num ${tone(s.change_in_surplus)}`}>{money(s.change_in_surplus, scheme.currency)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <CustomStress />
        </Panel>

        {sim && (
          <Panel
            title="Where the funding ratio could be in ten years"
            note={`${sim.n_paths.toLocaleString()} simulated paths of interest rates and growth-asset returns, with the deficit paid off by the sponsor over ten years. An illustration of the range, not an actuarial valuation.`}
          >
            <p className="lead-stat">
              Median outcome <FactValue id="funding.sim.median_10y">{pct(sim.median_end, 1)}</FactValue> ·{" "}
              <FactValue id="funding.sim.prob_full_10y">{pct(sim.prob_fully_funded_end, 0)}</FactValue> chance of being fully funded
            </p>
            <div className="chart-box">
              <Line key={theme}
                data={{
                  labels: sim.years.map(String),
                  datasets: [
                    { label: "95th percentile", data: sim.percentiles["95"], borderWidth: 0, pointRadius: 0, backgroundColor: c.seq.outer, fill: "+4", order: 3 },
                    { label: "75th percentile", data: sim.percentiles["75"], borderWidth: 0, pointRadius: 0, backgroundColor: c.seq.inner, fill: "+2", order: 2 },
                    { label: "Median", data: sim.percentiles["50"], borderColor: c.seq.line, backgroundColor: c.seq.line, borderWidth: 2, pointRadius: 0, fill: false, order: 1 },
                    { label: "25th percentile", data: sim.percentiles["25"], borderWidth: 0, pointRadius: 0, fill: false, order: 4 },
                    { label: "5th percentile", data: sim.percentiles["5"], borderWidth: 0, pointRadius: 0, fill: false, order: 5 },
                  ],
                }}
                options={{
                  interaction: { mode: "index", intersect: false },
                  scales: { y: { ticks: { callback: pctTick(0) } }, x: { grid: { display: false }, title: { display: true, text: "Years from now" } } },
                  plugins: {
                    legend: { labels: { filter: (i) => !["25th percentile", "5th percentile"].includes(i.text),
                      generateLabels: (chart) => ChartJS.defaults.plugins.legend.labels.generateLabels(chart).map((l) =>
                        l.text === "95th percentile" ? { ...l, text: "5th to 95th percentile" } : l.text === "75th percentile" ? { ...l, text: "25th to 75th percentile" } : l) } },
                    tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${pct(c.raw as number, 1)}` } },
                  },
                }}
              />
            </div>
          </Panel>
        )}
      </div>

      <Panel title={`Government yield curve, ${data.curve.as_of}`} note="Par yields are what bonds are quoted at; zero rates are bootstrapped from them and used to discount each year's pension payments.">
        <div className="chart-box">
          <Line key={theme}
            data={{
              labels: data.curve.years,
              datasets: [
                { label: "Zero rate (bootstrapped)", data: data.curve.zero_rates, borderColor: c.series[0], borderWidth: 2, pointRadius: 0 },
                {
                  label: "Par yield (quoted)",
                  data: data.curve.years.map((y) => {
                    const i = data.curve.par_tenors.indexOf(y);
                    return i >= 0 ? data.curve.par_yields[i] : null;
                  }),
                  borderColor: c.neutral, backgroundColor: c.neutral, showLine: false, pointRadius: 5,
                },
              ],
            }}
            options={{ scales: { y: { ticks: { callback: pctTick(1) } }, x: { title: { display: true, text: "Years" }, ticks: { maxTicksLimit: 10 }, grid: { display: false } } } }}
          />
        </div>
      </Panel>
    </Page>
  );
}

function CustomStress() {
  const { scheme, periodEnd } = useScheme();
  const [rates, setRates] = useState(-50);
  const [equity, setEquity] = useState(-10);
  const [result, setResult] = useState<Stress | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try {
      setResult(await post(`/schemes/${scheme!.id}/funding/stress?period_end=${periodEnd}`, { rates_bps: rates, equity: equity / 100 }));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="custom-stress">
      <h3>Try your own scenario</h3>
      <label>Interest rates move <strong>{rates > 0 ? "+" : ""}{rates} bps</strong>
        <input type="range" min={-200} max={200} step={10} value={rates} onChange={(e) => setRates(Number(e.target.value))} />
      </label>
      <label>Growth assets move <strong>{equity > 0 ? "+" : ""}{equity}%</strong>
        <input type="range" min={-50} max={30} step={5} value={equity} onChange={(e) => setEquity(Number(e.target.value))} />
      </label>
      <button className="btn" onClick={run} disabled={busy}>Run scenario</button>
      {result && (
        <p className="stress-result">
          Funding ratio becomes <strong>{pct(result.funding_ratio)}</strong>,{" "}
          <span className={tone(result.change_in_funding_ratio)}>{(result.change_in_funding_ratio * 100).toFixed(1)} pts</span> versus today.
        </p>
      )}
    </div>
  );
}
