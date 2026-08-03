import React, {
  Suspense,
  lazy,
  useState,
  useEffect,
  useRef,
} from "react";
import HomeTab from "./components/HomeTab";
import TradeTab from "./components/TradeTab";
import BotsTab from "./components/BotsTab";
import PortfolioTab from "./components/PortfolioTab";
import ContactTab from "./components/ContactTab";
import SettingsTab from "./components/SettingsTab";
import BotDetailPage from "./features/bots/BotDetailPage";
import SpotOrderModal from "./features/trade/SpotOrderModal";
import UserPopup from "./features/notifications/UserPopup";
import BrandMark from "./components/brand/BrandMark";
import { useDashboard } from "./context/DashboardContext";
import {
  DashboardDataProvider,
  useDashboardData,
} from "./core/state/DashboardDataContext";
import { useTabNavigation } from "./app/useTabNavigation";
import { dismissMobileAppSplash } from "./app/mobileSplash";
import {
  LogOut,
  Coins,
  Search,
  Sliders,
  MessageSquare,
  Settings as SettingsIcon,
  Cpu,
  UserRound,
  RefreshCw,
  CheckCircle2,
  AlertCircle,
} from "lucide-react";

const AdminPage = lazy(() => import("./features/admin/AdminPage"));

export default function App() {
  const { accountId, isAdmin } = useDashboard();
  const search = new URLSearchParams(window.location.search);
  const isAdminAccountView =
    isAdmin && (search.has("account_id") || search.has("account_code"));

  useEffect(() => {
    if (isAdmin && !isAdminAccountView) dismissMobileAppSplash();
  }, [isAdmin, isAdminAccountView]);

  if (isAdmin && !isAdminAccountView) {
    return (
      <Suspense fallback={<TabSkeleton />}>
        <AdminPage
          onOpenAccount={(nextAccountId) => {
            const url = new URL(window.location.href);
            url.searchParams.set("account_id", String(nextAccountId));
            url.searchParams.delete("account_code");
            url.searchParams.delete("bot_id");
            url.searchParams.delete("tab");
            window.location.assign(`${url.pathname}${url.search}${url.hash}`);
          }}
        />
      </Suspense>
    );
  }

  return (
    <DashboardDataProvider accountId={accountId}>
      <AppContent />
    </DashboardDataProvider>
  );
}

