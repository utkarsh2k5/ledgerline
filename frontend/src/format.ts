export const pct = (v: number | null | undefined, d = 2) =>
  v === null || v === undefined || Number.isNaN(v) ? "–" : `${(v * 100).toFixed(d)}%`;

export const signedPct = (v: number | null | undefined, d = 2) =>
  v === null || v === undefined ? "–" : `${v > 0 ? "+" : ""}${(v * 100).toFixed(d)}%`;

export const money = (v: number | null | undefined, cur = "GBP") => {
  if (v === null || v === undefined) return "–";
  const s = ({ GBP: "£", USD: "$", EUR: "€", INR: "₹" } as Record<string, string>)[cur] ?? "";
  const a = Math.abs(v);
  const sign = v < 0 ? "-" : "";
  if (a >= 1e9) return `${sign}${s}${(a / 1e9).toFixed(2)}bn`;
  if (a >= 1e6) return `${sign}${s}${(a / 1e6).toFixed(1)}m`;
  return `${sign}${s}${a.toLocaleString("en-GB", { maximumFractionDigits: 0 })}`;
};

export const tone = (v: number | null | undefined) =>
  v === null || v === undefined || Math.abs(v) < 0.00005 ? "" : v > 0 ? "pos" : "neg";

export const monthLabel = (iso: string) =>
  new Date(iso + "T00:00:00").toLocaleDateString("en-GB", { month: "short", year: "numeric" });

export const dateTime = (iso: string) =>
  new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
