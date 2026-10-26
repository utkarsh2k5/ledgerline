import { NavLink, Outlet } from "react-router-dom";
import { useAuth, type User } from "../auth";
import { ThemeButton } from "../theme";
import { GitHubLink } from "./GitHubLink";
import { monthLabel } from "../format";
import { useScheme } from "../scheme";

const NAV = [
  { to: "/", label: "Overview", end: true },
  { to: "/reconciliation", label: "Reconciliation" },
  { to: "/attribution", label: "Attribution" },
  { to: "/funding", label: "Funding" },
  { to: "/reports", label: "Reports" },
  { to: "/data", label: "Data" },
  { to: "/audit", label: "Audit trail" },
];

export default function Layout() {
  const { user, logout, loginAs } = useAuth();
  const { scheme, periodEnd, setPeriodEnd, months } = useScheme();

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark" aria-hidden>
            <svg viewBox="0 0 24 24" width="22" height="22">
              <path d="M4 4v16h16" fill="none" stroke="currentColor" strokeWidth="2.2" />
              <path d="M8 15l4-4 3 3 5-6" fill="none" stroke="currentColor" strokeWidth="2.2" />
            </svg>
          </span>
          Ledgerline
        </div>
        <nav>
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end} className={({ isActive }) => (isActive ? "active" : "")}>
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          <label className="role-switch">
            Viewing as
            <select value={user?.role} onChange={(e) => loginAs(e.target.value as User["role"])}>
              <option value="analyst">Analyst</option>
              <option value="admin">Admin</option>
              <option value="viewer">Trustee (read-only)</option>
            </select>
          </label>
          <button className="link-btn light" onClick={logout}>Back to start</button>
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <div className="scheme-name">
            <strong>{scheme?.name ?? "…"}</strong>
            {scheme && <span>{scheme.sponsor}</span>}
          </div>
          <div className="top-tools">
            {periodEnd && (
              <label className="period-pick">
                Period end
                <select value={periodEnd} onChange={(e) => setPeriodEnd(e.target.value)}>
                  {(months.length ? [...months].reverse() : [periodEnd]).map((m) => (
                    <option key={m} value={m}>{monthLabel(m)}</option>
                  ))}
                </select>
              </label>
            )}
            <GitHubLink />
            <ThemeButton />
          </div>
        </header>
        <main className="content">
          {scheme && periodEnd ? <Outlet /> : <div className="loading">Loading scheme…</div>}
        </main>
      </div>
    </div>
  );
}
