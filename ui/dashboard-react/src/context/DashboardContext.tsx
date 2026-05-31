import React, { createContext, useContext, useEffect, useState } from "react";
import { requireAuth, resolveAccountId, logout as sessionLogout } from "../lib/session";

export interface DashboardContextValue {
  accountId: number;
  accountCode: string | null;
  displayName: string;
  ready: boolean;
  logout: () => void;
}

const DashboardContext = createContext<DashboardContextValue | null>(null);

export function DashboardProvider({ children }: { children: React.ReactNode }) {
  const [accountId, setAccountId] = useState(0);
  const [accountCode, setAccountCode] = useState<string | null>(null);
  const [displayName, setDisplayName] = useState("");
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!requireAuth()) return;
    resolveAccountId()
      .then(({ accountId: id, accountCode: code, displayName: name }) => {
        setAccountId(id);
        setAccountCode(code);
        setDisplayName(name);
        setReady(true);
      })
      .catch(() => {
        window.location.replace("/ui/login.html");
      });
  }, []);

  const logout = () => {
    if (confirm("Oturumu kapatmak istiyor musunuz?")) {
      sessionLogout();
    }
  };

  if (!ready) {
    return (
      <div className="min-h-screen bg-[#14151a] flex items-center justify-center text-neutral-400">
        Yükleniyor…
      </div>
    );
  }

  return (
    <DashboardContext.Provider value={{ accountId, accountCode, displayName, ready, logout }}>
      {children}
    </DashboardContext.Provider>
  );
}

export function useDashboard(): DashboardContextValue {
  const ctx = useContext(DashboardContext);
  if (!ctx) throw new Error("useDashboard must be used within DashboardProvider");
  return ctx;
}
