import { useEffect, useState, type ReactNode } from "react";
import type { Fact } from "../api";
import { FactValue } from "./Trace";

export function Page({ title, intro, actions, children }: { title: string; intro?: ReactNode; actions?: ReactNode; children: ReactNode }) {
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>{title}</h1>
          {intro && <p className="intro">{intro}</p>}
        </div>
        {actions && <div className="page-actions">{actions}</div>}
      </div>
      {children}
    </div>
  );
}

export function Panel({ title, note, children, actions }: { title?: string; note?: ReactNode; children: ReactNode; actions?: ReactNode }) {
  return (
    <section className="panel">
      {(title || actions) && (
        <div className="panel-head">
          {title && <h2>{title}</h2>}
          {actions}
        </div>
      )}
      {children}
      {note && <p className="note">{note}</p>}
    </section>
  );
}

export function Figure({ fact, label, sub, subFact, size = "lg" }: { fact?: Fact | null; label: string; sub?: ReactNode; subFact?: Fact | null; size?: "lg" | "md" }) {
  return (
    <div className={`figure figure-${size}`}>
      <div className="figure-label">{label}</div>
      <div className="figure-value">
        <FactValue id={fact?.id}>{fact?.display ?? "–"}</FactValue>
      </div>
      {subFact && (
        <div className={`figure-sub ${subFact.value !== null && subFact.value < 0 ? "neg" : "pos"}`}>
          <FactValue id={subFact.id}>
            {subFact.value !== null && subFact.value > 0 ? "+" : ""}
            {subFact.display}
          </FactValue>{" "}
          {sub}
        </div>
      )}
      {!subFact && sub && <div className="figure-sub">{sub}</div>}
    </div>
  );
}

export function Segmented<T extends string>({ value, options, onChange, label }: { value: T; options: { value: T; label: string }[]; onChange: (v: T) => void; label: string }) {
  return (
    <div className="segmented" role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} role="radio" aria-checked={o.value === value} className={o.value === value ? "on" : ""} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Status({ kind, children }: { kind: "good" | "bad" | "warn" | "info"; children: ReactNode }) {
  const icon = { good: "✓", bad: "!", warn: "!", info: "i" }[kind];
  return (
    <span className={`status status-${kind}`}>
      <span className="status-icon" aria-hidden>{icon}</span>
      {children}
    </span>
  );
}

export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let live = true;
    setLoading(true);
    setError(null);
    fn()
      .then((d) => live && setData(d))
      .catch((e) => live && setError(e.message))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  return { data, error, loading, reload: () => setTick((t) => t + 1) };
}

export function Loading({ error, children }: { error?: string | null; children?: ReactNode }) {
  if (error) return <div className="callout callout-bad">{error}</div>;
  return <div className="loading">{children ?? "Loading…"}</div>;
}
