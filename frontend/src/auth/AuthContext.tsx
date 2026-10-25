import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api, type SeedUser } from "../api/client";
import type { Me } from "../api/types";

type AuthState = {
  me: Me | null;
  loading: boolean;
  refresh: () => Promise<void>;
  loginDev: (user: SeedUser) => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  // `loading` is only true for the first check: a later refresh (e.g. after joining an org) must
  // not make RequireAuth unmount the page that asked for it.
  const refresh = useCallback(async () => {
    try {
      setMe(await api.me());
    } catch {
      setMe(null); // backend unreachable: show the login page rather than spin
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const value = useMemo<AuthState>(
    () => ({
      me,
      loading,
      refresh,
      async loginDev(user: SeedUser) {
        setMe(await api.devLogin(user));
      },
      async logout() {
        await api.logout();
        setMe(null);
      },
    }),
    [me, loading, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}
