import { useState } from "react";
import { useAuth, type User } from "../auth";
import { GitHubLink } from "../components/GitHubLink";
import { ThemeButton } from "../theme";

const ROLES: { role: User["role"]; title: string; what: string; recommended?: boolean }[] = [
  {
    role: "analyst",
    title: "Analyst",
    what: "Upload source files, resolve data differences and generate the quarterly reports.",
    recommended: true,
  },
  {
    role: "admin",
    title: "Admin",
    what: "Everything an analyst can do, plus releasing a report while differences are still open.",
  },
  {
    role: "viewer",
    title: "Trustee",
    what: "Read-only. Browse the dashboards, trace any figure and download finished reports.",
  },
];

export default function Login() {
  const { loginAs } = useAuth();
  const [busy, setBusy] = useState<User["role"] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const enter = async (role: User["role"]) => {
    setBusy(role);
    setError(null);
    try {
      await loginAs(role);
    } catch (e) {
      setError((e as Error).message);
      setBusy(null);
    }
  };

  return (
    <div className="landing">
      <div className="landing-story">
        <div className="brand big">
          <span className="brand-mark" aria-hidden>
            <svg viewBox="0 0 24 24" width="28" height="28">
              <path d="M4 4v16h16" fill="none" stroke="currentColor" strokeWidth="2.2" />
              <path d="M8 15l4-4 3 3 5-6" fill="none" stroke="currentColor" strokeWidth="2.2" />
            </svg>
          </span>
          Ledgerline
        </div>
        <p className="landing-lede">
          Quarterly performance reporting for defined benefit pension schemes, where every number can show its working.
        </p>
        <ul className="landing-points">
          <li>Reconciles custodian and fund manager data before anything is published</li>
          <li>Explains performance with attribution that adds up exactly</li>
          <li>Generates Word, PowerPoint and interactive reports in about a second</li>
          <li>Traces any figure back to the row of the file it came from</li>
        </ul>
        <div className="landing-links">
          <GitHubLink onDark label="Source code on GitHub" />
        </div>
        <svg className="landing-art" viewBox="0 0 360 150" aria-hidden>
          <path d="M10 120 L70 96 L120 104 L180 70 L240 78 L300 40 L350 30" fill="none" stroke="#9ec5f4" strokeWidth="2.5" />
          <path d="M10 124 L70 104 L120 108 L180 86 L240 88 L300 58 L350 50" fill="none" stroke="#56718f" strokeWidth="2" strokeDasharray="5 5" />
          <circle cx="300" cy="40" r="5" fill="#fff" />
          <path d="M300 40 V140" stroke="#ffffff55" strokeDasharray="2 4" />
        </svg>
      </div>

      <main className="landing-main">
        <ThemeButton />
        <div>
          <h1>Explore the demo</h1>
          <p className="intro">
            Pick a role to look around. No sign-up, and the data is a fictional £1.5bn pension scheme.
          </p>
        </div>
        <div className="roles">
          {ROLES.map((r) => (
            <button key={r.role} className={`role ${r.recommended ? "recommended" : ""}`} onClick={() => enter(r.role)} disabled={busy !== null}>
              <strong>
                {r.title}
                {r.recommended && <span className="tag">Start here</span>}
              </strong>
              <span>{r.what}</span>
              <em className="go" style={{ fontStyle: "normal" }}>{busy === r.role ? "Opening…" : "Enter"}</em>
            </button>
          ))}
        </div>
        {error && <p className="error">{error}</p>}
      </main>
    </div>
  );
}
