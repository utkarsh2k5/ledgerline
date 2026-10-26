import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api } from "./api";
import { useAuth } from "./auth";

export type Scheme = {
  id: number;
  code: string;
  name: string;
  currency: string;
  sponsor: string;
  latest_month: string | null;
};

type SchemeState = {
  scheme: Scheme | null;
  periodEnd: string | null;
  setPeriodEnd: (p: string) => void;
  months: string[];
  setMonths: (m: string[]) => void;
  version: number; // bump to make pages refetch after data changes
  refresh: () => void;
};

const Ctx = createContext<SchemeState | null>(null);

export function SchemeProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const [scheme, setScheme] = useState<Scheme | null>(null);
  const [periodEnd, setPeriodEnd] = useState<string | null>(null);
  const [months, setMonths] = useState<string[]>([]);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    if (!user) return;
    api<Scheme[]>("/schemes").then((list) => {
      if (list.length) {
        setScheme(list[0]);
        setPeriodEnd((p) => p ?? list[0].latest_month);
      }
    });
  }, [user, version]);

  return (
    <Ctx.Provider
      value={{ scheme, periodEnd, setPeriodEnd, months, setMonths, version, refresh: () => setVersion((v) => v + 1) }}
    >
      {children}
    </Ctx.Provider>
  );
}

export function useScheme() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useScheme outside SchemeProvider");
  return ctx;
}
