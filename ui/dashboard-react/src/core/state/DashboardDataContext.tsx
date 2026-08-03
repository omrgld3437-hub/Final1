import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { Dispatch, ReactNode, SetStateAction } from "react";
import type { Bot, WalletState } from "../../types";
import {
  DashboardTransport,
  type DashboardEnvelope,
  type DashboardTransportStatus,
} from "../realtime/dashboardTransport";
import {
  normalizeBots,
  normalizePrices,
  normalizeWallet,
} from "./dashboardNormalization";
import { accountUrl, apiRequest } from "../api/http";

const EMPTY_WALLET: WalletState = {
  total_usd: 0,
  free_usd: 0,
  locked_usd: 0,
  bot_locked_usd: 0,
  available_usd: 0,
  keys_configured: false,
  assets: [],
};

export interface DashboardDataValue {
  bots: Bot[];
  wallet: WalletState;
  prices: Record<string, { price?: number; change24h?: number; volume24h?: number }>;
  kpis: Record<string, unknown>;
  status: DashboardTransportStatus;
  lastUpdatedAt: number | null;
  error: string | null;
  setBots: Dispatch<SetStateAction<Bot[]>>;
  refresh: () => Promise<DashboardRefreshResult>;
}

export interface DashboardRefreshResult {
  wallet: "refreshed" | "current" | "stale" | "unavailable";
  completedAt: number;
}

const DashboardDataContext = createContext<DashboardDataValue | null>(null);
const BOT_CARD_CACHE_VERSION = 1;
const BOT_CARD_CACHE_MAX_AGE_MS = 24 * 60 * 60 * 1_000;

function botCardCacheKey(accountId: number): string {
  return `ayserose:bot-cards:v${BOT_CARD_CACHE_VERSION}:${accountId}`;
}

function readCachedBots(accountId: number): Bot[] {
  if (!accountId) return [];
  try {
    const raw = window.localStorage.getItem(botCardCacheKey(accountId));
    if (!raw) return [];
    const parsed = JSON.parse(raw) as { savedAt?: number; bots?: unknown };
    if (
      !Number.isFinite(parsed.savedAt) ||
      Date.now() - Number(parsed.savedAt) > BOT_CARD_CACHE_MAX_AGE_MS
    ) {
      window.localStorage.removeItem(botCardCacheKey(accountId));
      return [];
    }
    return normalizeBots(parsed.bots);
  } catch {
    return [];
  }
}

function writeCachedBots(accountId: number, bots: Bot[]): void {
  if (!accountId) return;
  try {
    window.localStorage.setItem(
      botCardCacheKey(accountId),
      JSON.stringify({ savedAt: Date.now(), bots }),
    );
  } catch {
    // Depolama kapalıysa canlı veri akışı normal şekilde devam eder.
  }
}

function envelopeData(envelope: DashboardEnvelope): Record<string, unknown> {
  if (envelope?.data && typeof envelope.data === "object") return envelope.data;
  return envelope as unknown as Record<string, unknown>;
}

