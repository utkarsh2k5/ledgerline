import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, getToken, post, setToken, setUnauthorizedHandler } from "./api";

export type User = { id: number; email: string; name: string; role: "admin" | "analyst" | "viewer" };

type AuthState = {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  loginAs: (role: User["role"]) => Promise<void>;
  logout: () => void;
  can: (role: User["role"]) => boolean;
};

const RANK = { viewer: 0, analyst: 1, admin: 2 };
const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(Boolean(getToken()));

  const logout = useCallback(() => {
    setToken(null);
    setUser(null);
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => setUser(null));
    if (!getToken()) return;
    api<User>("/auth/me")
      .then(setUser)
      .catch(() => setToken(null))
      .finally(() => setLoading(false));
  }, []);

  const login = async (email: string, password: string) => {
    const res = await post<{ access_token: string; user: User }>("/auth/login", { email, password });
    setToken(res.access_token);
    setUser(res.user);
  };

  // One-click access by role (the public demo has no passwords to remember)
  const loginAs = async (role: User["role"]) => {
    const res = await post<{ access_token: string; user: User }>("/auth/demo", { role });
    setToken(res.access_token);
    setUser(res.user);
  };

  const can = (role: User["role"]) => (user ? RANK[user.role] >= RANK[role] : false);

  return <Ctx.Provider value={{ user, loading, login, loginAs, logout, can }}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}
