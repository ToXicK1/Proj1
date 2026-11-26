import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, setCsrfToken, type UserDto } from "./api";

type SessionState =
  | { status: "loading" }
  | { status: "anonymous"; signedOut?: boolean }  // signedOut: this browser just signed out (not a visit to a link)
  | { status: "authenticated"; user: UserDto };

interface SessionContextValue {
  state: SessionState;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  /** Re-reads the account, for example after the first password change. */
  refresh: () => Promise<void>;
}

const SessionContext = createContext<SessionContextValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<SessionState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    api
      .me()
      .then((session) => {
        if (cancelled) return;
        setCsrfToken(session.csrf_token);
        setState({ status: "authenticated", user: session.user });
      })
      .catch(() => {
        if (!cancelled) setState({ status: "anonymous" });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    const session = await api.login(email, password);
    setCsrfToken(session.csrf_token);
    setState({ status: "authenticated", user: session.user });
  }, []);

  const signOut = useCallback(async () => {
    try {
      await api.logout();
    } finally {
      setCsrfToken(null);
      setState({ status: "anonymous", signedOut: true });
    }
  }, []);

  const refresh = useCallback(async () => {
    const session = await api.me();
    setCsrfToken(session.csrf_token);
    setState({ status: "authenticated", user: session.user });
  }, []);

  const value = useMemo(() => ({ state, signIn, signOut, refresh }), [state, signIn, signOut, refresh]);
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionContextValue {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession must be used inside SessionProvider");
  return ctx;
}
