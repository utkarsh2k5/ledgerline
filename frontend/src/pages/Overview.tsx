import { useEffect, useState } from "react";
import { Bar, Line } from "react-chartjs-2";
import { Link } from "react-router-dom";
import { api, type Fact } from "../api";
import { pctTick } from "../components/charts";
import { FactValue } from "../components/Trace";
import { Figure, Loading, Page, Panel, Segmented, Status, useAsync } from "../components/ui";
import { monthLabel, tone } from "../format";
import { useScheme } from "../scheme";
import { useChartColors, useTheme } from "../theme";

type PeriodCell = { ret: Fact | null; bench: Fact | null; excess: Fact | null };
type FundRow = {
  code: string; name: string; manager: string; asset_class: string;
  value: Fact | null; allocation: Fact | null; target: Fact | null; periods: Record<string, PeriodCell>;
};
type Overview = {
  period_end: string;
  periods: { key: string; label: string }[];
  kpis: Fact[];
  funds: FundRow[];
  cumulative: { months: string[]; portfolio: number[]; benchmark: number[] };
  recon: { open_material: number; open_minor: number };
  available_months: string[];
};

export default function OverviewPage() {
  const { scheme, periodEnd, setMonths, version } = useScheme();
  const { data, error } = useAsync<Overview>(
    () => api(`/schemes/${scheme!.id}/overview?period_end=${periodEnd}`),
    [scheme?.id, periodEnd, version],
  );
  const [period, setPeriod] = useState("3m");
  const c = useChartColors();
  const { theme } = useTheme();

  useEffect(() => {
    if (data) setMonths(data.available_months);
  }, [data, setMonths]);

  if (!scheme || !data) return <Loading error={error} />;
  const k = Object.fromEntries(data.kpis.map((f) => [f.id, f]));
  const total = data.funds.find((f) => f.code === "TOTAL")!;
  const mandates = data.funds.filter((f) => f.code !== "TOTAL");

  return (
    <Page
      title="Overview"
      intro={<>Position at {monthLabel(data.period_end)}. Click any underlined figure to see how it was calculated.</>}
    >
      {data.recon.open_material > 0 && (
        <div className="callout callout-warn">
          <Status kind="warn">
            {data.recon.open_material} material difference{data.recon.open_material > 1 ? "s" : ""} between custodian and manager data
          </Status>
          <span>Reports for this period are blocked until they're resolved.</span>
          <Link to="/reconciliation" className="btn small">Review differences</Link>
        </div>
      )}

      <div className="figures">
        <Figure label="Scheme assets" fact={k["mv.TOTAL.end"]} />
        <Figure label="Return this quarter" fact={k["perf.TOTAL.3m.ret"]} subFact={k["perf.TOTAL.3m.excess"]} sub="vs benchmark" />
        <Figure label="Return over one year" fact={k["perf.TOTAL.1y.ret"]} subFact={k["perf.TOTAL.1y.excess"]} sub="vs benchmark" />
        <Figure label="Funding ratio" fact={k["funding.ratio"]}
          sub={k["funding.surplus"] && <FactValue id="funding.surplus">{k["funding.surplus"].display.replace("-", "")} {k["funding.surplus"].value! < 0 ? "deficit" : "surplus"}</FactValue>} />
        <Figure label="Interest-rate hedge" fact={k["funding.hedge_ratio"]} sub="of liability rate sensitivity" />
      </div>

      <div className="grid-2">
        <Panel title="Growth since the start of the data" note="Total fund vs its strategic benchmark, cumulative.">
          <div className="chart-box">
            <Line key={theme}
              data={{
                labels: data.cumulative.months.map(monthLabel),
                datasets: [
                  { label: "Total fund", data: data.cumulative.portfolio.map((v) => v - 1), borderColor: c.series[0], borderWidth: 2, pointRadius: 0, pointHoverRadius: 4 },
                  { label: "Benchmark", data: data.cumulative.benchmark.map((v) => v - 1), borderColor: c.neutral, borderDash: [6, 4], borderWidth: 1.6, pointRadius: 0, pointHoverRadius: 4 },
                ],
              }}
              options={{
                interaction: { mode: "index", intersect: false },
                scales: { y: { ticks: { callback: pctTick(0) } }, x: { ticks: { maxTicksLimit: 7 }, grid: { display: false } } },
                plugins: { tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${((c.raw as number) * 100).toFixed(2)}%` } } },
              }}
            />
          </div>
        </Panel>
        <Panel title="Allocation vs strategy" note="Bars show actual weights; the tick marks the strategic target.">
          <div className="chart-box">
            <Bar key={theme}
              data={{
                labels: mandates.map((m) => m.code),
                datasets: [
                  { label: "Actual", data: mandates.map((m) => m.allocation?.value ?? 0), backgroundColor: c.series[0], borderRadius: 4, barPercentage: 0.6 },
                  { label: "Target", data: mandates.map((m) => m.target?.value ?? 0), type: "line" as any, showLine: false, pointStyle: "line", pointRadius: 16, pointBorderWidth: 3, borderColor: c.target, backgroundColor: c.target } as any,
                ],
              }}
              options={{
                scales: { y: { beginAtZero: true, ticks: { callback: pctTick(0) } }, x: { grid: { display: false } } },
                plugins: { tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${((c.raw as number) * 100).toFixed(1)}%` } } },
              }}
            />
          </div>
        </Panel>
      </div>

      <Panel
        title="Performance by mandate"
        actions={<Segmented label="Period" value={period} onChange={setPeriod} options={data.periods.map((p) => ({ value: p.key, label: p.label }))} />}
        note="Time-weighted returns (Modified Dietz, chain-linked). Periods over one year are annualised."
      >
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr><th>Mandate</th><th className="hide-sm">Manager</th><th className="num">Value</th><th className="num">Weight</th><th className="num">Return</th><th className="num">Benchmark</th><th className="num">Relative</th></tr>
            </thead>
            <tbody>
              {[...mandates, total].map((f) => {
                const p = f.periods[period];
                return (
                  <tr key={f.code} className={f.code === "TOTAL" ? "total" : ""}>
                    <td>{f.name}</td>
                    <td className="muted hide-sm">{f.manager}</td>
                    <td className="num"><FactValue id={f.value?.id}>{f.value?.display}</FactValue></td>
                    <td className="num"><FactValue id={f.allocation?.id}>{f.allocation?.display ?? "100.00%"}</FactValue></td>
                    <td className="num"><FactValue id={p?.ret?.id}>{p?.ret?.display}</FactValue></td>
                    <td className="num"><FactValue id={p?.bench?.id}>{p?.bench?.display}</FactValue></td>
                    <td className={`num ${tone(p?.excess?.value)}`}>
                      <FactValue id={p?.excess?.id}>{p?.excess && p.excess.value! > 0 ? "+" : ""}{p?.excess?.display}</FactValue>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>
    </Page>
  );
}
