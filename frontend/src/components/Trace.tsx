import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api } from "../api";
import { useScheme } from "../scheme";

// Normalised lineage node (live analytics and stored report lineage have slightly different shapes)
type Node = {
  id: string;
  label: string;
  display: string;
  formula: string;
  sources: string[];
  nInputs: number;
  children?: Node[];
  truncated?: number;
};

function normalise(raw: any): Node {
  return {
    id: raw.id ?? raw.fact_id,
    label: raw.label,
    display: raw.display,
    formula: raw.formula ?? "",
    sources: raw.sources ?? [],
    nInputs: raw.n_inputs ?? raw.inputs?.length ?? 0,
    children: raw.children?.map(normalise),
    truncated: raw.children_truncated ?? Math.max(0, (raw.n_inputs ?? 0) - (raw.children?.length ?? 0)),
  };
}

type Target = { factId: string; reportId?: number };
const Ctx = createContext<(t: Target) => void>(() => {});
export const useTrace = () => useContext(Ctx);

export function TraceProvider({ children }: { children: ReactNode }) {
  const [target, setTarget] = useState<Target | null>(null);
  return (
    <Ctx.Provider value={setTarget}>
      {children}
      {target && <TraceDrawer target={target} onClose={() => setTarget(null)} />}
    </Ctx.Provider>
  );
}

/** A number you can click to see where it came from. */
export function FactValue({ id, children, reportId, className = "" }: { id?: string | null; children: ReactNode; reportId?: number; className?: string }) {
  const open = useTrace();
  if (!id) return <span className={className}>{children}</span>;
  return (
    <button type="button" className={`fact ${className}`} onClick={() => open({ factId: id, reportId })} title="Where does this number come from?">
      {children}
    </button>
  );
}

function useFetchNode() {
  const { scheme, periodEnd } = useScheme();
  return useCallback(
    async (t: Target): Promise<Node> => {
      const path = t.reportId
        ? `/reports/${t.reportId}/lineage/${encodeURIComponent(t.factId)}?depth=1`
        : `/schemes/${scheme!.id}/facts/${encodeURIComponent(t.factId)}/trace?depth=1${periodEnd ? `&period_end=${periodEnd}` : ""}`;
      return normalise(await api(path));
    },
    [scheme, periodEnd],
  );
}

function TraceDrawer({ target, onClose }: { target: Target; onClose: () => void }) {
  const fetchNode = useFetchNode();
  const [root, setRoot] = useState<Node | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setRoot(null);
    setError(null);
    fetchNode(target).then(setRoot).catch((e) => setError(e.message));
  }, [target, fetchNode]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="drawer-scrim" onClick={onClose}>
      <aside className="drawer" role="dialog" aria-label="Number lineage" onClick={(e) => e.stopPropagation()}>
        <header className="drawer-head">
          <div>
            <h2>Where this number comes from</h2>
            <p>{target.reportId ? `As recorded in report #${target.reportId}` : "Live, from the current data"}</p>
          </div>
          <button className="icon-btn" onClick={onClose} aria-label="Close">×</button>
        </header>
        <div className="drawer-body">
          {error && <p className="error">{error}</p>}
          {!root && !error && <p className="muted">Tracing…</p>}
          {root && <TrailNode node={root} target={target} depth={0} />}
        </div>
      </aside>
    </div>
  );
}

function TrailNode({ node, target, depth }: { node: Node; target: Target; depth: number }) {
  const fetchNode = useFetchNode();
  const [expanded, setExpanded] = useState<Node | null>(depth === 0 ? node : null);
  const [loading, setLoading] = useState(false);
  const isLeaf = node.nInputs === 0;

  const expand = async () => {
    if (expanded) return setExpanded(null);
    setLoading(true);
    try {
      setExpanded(await fetchNode({ factId: node.id, reportId: target.reportId }));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className={`trail ${depth === 0 ? "trail-root" : ""}`}>
      <div className="trail-card">
        <div className="trail-top">
          <span className="trail-label">{node.label}</span>
          <span className="trail-value">{node.display}</span>
        </div>
        {node.formula && <div className="trail-formula">{node.formula}</div>}
        {node.sources.map((s) => (
          <div key={s} className="trail-source">
            <span aria-hidden>▸</span> {s}
          </div>
        ))}
        {!isLeaf && depth > 0 && (
          <button className="link-btn" onClick={expand}>
            {loading ? "Loading…" : expanded ? "Hide inputs" : `Show ${node.nInputs} input${node.nInputs > 1 ? "s" : ""}`}
          </button>
        )}
      </div>
      {expanded?.children && expanded.children.length > 0 && (
        <div className="trail-children">
          {expanded.children.map((c) => (
            <TrailNode key={c.id} node={c} target={target} depth={depth + 1} />
          ))}
          {!!expanded.truncated && expanded.truncated > 0 && <p className="muted small">…and {expanded.truncated} more inputs</p>}
        </div>
      )}
    </div>
  );
}
