import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../lib/api";

const AuthContext = createContext(null);

// status: "loading" | "authenticated" | "unauthenticated" | "error"
export function AuthProvider({ children }) {
  const [status, setStatus] = useState("loading");
  const [user, setUser] = useState(null);
  const [error, setError] = useState(null);

  const refetch = useCallback(async () => {
    setStatus("loading");
    try {
      const me = await api.me();
      setUser(me);
      setStatus("authenticated");
      setError(null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setUser(null);
        setStatus("unauthenticated");
        setError(null);
      } else {
        setUser(null);
        setStatus("error");
        setError(err);
      }
    }
  }, []);

  useEffect(() => {
    refetch();
  }, [refetch]);

  const logout = useCallback(async () => {
    try {
      await api.logout();
    } finally {
      setUser(null);
      setStatus("unauthenticated");
    }
  }, []);

  const value = useMemo(
    () => ({ status, user, error, refetch, logout, setUser }),
    [status, user, error, refetch, logout]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