function AppContent() {
  const {
    accountId,
    displayName,
    isAdmin,
    isFirstLogin,
    completeFirstLogin,
    logout,
  } = useDashboard();
  const { bots, setBots, wallet, prices, status, lastUpdatedAt, error, refresh } =
    useDashboardData();
  const [activeTab, setActiveTab] = useTabNavigation();
  const [selectedBotId, setSelectedBotId] = useState<number | null>(() => {
    const raw = new URLSearchParams(window.location.search).get("bot_id");
    const value = Number(raw);
    return Number.isInteger(value) && value > 0 ? value : null;
  });
  const [botStudioOpen, setBotStudioOpen] = useState(false);
  const botStudioOpenRef = useRef(false);
  const [tradeRequest, setTradeRequest] = useState<{
    symbol: string;
    side: "BUY" | "SELL";
  } | null>(null);
  const [botTemplateDraft, setBotTemplateDraft] = useState<{
    id: number;
    params: Record<string, unknown>;
  } | null>(null);
  const retainedTabsRef = useRef(
    new Set(["binance", "trade", "bots", activeTab]),
  );
  const pullStartRef = useRef<number | null>(null);
  const pullDistanceRef = useRef(0);
  const [pullDistance, setPullDistance] = useState(0);
  const [pullRefreshing, setPullRefreshing] = useState(false);
  const [pullOutcome, setPullOutcome] = useState<"idle" | "success" | "error">("idle");
  retainedTabsRef.current.add(activeTab);
  botStudioOpenRef.current = botStudioOpen;

  useEffect(() => {
    if (lastUpdatedAt !== null || status === "offline" || Boolean(error)) {
      dismissMobileAppSplash();
    }
  }, [error, lastUpdatedAt, status]);

  const handleApplyLeaderboard = (params: unknown) => {
    const normalized =
      params && typeof params === "object" && !Array.isArray(params)
        ? (params as Record<string, unknown>)
        : {};
    setBotTemplateDraft({ id: Date.now(), params: normalized });
    setActiveTab("bots");
  };

  useEffect(() => {
    const onPopState = () => {
      const value = Number(new URLSearchParams(window.location.search).get("bot_id"));
      if (botStudioOpenRef.current && Number.isInteger(value) && value > 0) {
        const url = new URL(window.location.href);
        url.searchParams.delete("bot_id");
        window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
        setSelectedBotId(null);
        return;
      }
      setSelectedBotId(Number.isInteger(value) && value > 0 ? value : null);
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  useEffect(() => {
    if (!("serviceWorker" in navigator)) return;
    const onServiceWorkerMessage = (event: MessageEvent) => {
      if (event.data?.type !== "AYSEROSE_OPEN_BOT_DETAIL") return;
      const botId = Number(event.data?.botId);
      if (!Number.isInteger(botId) || botId <= 0) return;
      if (botStudioOpenRef.current) return;
      setActiveTab("bots");
      const url = new URL(window.location.href);
      url.searchParams.set("tab", "bots");
      url.searchParams.set("bot_id", String(botId));
      window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
      setSelectedBotId(botId);
      window.scrollTo({ top: 0, behavior: "smooth" });
    };
    navigator.serviceWorker.addEventListener("message", onServiceWorkerMessage);
    return () => navigator.serviceWorker.removeEventListener("message", onServiceWorkerMessage);
  }, [setActiveTab]);

  useEffect(() => {
    const onTouchStart = (event: TouchEvent) => {
      if (
        window.innerWidth >= 640 ||
        window.scrollY > 0 ||
        document.body.style.overflow === "hidden" ||
        event.touches.length !== 1
      ) {
        pullStartRef.current = null;
        return;
      }
      pullStartRef.current = event.touches[0].clientY;
    };
    const onTouchMove = (event: TouchEvent) => {
      if (pullStartRef.current === null || event.touches.length !== 1) return;
      const distance = Math.max(0, event.touches[0].clientY - pullStartRef.current);
      const nextDistance = Math.min(92, distance * 0.48);
      pullDistanceRef.current = nextDistance;
      setPullDistance(nextDistance);
    };
    const onTouchEnd = () => {
      const shouldRefresh = pullDistanceRef.current >= 58 && !pullRefreshing;
      pullStartRef.current = null;
      if (!shouldRefresh) {
        pullDistanceRef.current = 0;
        setPullDistance(0);
        return;
      }
      setPullRefreshing(true);
      setPullOutcome("idle");
      setPullDistance(62);
      const startedAt = Date.now();
      void refresh()
        .then(() => setPullOutcome("success"))
        .catch(() => setPullOutcome("error"))
        .finally(() => {
          const minimumVisibleMs = 720;
          window.setTimeout(() => {
            pullDistanceRef.current = 0;
            setPullRefreshing(false);
            setPullDistance(0);
            window.setTimeout(() => setPullOutcome("idle"), 550);
          }, Math.max(0, minimumVisibleMs - (Date.now() - startedAt)));
        });
    };
    window.addEventListener("touchstart", onTouchStart, { passive: true });
    window.addEventListener("touchmove", onTouchMove, { passive: true });
    window.addEventListener("touchend", onTouchEnd, { passive: true });
    window.addEventListener("touchcancel", onTouchEnd, { passive: true });
    return () => {
      window.removeEventListener("touchstart", onTouchStart);
      window.removeEventListener("touchmove", onTouchMove);
      window.removeEventListener("touchend", onTouchEnd);
      window.removeEventListener("touchcancel", onTouchEnd);
    };
  }, [pullRefreshing, refresh]);

  const openBot = (botId: number) => {
    if (botStudioOpenRef.current) return;
    const url = new URL(window.location.href);
    url.searchParams.set("tab", "bots");
    url.searchParams.set("bot_id", String(botId));
    window.history.pushState({}, "", `${url.pathname}${url.search}${url.hash}`);
    setActiveTab("bots");
    setSelectedBotId(botId);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const closeBot = () => {
    const url = new URL(window.location.href);
    url.searchParams.delete("bot_id");
    window.history.pushState({}, "", `${url.pathname}${url.search}${url.hash}`);
    setSelectedBotId(null);
  };

  const handleBotDeleted = (botId: number) => {
    setBots((current) =>
      current.filter((bot) => Number(bot.bot_id ?? bot.id) !== botId),
    );
    window.dispatchEvent(
      new CustomEvent("ayserose:bot-deleted", {
        detail: { accountId, botId },
      }),
    );
    closeBot();
    void refresh();
  };

  const navigateTab = (tab: Parameters<typeof setActiveTab>[0]) => {
    if (selectedBotId) {
      const url = new URL(window.location.href);
      url.searchParams.delete("bot_id");
      window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
      setSelectedBotId(null);
    }
    setActiveTab(tab);
  };

  const openHomeFromBrand = () => {
    navigateTab("binance");
    window.requestAnimationFrame(() => {
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
  };

  const handleOpenTradeModal = (symbol: string, side: "BUY" | "SELL" = "BUY") => {
    setTradeRequest({ symbol, side });
  };

  useEffect(() => {
    if (isFirstLogin && wallet.keys_configured) completeFirstLogin();
  }, [completeFirstLogin, isFirstLogin, wallet.keys_configured]);

  const connectionHealthy =
    status === "live" ||
    (status === "fallback" && !error && lastUpdatedAt !== null);
  const connectionLabel = connectionHealthy
    ? "Bağlantı stabil"
    : status === "offline" || error
      ? "Bağlantı sorunu"
      : "Bağlanıyor";
  const connectionDotClass = connectionHealthy
    ? "bg-[#0ecb81] shadow-[0_0_8px_rgba(14,203,129,.8)]"
    : status === "offline" || error
      ? "bg-[#f6465d] shadow-[0_0_8px_rgba(246,70,93,.55)]"
      : "bg-[#f0b90b]";
  const desktopNavItems = ([
    ["binance", Coins, "Anasayfa"],
    ["bots", Cpu, "Botlar"],
    ["finance", Sliders, "Portföy"],
    ["contact", MessageSquare, "İletişim"],
    ["trade", Search, "Trade"],
  ] as const).filter(
    ([tab]) => wallet.is_test_account || (tab !== "finance" && tab !== "contact"),
  );
  const mobileNavItems = [
    ["binance", Coins, "Anasayfa"],
    ["bots", Cpu, "Botlar"],
    ["trade", Search, "Trade"],
  ] as const;

  return (
    <div className="min-h-screen bg-[#14151a] text-neutral-200 font-sans selection:bg-[#f0b90b] selection:text-neutral-900">
      <div className="sticky top-0 z-30 border-b border-white/8 bg-[#1b1c22]/95 pt-[max(0px,calc(env(safe-area-inset-top)-3px))] shadow-[0_12px_36px_rgba(0,0,0,.25)] backdrop-blur-xl">
        <div className="mx-auto flex h-14 max-w-7xl items-center justify-between gap-2 px-3 sm:h-16 sm:px-6 lg:px-8">
          <button
            type="button"
            onClick={openHomeFromBrand}
            aria-label="Ana sayfanın en üstüne dön"
            title="Ana sayfaya dön"
            className="group -ml-1 rounded-xl p-1 text-left transition hover:bg-white/[0.035] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-fuchsia-300/45"
          >
            <BrandMark />
          </button>

          <div className="flex min-w-0 items-center gap-1.5 sm:gap-2">
            <div className="flex min-w-0 items-center gap-1.5 text-right sm:gap-2">
              <button
                type="button"
                onClick={() => void refresh()}
                className="hidden items-center gap-1.5 rounded-full border border-neutral-700/70 bg-neutral-900/60 px-2.5 py-1 text-[10px] font-bold text-neutral-300 sm:flex"
                title={lastUpdatedAt ? `Son veri: ${new Date(lastUpdatedAt).toLocaleTimeString("tr-TR")}` : connectionLabel}
              >
                <span className={`h-1.5 w-1.5 rounded-full ${connectionDotClass}`} />
                {connectionLabel}
              </button>
              <div className="min-w-0">
                <span className="block max-w-16 truncate text-[11px] font-bold text-white min-[380px]:max-w-24 sm:max-w-44 sm:text-sm">
                  {displayName}
                </span>
              </div>
              <button
                type="button"
                onClick={() => navigateTab(activeTab === "settings" ? "binance" : "settings")}
                aria-label="Profil ve ayarları aç"
                aria-current={activeTab === "settings" ? "page" : undefined}
                title="Ayarlar"
                className={`grid h-11 w-11 shrink-0 place-items-center rounded-xl border transition ${
                  activeTab === "settings"
                    ? "border-fuchsia-300/25 bg-fuchsia-300/10 text-fuchsia-100"
                    : "border-white/8 bg-white/[0.035] text-neutral-400 hover:border-fuchsia-300/20 hover:text-fuchsia-100"
                }`}
              >
                <UserRound className="h-4 w-4" />
              </button>
            </div>
            <button
              onClick={logout}
              className="grid h-11 w-11 shrink-0 place-items-center rounded-xl border border-white/8 bg-white/[0.035] text-neutral-400 transition hover:border-red-300/20 hover:bg-red-300/[0.06] hover:text-red-200"
              title="Çıkış Yap"
              aria-label="Güvenli çıkış"
            >
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>

      <div
        aria-live="polite"
        className="pointer-events-none fixed left-1/2 z-50 -translate-x-1/2 transition-[top,opacity] duration-200 sm:hidden"
        style={{
          top: `calc(env(safe-area-inset-top) + ${Math.max(8, pullDistance - 30)}px)`,
          opacity: pullDistance > 8 || pullRefreshing || pullOutcome !== "idle" ? 1 : 0,
        }}
      >
        <span className="inline-flex items-center gap-2 rounded-full border border-fuchsia-300/20 bg-[#181920]/95 px-3 py-2 text-[10px] font-black text-fuchsia-100 shadow-2xl backdrop-blur-xl">
          {pullOutcome === "success" ? (
            <CheckCircle2 className="h-3.5 w-3.5 text-emerald-300" />
          ) : pullOutcome === "error" ? (
            <AlertCircle className="h-3.5 w-3.5 text-red-300" />
          ) : (
            <RefreshCw
              className={`h-3.5 w-3.5 ${pullRefreshing ? "animate-spin" : ""}`}
              style={{ transform: pullRefreshing ? undefined : `rotate(${pullDistance * 3}deg)` }}
            />
          )}
          {pullOutcome === "success"
            ? "Veriler güncellendi"
            : pullOutcome === "error"
              ? "Yenileme tamamlanamadı"
              : pullRefreshing
                ? "Veriler yenileniyor"
            : pullDistance >= 58
              ? "Yenilemek için bırak"
              : "Yenilemek için çek"}
        </span>
      </div>

      <div className="hidden border-b border-neutral-800 bg-[#16181d] sm:block">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-start sm:justify-center overflow-x-auto space-x-2 py-3 scrollbar-none">
            {desktopNavItems.map(([tab, Icon, label]) => (
              <button
                key={tab}
                onClick={() => navigateTab(tab)}
                className={`flex items-center space-x-2 px-4 py-2.5 rounded-lg text-sm font-semibold tracking-wide transition whitespace-nowrap ${
                  activeTab === tab
                    ? "bg-[#f0b90b] text-neutral-950 font-bold shadow-md"
                    : "text-neutral-400 hover:text-white hover:bg-neutral-800/40"
                }`}
              >
                <Icon className="w-4 h-4" />
                <span>{label}</span>
              </button>
            ))}
          </div>
        </div>
      </div>

      <main className="mx-auto max-w-7xl px-3 pb-32 pt-4 sm:px-6 sm:py-8 lg:px-8">
        {isFirstLogin && !wallet.keys_configured && (
          <section className="mb-5 flex flex-col gap-3 rounded-2xl border border-fuchsia-300/15 bg-gradient-to-r from-fuchsia-300/10 to-amber-300/5 p-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-sm font-black text-white">İlk kurulumunuzu tamamlayın</p>
              <p className="mt-1 text-xs leading-5 text-neutral-400">
                Canlı bakiye ve işlemler için Binance API bilgilerinizi güvenli ayarlardan
                tanımlayın.
              </p>
            </div>
            <button
              type="button"
              onClick={() => navigateTab("settings")}
              className="shrink-0 rounded-xl bg-white px-4 py-2.5 text-xs font-black text-neutral-950"
            >
              Güvenli ayarlara git
            </button>
          </section>
        )}
        {isAdmin && (
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
            className="mb-4 rounded-xl border border-[#f0b90b]/25 bg-[#f0b90b]/10 px-4 py-2 text-xs font-black text-[#f0b90b] hover:bg-[#f0b90b]/15"
          >
            ← Yönetim merkezine dön
          </button>
        )}
        {selectedBotId && (
          <button
            type="button"
            onClick={closeBot}
            className="mb-4 rounded-xl border border-white/10 bg-neutral-900 px-4 py-2 text-xs font-black text-neutral-300 hover:text-white"
          >
            ← Bot listesine dön
          </button>
        )}
        <Suspense fallback={<TabSkeleton />}>
          {selectedBotId && (
            <BotDetailPage
              botId={selectedBotId}
              accountId={accountId}
              onDeleted={handleBotDeleted}
            />
          )}
          <div
            hidden={selectedBotId !== null}
            aria-hidden={selectedBotId !== null || botStudioOpen || undefined}
            inert={botStudioOpen || undefined}
          >
          <TabSurface active={activeTab === "binance"}>
            <HomeTab
              bots={bots}
              wallet={wallet}
              prices={prices}
              onOpenTradeModal={handleOpenTradeModal}
              onApplyLeaderboard={handleApplyLeaderboard}
              isTestAccount={!!wallet.is_test_account}
              onOpenBot={openBot}
            />
          </TabSurface>
          <TabSurface active={activeTab === "trade"}>
            <TradeTab
              prices={prices}
              isActive={activeTab === "trade"}
              onOpenTradeModal={handleOpenTradeModal}
            />
          </TabSurface>
          <TabSurface active={activeTab === "bots"}>
            <BotsTab
              bots={bots}
              setBots={setBots}
              availableUSDT={wallet.available_usd}
              onOpenBot={openBot}
              onStudioOpenChange={setBotStudioOpen}
              templateDraft={botTemplateDraft}
            />
          </TabSurface>
          {retainedTabsRef.current.has("finance") && wallet.is_test_account && (
            <TabSurface active={activeTab === "finance"}><PortfolioTab /></TabSurface>
          )}
          {retainedTabsRef.current.has("contact") && wallet.is_test_account && (
            <TabSurface active={activeTab === "contact"}><ContactTab /></TabSurface>
          )}
          {retainedTabsRef.current.has("settings") && (
            <TabSurface active={activeTab === "settings"}><SettingsTab onLogout={logout} /></TabSurface>
          )}
          </div>
        </Suspense>
      </main>

      {tradeRequest && (
        <Suspense fallback={null}>
          <SpotOrderModal
            accountId={accountId}
            symbol={tradeRequest.symbol}
            side={tradeRequest.side}
            onClose={() => setTradeRequest(null)}
            onSuccess={async () => {
              setTradeRequest(null);
              window.dispatchEvent(
                new CustomEvent("ayserose:spot-order-updated"),
              );
              await refresh();
            }}
          />
        </Suspense>
      )}

      <UserPopup />

      <footer className="border-t border-neutral-900 bg-[#14151a] pb-32 pt-10 text-center text-neutral-500 sm:py-12">
        <div className="mx-auto max-w-7xl space-y-4 px-3 sm:px-4">
          <p className="whitespace-nowrap text-[8px] font-semibold leading-none text-neutral-400 min-[360px]:text-[9px] min-[390px]:text-[10px] sm:text-xs">
            <span className="font-semibold tracking-[0.04em] text-fuchsia-200 sm:tracking-[0.08em]">ayserose</span>{" "}
            Ömer Altın kuruluşudur. Tüm hakları saklıdır © 2026
          </p>
        </div>
      </footer>

      <nav
        aria-label="Mobil ana navigasyon"
        className="fixed inset-x-3 bottom-[max(.75rem,env(safe-area-inset-bottom))] z-40 grid grid-cols-3 rounded-[1.4rem] border border-fuchsia-300/15 bg-[#17181e]/95 p-1.5 shadow-[0_22px_70px_rgba(0,0,0,.68)] backdrop-blur-xl sm:hidden"
      >
        {mobileNavItems.map(([tab, Icon, label]) => (
          <button
            type="button"
            key={tab}
            onClick={() => navigateTab(tab)}
            aria-current={activeTab === tab ? "page" : undefined}
            className={`flex min-h-14 min-w-0 flex-col items-center justify-center gap-1 rounded-2xl px-2 py-2 text-[10px] font-black transition ${
              activeTab === tab
                ? "bg-gradient-to-br from-fuchsia-300/20 to-violet-300/10 text-white shadow-[inset_0_1px_0_rgba(255,255,255,.05)]"
                : "text-neutral-500 active:bg-white/5"
            }`}
          >
            <Icon className={`h-5 w-5 ${activeTab === tab ? "text-fuchsia-200" : ""}`} />
            <span className="max-w-full truncate">{label}</span>
          </button>
        ))}
      </nav>
    </div>
  );
}

function TabSurface({ active, children }: { active: boolean; children: React.ReactNode }) {
  return (
    <div hidden={!active} aria-hidden={!active || undefined}>
      {children}
    </div>
  );
}

function TabSkeleton() {
  return (
    <div className="animate-pulse space-y-5" aria-label="Bölüm yükleniyor">
      <div className="h-8 w-48 rounded-lg bg-neutral-800" />
      <div className="grid gap-4 md:grid-cols-3">
        <div className="h-32 rounded-2xl bg-neutral-900" />
        <div className="h-32 rounded-2xl bg-neutral-900" />
        <div className="h-32 rounded-2xl bg-neutral-900" />
      </div>
      <div className="h-72 rounded-2xl bg-neutral-900" />
    </div>
  );
}
