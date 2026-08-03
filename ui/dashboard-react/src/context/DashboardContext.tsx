import React, { createContext, useContext, useEffect, useState } from "react";
import { resolveAccountId, logout as sessionLogout } from "../lib/session";
import LoginPage from "../features/auth/LoginPage";
import PasswordChangeGate from "../features/auth/PasswordChangeGate";
import { ApiError, apiRequest } from "../core/api/http";
import { dismissMobileAppSplash } from "../app/mobileSplash";

export interface DashboardContextValue {
  accountId: number;
  accountCode: string | null;
  displayName: string;
  isAdmin: boolean;
  isFirstLogin: boolean;
  ready: boolean;
  completeFirstLogin: () => void;
  logout: () => void;
}

const DashboardContext = createContext<DashboardContextValue | null>(null);

export function DashboardProvider({ children }: { children: React.ReactNode }) {
  const [accountId, setAccountId] = useState(0);
  const [accountCode, setAccountCode] = useState<string | null>(null);
  const [displayName, setDisplayName] = useState("");
  const [isAdmin, setIsAdmin] = useState(false);
  const [ready, setReady] = useState(false);
  const [mustChangePassword, setMustChangePassword] = useState(
    () => sessionStorage.getItem("v2_must_change_password") === "1",
  );
  const [isFirstLogin, setIsFirstLogin] = useState(
    () => sessionStorage.getItem("v2_first_login") === "1",
  );
  const [authRequired, setAuthRequired] = useState(false);
  const [startupError, setStartupError] = useState("");

  const bootstrap = () => {
    setStartupError("");
    if (new URLSearchParams(window.location.search).get("auth") === "login") {
      setAuthRequired(true);
      return;
    }
    resolveAccountId()
      .then(({ accountId: id, accountCode: code, displayName: name, isAdmin: admin }) => {
        setAccountId(id);
        setAccountCode(code);
        setDisplayName(name);
        setIsAdmin(admin);
        setReady(true);
        setAuthRequired(false);
      })
      .catch((error) => {
        if (error instanceof ApiError && error.status === 401) {
          setAuthRequired(true);
          return;
        }
        setStartupError(error instanceof Error ? error.message : "Uygulama başlatılamadı.");
      });
  };

  useEffect(bootstrap, []);

  useEffect(() => {
    if (
      authRequired ||
      Boolean(startupError) ||
      (ready && mustChangePassword && accountId > 0)
    ) {
      dismissMobileAppSplash();
    }
  }, [accountId, authRequired, mustChangePassword, ready, startupError]);

  useEffect(() => {
    if (!ready) return;
    let stopped = false;
    let pingTimer = 0;
    let bootTimer = 0;
    let channel: BroadcastChannel | null = null;

    const forceLogin = () => {
      localStorage.removeItem("token");
      sessionStorage.removeItem("token");
      setReady(false);
      setAuthRequired(true);
    };

    const ping = async () => {
      if (stopped || !accountId || document.hidden || !navigator.onLine) return;
      try {
        const result = await apiRequest<{ kicked?: boolean }>(
          `/api/auth/ping?account_id=${accountId}`,
          { timeoutMs: 8_000, dedupe: false, redirectOnAuthError: false },
        );
        if (result.kicked) forceLogin();
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) forceLogin();
      }
    };

    const checkBoot = async () => {
      if (stopped || document.hidden || !navigator.onLine) return;
      try {
        const result = await apiRequest<{ boot_id?: string }>("/api/boot-id", {
          timeoutMs: 8_000,
          dedupe: false,
          redirectOnAuthError: false,
        });
        const next = result.boot_id ? String(result.boot_id) : "";
        const previous = sessionStorage.getItem("v2_boot_id");
        // Sunucu yeniden başlasa da paylaşımlı DB oturumu geçerliliğini korur.
        // boot_id yalnız tanı içindir; geçerli HttpOnly çerezi istemci tarafında
        // düşürmek kullanıcıyı gereksiz yere giriş ekranına gönderiyordu.
        if (next) sessionStorage.setItem("v2_boot_id", next);
      } catch {
        /* A temporary health failure must not destroy the session. */
      }
    };

    try {
      channel = new BroadcastChannel("ayserose-session");
      channel.onmessage = (event) => {
        if (event.data?.type === "logout") forceLogin();
      };
    } catch {
      channel = null;
    }

    void ping();
    void checkBoot();
    pingTimer = window.setInterval(ping, 45_000);
    bootTimer = window.setInterval(checkBoot, 300_000);
    return () => {
      stopped = true;
      window.clearInterval(pingTimer);
      window.clearInterval(bootTimer);
      channel?.close();
    };
  }, [accountId, ready]);

  const logout = () => {
    if (confirm("Oturumu kapatmak istiyor musunuz?")) {
      void sessionLogout(accountId).catch((error) => {
        setStartupError(
          error instanceof Error
            ? `Güvenli çıkış tamamlanamadı: ${error.message}`
            : "Güvenli çıkış tamamlanamadı.",
        );
      });
    }
  };

  if (authRequired) {
    return (
      <LoginPage
        onAuthenticated={({ mustChangePassword: mustChange, isFirstLogin: firstLogin }) => {
          setMustChangePassword(mustChange);
          setIsFirstLogin(firstLogin);
          const url = new URL(window.location.href);
          const next = url.searchParams.get("next");
          if (next) {
            try {
              const destination = new URL(next, window.location.origin);
              if (
                destination.origin === window.location.origin &&
                destination.pathname.startsWith("/ui/")
              ) {
                window.location.replace(
                  `${destination.pathname}${destination.search}${destination.hash}`,
                );
                return;
              }
            } catch {
              /* Ignore malformed return paths. */
            }
          }
          url.searchParams.delete("auth");
          url.searchParams.delete("next");
          window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
          bootstrap();
        }}
      />
    );
  }

  if (startupError) {
    return (
      <main className="min-h-screen bg-[#101115] text-neutral-100 grid place-items-center p-6">
        <section className="max-w-md rounded-3xl border border-amber-300/15 bg-[#191b21] p-8 text-center">
          <h1 className="text-xl font-black text-white">Bağlantı kurulamadı</h1>
          <p className="mt-3 text-sm leading-6 text-neutral-400">{startupError}</p>
          <button
            type="button"
            onClick={bootstrap}
            className="mt-6 rounded-xl bg-[#f0b90b] px-5 py-3 text-sm font-black text-neutral-950"
          >
            Yeniden dene
          </button>
          {(new URLSearchParams(window.location.search).has("account_id") ||
            new URLSearchParams(window.location.search).has("account_code")) && (
            <button
              type="button"
              onClick={() => {
                const url = new URL(window.location.href);
                url.searchParams.delete("account_id");
                url.searchParams.delete("account_code");
                url.searchParams.delete("bot_id");
                url.searchParams.delete("tab");
                window.location.assign(`${url.pathname}${url.search}${url.hash}`);
              }}
              className="mt-3 block w-full rounded-xl border border-neutral-700 px-5 py-3 text-sm font-black text-neutral-300"
            >
              Yönetim merkezine dön
            </button>
          )}
        </section>
      </main>
    );
  }

  if (!ready) {
    return (
      <div className="min-h-screen bg-[#14151a] flex items-center justify-center text-neutral-400">
        Yükleniyor…
      </div>
    );
  }

  if (mustChangePassword && accountId > 0) {
    return (
      <PasswordChangeGate
        accountId={accountId}
        displayName={displayName}
        onLogout={logout}
        onCompleted={() => {
          sessionStorage.removeItem("v2_must_change_password");
          setMustChangePassword(false);
        }}
      />
    );
  }

  const completeFirstLogin = () => {
    sessionStorage.removeItem("v2_first_login");
    setIsFirstLogin(false);
  };

  return (
    <DashboardContext.Provider
      value={{
        accountId,
        accountCode,
        displayName,
        isAdmin,
        isFirstLogin,
        ready,
        completeFirstLogin,
        logout,
      }}
    >
      {children}
    </DashboardContext.Provider>
  );
}

export function useDashboard(): DashboardContextValue {
  const ctx = useContext(DashboardContext);
  if (!ctx) throw new Error("useDashboard must be used within DashboardProvider");
  return ctx;
}
