import { Chart as ChartJS } from "chart.js";
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

export type Theme = "light" | "dark";
const KEY = "ledgerline.theme";

// Chart colours per theme. Categorical slots are a colour-blind-safe set,
// with separately tuned steps for the dark background.
const PALETTES = {
  light: {
    series: ["#2a78d6", "#eb6834", "#1baf7a"],
    neutral: "#56606e",
    seq: { outer: "#cde2fb", inner: "#86b6ef", line: "#1c5cab" },
    target: "#13294b",
    text: "#56606e",
    grid: "#e3e7ec",
    tooltip: "#13294b",
  },
  dark: {
    series: ["#3987e5", "#d95926", "#199e70"],
    neutral: "#a3afbf",
    seq: { outer: "#1d3554", inner: "#2f5f99", line: "#86b6ef" },
    target: "#eef3f9",
    text: "#a3afbf",
    grid: "#263446",
    tooltip: "#0a111c",
  },
};

function initial(): Theme {
  try {
    const saved = localStorage.getItem(KEY);
    if (saved === "light" || saved === "dark") return saved;
  } catch {
    /* storage blocked: fall back to the OS setting */
  }
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function applyChartDefaults(theme: Theme) {
  const p = PALETTES[theme];
  ChartJS.defaults.color = p.text;
  ChartJS.defaults.borderColor = p.grid;
  ChartJS.defaults.plugins.tooltip.backgroundColor = p.tooltip;
}

const Ctx = createContext<{ theme: Theme; toggle: () => void }>({ theme: "light", toggle: () => {} });

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(initial);

  // apply before paint of the first chart
  document.documentElement.dataset.theme = theme;
  applyChartDefaults(theme);

  useEffect(() => {
    try {
      localStorage.setItem(KEY, theme);
    } catch {
      /* ignore */
    }
  }, [theme]);

  const toggle = useCallback(() => setTheme((t) => (t === "dark" ? "light" : "dark")), []);
  return <Ctx.Provider value={{ theme, toggle }}>{children}</Ctx.Provider>;
}

export const useTheme = () => useContext(Ctx);
export const useChartColors = () => PALETTES[useContext(Ctx).theme];

export function ThemeButton() {
  const { theme, toggle } = useTheme();
  const dark = theme === "dark";
  return (
    <button className="theme-btn" onClick={toggle} aria-label={dark ? "Switch to light mode" : "Switch to dark mode"} title={dark ? "Light mode" : "Dark mode"}>
      {dark ? (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <circle cx="12" cy="12" r="4.5" />
          <path d="M12 2v2.5M12 19.5V22M4.2 4.2l1.8 1.8M18 18l1.8 1.8M2 12h2.5M19.5 12H22M4.2 19.8 6 18M18 6l1.8-1.8" />
        </svg>
      ) : (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round">
          <path d="M20.5 14.5A8.5 8.5 0 0 1 9.5 3.5a8.5 8.5 0 1 0 11 11Z" />
        </svg>
      )}
    </button>
  );
}