export function DashboardDataProvider({
  accountId,
  children,
}: {
  accountId: number;
  children: ReactNode;
}) {
  const [bots, setBots] = useState<Bot[]>(() => readCachedBots(accountId));
  const [wallet, setWallet] = useState<WalletState>(EMPTY_WALLET);
  const [prices, setPrices] = useState<Record<string, { price?: number; change24h?: number; volume24h?: number }>>({});
  const [kpis, setKpis] = useState<Record<string, unknown>>({});
  const [status, setStatus] = useState<DashboardTransportStatus>("connecting");
  const [lastUpdatedAt, setLastUpdatedAt] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const transportRef = useRef<DashboardTransport | null>(null);
  const locallyDeletedBotIdsRef = useRef(new Set<number>());

  const applyEnvelope = useCallback((envelope: DashboardEnvelope) => {
    const data = envelopeData(envelope);
    const trimmed = new Set(envelope.meta?.trimmed_fields || []);
    if (data.prices && typeof data.prices === "object") {
      setPrices((current) =>
        normalizePrices(data.prices, current, trimmed.has("prices")),
      );
    }
    if (
      data.wallet &&
      typeof data.wallet === "object" &&
      !trimmed.has("wallet")
    ) {
      setWallet((current) => normalizeWallet(data.wallet, current));
    } else if (data.wallet_cached && typeof data.wallet_cached === "object") {
      setWallet((current) => {
        const walletStatus =
          data.wallet_status && typeof data.wallet_status === "object"
            ? data.wallet_status
            : {};
        return normalizeWallet(
          { ...(data.wallet_cached as object), ...(walletStatus as object) },
          current,
        );
      });
    }
    if (Array.isArray(data.bots) && !trimmed.has("bots")) {
      const nextBots = normalizeBots(data.bots).filter(
        (bot) => !locallyDeletedBotIdsRef.current.has(Number(bot.bot_id ?? bot.id)),
      );
      setBots(nextBots);
      writeCachedBots(accountId, nextBots);
    }
    if (data.kpis && typeof data.kpis === "object") {
      setKpis(data.kpis as Record<string, unknown>);
    }
    setLastUpdatedAt(Date.now());
    setError(null);
  }, [accountId]);

  useEffect(() => {
    const onBotDeleted = (event: Event) => {
      const detail = (event as CustomEvent<{ accountId?: number; botId?: number }>).detail;
      const deletedAccountId = Number(detail?.accountId);
      const deletedBotId = Number(detail?.botId);
      if (
        deletedAccountId !== accountId ||
        !Number.isInteger(deletedBotId) ||
        deletedBotId <= 0
      ) {
        return;
      }
      locallyDeletedBotIdsRef.current.add(deletedBotId);
      setBots((current) => {
        const next = current.filter(
          (bot) => Number(bot.bot_id ?? bot.id) !== deletedBotId,
        );
        writeCachedBots(accountId, next);
        return next;
      });
    };
    window.addEventListener("ayserose:bot-deleted", onBotDeleted);
    return () => window.removeEventListener("ayserose:bot-deleted", onBotDeleted);
  }, [accountId]);

  useEffect(() => {
    if (!accountId) return;
    locallyDeletedBotIdsRef.current.clear();
    setBots(readCachedBots(accountId));
    setWallet(EMPTY_WALLET);
    setPrices({});
    setKpis({});
    setLastUpdatedAt(null);
    setError(null);
    setStatus("connecting");
    const transport = new DashboardTransport(accountId, {
      onData: applyEnvelope,
      onStatus: setStatus,
      onError: (cause) => {
        const message = cause instanceof Error ? cause.message : "Canlı veri bağlantısı kurulamadı.";
        setError(message);
      },
    });
    transportRef.current = transport;
    transport.start();
    return () => {
      transport.stop(false);
      if (transportRef.current === transport) transportRef.current = null;
    };
  }, [accountId, applyEnvelope]);

  const refresh = useCallback(async (): Promise<DashboardRefreshResult> => {
    let walletState: DashboardRefreshResult["wallet"] = "unavailable";
    let walletError: unknown = null;
    try {
      const response = await apiRequest<{
        data?: {
          wallet_live?: unknown;
          skipped?: boolean;
          stale?: boolean;
        };
      }>(accountUrl("/api/home/wallet/refresh", accountId, { force: 1 }), {
        method: "POST",
        timeoutMs: 15_000,
        dedupe: false,
      });
      const payload = response?.data || {};
      if (payload.wallet_live && typeof payload.wallet_live === "object") {
        setWallet((current) => normalizeWallet(payload.wallet_live, current));
      }
      walletState = payload.stale
        ? "stale"
        : payload.skipped
          ? "current"
          : "refreshed";
    } catch (cause) {
      walletError = cause;
    }

    await transportRef.current?.refresh();
    const completedAt = Date.now();
    window.dispatchEvent(
      new CustomEvent("ayserose:manual-refresh", {
        detail: { accountId, completedAt },
      }),
    );
    if (walletError) throw walletError;
    if (walletState === "stale") {
      throw new Error("Cüzdanın canlı verisi yenilenemedi; son başarılı değerler korunuyor.");
    }
    return { wallet: walletState, completedAt };
  }, [accountId]);

  const value = useMemo<DashboardDataValue>(
    () => ({
      bots,
      wallet,
      prices,
      kpis,
      status,
      lastUpdatedAt,
      error,
      setBots,
      refresh,
    }),
    [bots, wallet, prices, kpis, status, lastUpdatedAt, error, refresh],
  );

  return (
    <DashboardDataContext.Provider value={value}>
      {children}
    </DashboardDataContext.Provider>
  );
}

export function useDashboardData(): DashboardDataValue {
  const value = useContext(DashboardDataContext);
  if (!value) throw new Error("useDashboardData must be used within DashboardDataProvider");
  return value;
}
