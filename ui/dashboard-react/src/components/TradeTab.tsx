import {
  ArrowDownLeft,
  ArrowUpRight,
  Clock3,
  ListFilter,
  LoaderCircle,
  Search,
  Sparkles,
  Star,
  XCircle,
} from "lucide-react";
import {
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent,
} from "react";
import CoinLogo, {
  splitTradingSymbol,
} from "./coin/CoinLogo";
import { useDashboard } from "../context/DashboardContext";
import { apiFetch } from "../lib/api";
import LiveValue from "./live/LiveValue";

interface MarketCoin {
  symbol: string;
  lastPrice?: unknown;
  price?: unknown;
  priceChangePercent?: unknown;
  volume?: unknown;
  quoteVolume?: unknown;
}

interface CoinListResponse {
  coins?: unknown[];
  symbols?: unknown[];
}

interface OpenOrder {
  orderId?: string | number;
  symbol?: string;
  side?: string;
  type?: string;
  price?: string | number;
  origQty?: string | number;
  executedQty?: string | number;
  status?: string;
  time?: string | number;
  updateTime?: string | number;
}

interface OpenOrdersResponse {
  orders?: OpenOrder[];
  data_status?: string;
}

interface TradeTabProps {
  prices: Record<string, { price?: number; change24h?: number; volume24h?: number }>;
  isActive: boolean;
  onOpenTradeModal: (symbol: string, side: "BUY" | "SELL") => void;
}

const PRICE_FORMAT = new Intl.NumberFormat("tr-TR", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 8,
});
const COMPACT_FORMAT = new Intl.NumberFormat("tr-TR", {
  notation: "compact",
  maximumFractionDigits: 1,
});
const CHANGE_FORMAT = new Intl.NumberFormat("tr-TR", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const MAX_SEARCH_RESULTS = 120;

type PriceMap = TradeTabProps["prices"];

/** Partial market snapshots must never erase the last complete value on screen. */
function mergePriceMaps(base: PriceMap, incoming: PriceMap): PriceMap {
  const merged = { ...base };
  for (const [rawSymbol, rawValue] of Object.entries(incoming || {})) {
    const symbol = normalizeSymbol(rawSymbol);
    if (!symbol || !rawValue || typeof rawValue !== "object") continue;
    const previous = merged[symbol] || {};
    const price = finite(rawValue.price);
    const change24h = finite(rawValue.change24h);
    const volume24h = finite(rawValue.volume24h);
    merged[symbol] = {
      ...previous,
      ...(price !== null ? { price } : {}),
      ...(change24h !== null ? { change24h } : {}),
      ...(volume24h !== null ? { volume24h } : {}),
    };
  }
  return merged;
}

function finite(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function normalizeSymbol(value: unknown): string {
  return String(value ?? "")
    .trim()
    .toUpperCase()
    .replace(/[^A-Z0-9]/g, "");
}

function normalizeCoin(value: unknown): MarketCoin | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Record<string, unknown>;
  const symbol = normalizeSymbol(raw.symbol);
  if (!symbol) return null;
  return {
    symbol,
    lastPrice: raw.lastPrice ?? raw.price,
    price: raw.price ?? raw.lastPrice,
    priceChangePercent: raw.priceChangePercent ?? raw.change24h,
    volume: raw.volume ?? raw.volume24h,
    quoteVolume: raw.quoteVolume ?? raw.quoteVolume24h,
  };
}

function marketValues(
  coin: MarketCoin,
  prices: TradeTabProps["prices"],
): { price: number | null; change: number | null; volume: number | null } {
  const live = prices[coin.symbol];
  const price = finite(live?.price) ?? finite(coin.lastPrice) ?? finite(coin.price);
  const change =
    finite(live?.change24h) ?? finite(coin.priceChangePercent);
  const quoteVolume =
    finite(coin.quoteVolume) ??
    ((finite(live?.volume24h) ?? finite(coin.volume) ?? 0) * (price ?? 0) || null);
  return { price, change, volume: quoteVolume };
}

function formatPrice(value: number | null): string {
  return value === null ? "—" : PRICE_FORMAT.format(value);
}

function formatChange(value: number | null): string {
  if (value === null) return "—";
  return `${value > 0 ? "+" : ""}${CHANGE_FORMAT.format(value)}%`;
}

function formatVolume(value: number | null, quote: string): string {
  return value === null ? "—" : `${COMPACT_FORMAT.format(value)} ${quote}`;
}

function formatOrderTime(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  const numeric = Number(value);
  const date = Number.isFinite(numeric)
    ? new Date(numeric)
    : new Date(String(value));
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("tr-TR", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(date);
}

function FavoriteMarketSnapshot({
  coin,
  values,
}: {
  coin: MarketCoin;
  values: ReturnType<typeof marketValues>;
}) {
  const pair = splitTradingSymbol(coin.symbol);
  return (
    <div className="flex h-full items-center gap-3">
      <CoinLogo symbol={coin.symbol} size={48} eager />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-black text-white">{pair.label}</p>
        <p className="mt-1 font-mono text-lg font-black text-white">
          {values.price === null ? (
            <span
              className="block h-6 w-24 animate-pulse rounded-lg bg-white/6"
              aria-label="Canlı fiyat yükleniyor"
            />
          ) : (
            <LiveValue value={values.price}>
              {formatPrice(values.price)} {pair.quote}
            </LiveValue>
          )}
        </p>
      </div>
      {values.change === null ? (
        <span
          className="h-7 w-16 animate-pulse rounded-full bg-white/6"
          aria-label="24 saatlik değişim yükleniyor"
        />
      ) : (
        <span
          className={`rounded-full px-2.5 py-1 text-xs font-black ${
            values.change >= 0
              ? "bg-emerald-400/10 text-emerald-300"
              : "bg-red-400/10 text-red-300"
          }`}
        >
          <LiveValue value={values.change} toneBySign>
            {formatChange(values.change)}
          </LiveValue>
        </span>
      )}
    </div>
  );
}

export default function TradeTab({
  prices,
  isActive,
  onOpenTradeModal,
}: TradeTabProps) {
  const { accountId } = useDashboard();
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search);
  const [coins, setCoins] = useState<MarketCoin[]>([]);
  const [favorites, setFavorites] = useState<string[]>([]);
  const [favoritePrices, setFavoritePrices] = useState<TradeTabProps["prices"]>({});
  const [searchPrices, setSearchPrices] = useState<TradeTabProps["prices"]>({});
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [favoriteError, setFavoriteError] = useState("");
  const [favoriteSaving, setFavoriteSaving] = useState<string | null>(null);
  const [openOrders, setOpenOrders] = useState<OpenOrder[]>([]);
  const [openOrderError, setOpenOrderError] = useState("");
  const [cancellingOrderId, setCancellingOrderId] = useState<string | null>(null);
  const hiddenOrderIdsRef = useRef(new Map<string, number>());
  const pendingCancellationRef = useRef<OpenOrder | null>(null);
  const emptyOpenOrderPollsRef = useRef(0);
  const [reloadKey, setReloadKey] = useState(0);
  const [featuredFavorite, setFeaturedFavorite] = useState<{
    currentIndex: number;
    previousIndex: number | null;
    transitionId: number;
  }>({ currentIndex: 0, previousIndex: null, transitionId: 0 });

  useEffect(() => {
    const onManualRefresh = () => setReloadKey((value) => value + 1);
    window.addEventListener("ayserose:manual-refresh", onManualRefresh);
    window.addEventListener("ayserose:spot-order-updated", onManualRefresh);
    return () => {
      window.removeEventListener("ayserose:manual-refresh", onManualRefresh);
      window.removeEventListener("ayserose:spot-order-updated", onManualRefresh);
    };
  }, []);

  useEffect(() => {
    hiddenOrderIdsRef.current.clear();
    pendingCancellationRef.current = null;
    emptyOpenOrderPollsRef.current = 0;
    setOpenOrders([]);
    setOpenOrderError("");
    setCancellingOrderId(null);
  }, [accountId]);

  useEffect(() => {
    if (!accountId || !isActive) return;
    let cancelled = false;
    let inFlight = false;
    const loadOpenOrders = async () => {
      if (inFlight || document.visibilityState !== "visible") return;
      inFlight = true;
      try {
        const response = await apiFetch<OpenOrdersResponse>(
          `/api/binance/open-orders?account_id=${accountId}`,
          { dedupe: false },
        );
        if (cancelled) return;
        const now = Date.now();
        for (const [orderId, hiddenUntil] of hiddenOrderIdsRef.current) {
          if (hiddenUntil <= now) hiddenOrderIdsRef.current.delete(orderId);
        }
        const orders = Array.isArray(response.orders)
          ? response.orders.filter(
              (order) =>
                order &&
                typeof order === "object" &&
                ["NEW", "PARTIALLY_FILLED"].includes(
                  String(order.status || "NEW").toUpperCase(),
                ) &&
                !hiddenOrderIdsRef.current.has(String(order.orderId ?? "")),
            )
          : [];
        const pendingCancellation = pendingCancellationRef.current;
        if (
          pendingCancellation &&
          !orders.some(
            (order) =>
              String(order.orderId ?? "") ===
              String(pendingCancellation.orderId ?? ""),
          )
        ) {
          orders.unshift(pendingCancellation);
        }
        orders.sort(
          (left, right) =>
            finite(right.time ?? right.updateTime)! -
            finite(left.time ?? left.updateTime)!,
        );
        setOpenOrders((current) => {
          if (orders.length > 0) {
            emptyOpenOrderPollsRef.current = 0;
            return orders;
          }
          if (response.data_status === "stale") return current;
          emptyOpenOrderPollsRef.current += 1;
          if (current.length > 0 && emptyOpenOrderPollsRef.current < 3) {
            return current;
          }
          return [];
        });
        setOpenOrderError("");
      } catch (error) {
        if (!cancelled && openOrders.length) {
          setOpenOrderError(
            error instanceof Error
              ? error.message
              : "Bekleyen emirler yenilenemedi.",
          );
        }
      } finally {
        inFlight = false;
      }
    };
    void loadOpenOrders();
    const timer = window.setInterval(loadOpenOrders, 3_000);
    const onVisible = () => {
      if (document.visibilityState === "visible") void loadOpenOrders();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [accountId, isActive, reloadKey]);

  useEffect(() => {
    let cancelled = false;
    setLoading(coins.length === 0);
    setLoadError("");
    setFavoriteError("");

    const loadWorkspace = async () => {
      const [favoriteResult, marketResult] = await Promise.allSettled([
        apiFetch<{ symbols?: string[] }>(
          `/api/accounts/${accountId}/spot-favorites`,
        ),
        apiFetch<CoinListResponse>("/api/data/coin-list?scope=all"),
      ]);
      if (cancelled) return;

      if (favoriteResult.status === "fulfilled") {
        setFavorites(
          Array.isArray(favoriteResult.value.symbols)
            ? [...new Set(favoriteResult.value.symbols.map(normalizeSymbol).filter(Boolean))]
            : [],
        );
      } else {
        setFavoriteError("Favoriler şu anda yenilenemedi; son görünüm korunuyor.");
      }

      if (marketResult.status === "fulfilled") {
        const coinMap = new Map<string, MarketCoin>();
        for (const candidate of marketResult.value.coins || []) {
          const coin = normalizeCoin(candidate);
          if (coin) coinMap.set(coin.symbol, coin);
        }
        for (const candidate of marketResult.value.symbols || []) {
          const symbol = normalizeSymbol(candidate);
          if (symbol && !coinMap.has(symbol)) coinMap.set(symbol, { symbol });
        }
        const nextCoins = [...coinMap.values()];
        if (nextCoins.length) setCoins(nextCoins);
        else if (coins.length === 0) {
          setLoadError("Piyasa listesi henüz hazır değil. Yeniden bağlanabilirsiniz.");
        }
      } else if (coins.length === 0) {
        setLoadError(
          marketResult.reason instanceof Error
            ? marketResult.reason.message
            : "Piyasa listesi yüklenemedi.",
        );
      }
      setLoading(false);
    };

    void loadWorkspace();

    return () => {
      cancelled = true;
    };
  }, [accountId, reloadKey]);

  useEffect(() => {
    if (!favorites.length) {
      setFavoritePrices({});
      return;
    }
    if (!isActive) return;
    let cancelled = false;
    let inFlight = false;
    const symbols = favorites.join(",");
    const loadFavoritePrices = async () => {
      if (inFlight || document.visibilityState !== "visible") return;
      inFlight = true;
      try {
        const response = await apiFetch<TradeTabProps["prices"]>(
          `/api/data/prices?slim=1&symbols=${encodeURIComponent(symbols)}`,
          { dedupe: false },
        );
        if (!cancelled && response && typeof response === "object") {
          setFavoritePrices((current) => mergePriceMaps(current, response));
        }
      } catch {
        // Ana canlı fiyat akışı çalışmaya devam eder; bu yalnız hızlı favori desteğidir.
      } finally {
        inFlight = false;
      }
    };
    void loadFavoritePrices();
    const timer = window.setInterval(loadFavoritePrices, 1_000);
    const onVisible = () => {
      if (document.visibilityState === "visible") void loadFavoritePrices();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [favorites, isActive, reloadKey]);

  useEffect(() => {
    setFeaturedFavorite({
      currentIndex: 0,
      previousIndex: null,
      transitionId: 0,
    });
    if (!isActive || favorites.length <= 1) return;
    const timer = window.setInterval(() => {
      if (document.visibilityState !== "visible") return;
      setFeaturedFavorite((current) => ({
        currentIndex: (current.currentIndex + 1) % favorites.length,
        previousIndex: current.currentIndex,
        transitionId: current.transitionId + 1,
      }));
    }, 1_500);
    return () => window.clearInterval(timer);
  }, [favorites, isActive]);

  const effectivePrices = useMemo(() => {
    return mergePriceMaps(mergePriceMaps(prices, searchPrices), favoritePrices);
  }, [favoritePrices, prices, searchPrices]);

  const marketCoins = useMemo(() => {
    const coinMap = new Map<string, MarketCoin>();
    for (const coin of coins) coinMap.set(coin.symbol, coin);
    for (const symbol of favorites) {
      if (!coinMap.has(symbol)) coinMap.set(symbol, { symbol });
    }
    for (const rawSymbol of Object.keys(effectivePrices)) {
      const symbol = normalizeSymbol(rawSymbol);
      if (symbol && !coinMap.has(symbol)) coinMap.set(symbol, { symbol });
    }
    return [...coinMap.values()];
  }, [coins, effectivePrices, favorites]);

  const coinBySymbol = useMemo(
    () => new Map(marketCoins.map((coin) => [coin.symbol, coin] as const)),
    [marketCoins],
  );

  const searching = Boolean(search.trim());
  const searchSettling = search.trim() !== deferredSearch.trim();
  const visibleCoins = useMemo(() => {
    const query = deferredSearch.trim().toUpperCase();
    if (!query) {
      return favorites.map(
        (symbol) => coinBySymbol.get(symbol) || { symbol },
      );
    }
    const compact = query.replace(/[^A-Z0-9]/g, "");
    return marketCoins
      .filter((coin) => {
        const pair = splitTradingSymbol(coin.symbol);
        return (
          pair.base.includes(compact) ||
          pair.quote.includes(compact) ||
          coin.symbol.startsWith(compact)
        );
      })
      .slice(0, MAX_SEARCH_RESULTS);
  }, [coinBySymbol, deferredSearch, favorites, marketCoins]);

  const searchedSymbolKey = searching
    ? visibleCoins.map((coin) => coin.symbol).join(",")
    : "";

  useEffect(() => {
    if (!searchedSymbolKey || !isActive) return;
    let cancelled = false;
    let inFlight = false;
    const loadSearchedPrices = async () => {
      if (inFlight || document.visibilityState !== "visible") return;
      inFlight = true;
      try {
        const response = await apiFetch<TradeTabProps["prices"]>(
          `/api/data/prices?slim=1&symbols=${encodeURIComponent(searchedSymbolKey)}`,
          { dedupe: false },
        );
        if (!cancelled && response && typeof response === "object") {
          setSearchPrices((current) => mergePriceMaps(current, response));
        }
      } catch {
        // Arama listesi mevcut son değerleri göstermeye devam eder.
      } finally {
        inFlight = false;
      }
    };
    void loadSearchedPrices();
    const timer = window.setInterval(loadSearchedPrices, 1_000);
    const onVisible = () => {
      if (document.visibilityState === "visible") void loadSearchedPrices();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [isActive, searchedSymbolKey, reloadKey]);

  const handleToggleFavorite = async (
    event: MouseEvent<HTMLButtonElement>,
    symbol: string,
  ) => {
    event.stopPropagation();
    if (favoriteSaving) return;
    const previous = favorites;
    const next = favorites.includes(symbol)
      ? favorites.filter((favorite) => favorite !== symbol)
      : [...favorites, symbol];
    setFavorites(next);
    setFavoriteSaving(symbol);
    setFavoriteError("");
    try {
      const response = await apiFetch<{ ok?: boolean; symbols?: string[] }>(
        `/api/accounts/${accountId}/spot-favorites`,
        {
          method: "PUT",
          body: JSON.stringify({ symbols: next }),
        },
      );
      if (!response?.ok) throw new Error("Favoriler kaydedilemedi.");
      if (Array.isArray(response.symbols)) {
        setFavorites(response.symbols.map(normalizeSymbol).filter(Boolean));
      }
    } catch (error) {
      setFavorites(previous);
      setFavoriteError(
        error instanceof Error ? error.message : "Favoriler kaydedilemedi.",
      );
    } finally {
      setFavoriteSaving(null);
    }
  };

  const handleCancelOrder = async (order: OpenOrder) => {
    const orderId = String(order.orderId ?? "");
    const symbol = normalizeSymbol(order.symbol);
    if (!orderId || !symbol || cancellingOrderId) return;
    pendingCancellationRef.current = order;
    setCancellingOrderId(orderId);
    setOpenOrderError("");
    try {
      const query = new URLSearchParams({
        account_id: String(accountId),
        symbol,
        order_id: orderId,
      });
      const [response] = await Promise.all([
        apiFetch<{ success?: boolean; message?: string }>(
          `/api/binance/order?${query}`,
          { method: "DELETE" },
        ),
        new Promise<void>((resolve) => window.setTimeout(resolve, 1_000)),
      ]);
      if (response?.success === false) {
        throw new Error(response.message || "Emir iptal edilemedi.");
      }
      hiddenOrderIdsRef.current.set(orderId, Date.now() + 10_000);
      pendingCancellationRef.current = null;
      setOpenOrders((current) =>
        current.filter(
          (candidate) => String(candidate.orderId ?? "") !== orderId,
        ),
      );
      window.dispatchEvent(new CustomEvent("ayserose:manual-refresh"));
    } catch (error) {
      pendingCancellationRef.current = null;
      setOpenOrderError(
        error instanceof Error ? error.message : "Emir iptal edilemedi.",
      );
    } finally {
      setCancellingOrderId(null);
    }
  };

  const featuredFavoriteSymbol = favorites.length
    ? favorites[featuredFavorite.currentIndex % favorites.length]
    : null;
  const featuredCoin = featuredFavoriteSymbol
    ? coinBySymbol.get(featuredFavoriteSymbol) || { symbol: featuredFavoriteSymbol }
    : null;
  const featuredValues = featuredCoin
    ? marketValues(featuredCoin, effectivePrices)
    : null;
  const previousFavoriteSymbol =
    featuredFavorite.previousIndex !== null && favorites.length > 1
      ? favorites[featuredFavorite.previousIndex % favorites.length]
      : null;
  const previousCoin = previousFavoriteSymbol
    ? coinBySymbol.get(previousFavoriteSymbol) || { symbol: previousFavoriteSymbol }
    : null;
  const previousValues = previousCoin
    ? marketValues(previousCoin, effectivePrices)
    : null;

  return (
    <section className="mx-auto max-w-6xl space-y-5">
      <header className="trade-hero relative overflow-hidden rounded-[1.75rem] border border-fuchsia-300/15 bg-[#191a21] p-5 sm:p-7">
        <div className="relative z-10 grid gap-6 lg:grid-cols-[1fr_330px] lg:items-end">
          <div>
            <p className="flex items-center gap-2 text-[11px] font-black uppercase tracking-[0.22em] text-fuchsia-200">
              <Sparkles className="h-4 w-4" />
              Spot işlem merkezi
            </p>
            <h1 className="mt-3 max-w-2xl text-3xl font-black tracking-[-0.035em] text-white sm:text-4xl">
              Piyasayı ara. Favorilerini izle. İşlemi tek yüzeyde tamamla.
            </h1>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-neutral-400">
              Favorilerini canlı izle; Binance spot piyasalarında aradığın çifte
              anında ulaş ve işlemini güvenle tamamla.
            </p>
          </div>

          <div className="relative overflow-hidden rounded-2xl border border-white/8 bg-black/20 p-4 backdrop-blur">
            {featuredCoin && featuredValues ? (
              <>
                <div className="mb-2 flex items-center justify-between gap-3 text-[9px] font-black uppercase tracking-[0.18em] text-neutral-500">
                  <span>Favori akışı</span>
                  <span className="tabular-nums text-fuchsia-200/80">
                    {(featuredFavorite.currentIndex % favorites.length) + 1} / {favorites.length}
                  </span>
                </div>
                <div className="relative min-h-[3.25rem]" aria-label="Sıradaki favori piyasa">
                  {previousCoin && previousValues && (
                    <div
                      key={`favorite-out-${featuredFavorite.transitionId}`}
                      className="trade-favorite-exit absolute inset-0"
                      aria-hidden="true"
                    >
                      <FavoriteMarketSnapshot coin={previousCoin} values={previousValues} />
                    </div>
                  )}
                  <div
                    key={`favorite-in-${featuredCoin.symbol}-${featuredFavorite.transitionId}`}
                    className="trade-favorite-enter absolute inset-0"
                  >
                    <FavoriteMarketSnapshot coin={featuredCoin} values={featuredValues} />
                  </div>
                </div>
              </>
            ) : (
              <div className="flex items-center gap-3 text-sm text-neutral-400">
                <Star className="h-5 w-5 text-fuchsia-200" />
                İlk favorini seçtiğinde hızlı piyasa özeti burada görünür.
              </div>
            )}
          </div>
        </div>
      </header>

      {openOrders.length > 0 && (
        <PendingOrdersCard
          orders={openOrders}
          cancellingOrderId={cancellingOrderId}
          error={openOrderError}
          onCancel={handleCancelOrder}
        />
      )}

      <div className="overflow-hidden rounded-[1.75rem] border border-white/8 bg-[#191a20] shadow-[0_24px_80px_rgba(0,0,0,.25)]">
        <div className="border-b border-white/8 p-4 sm:p-5">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
            <label className="relative block min-w-0 flex-1">
              <span className="sr-only">İşlem çifti ara</span>
              <Search className="pointer-events-none absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-fuchsia-200" />
              <input
                type="search"
                autoComplete="off"
                placeholder="BTCUSDT, ETHBTC veya SOLETH ara"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                className="h-13 w-full rounded-2xl border border-white/10 bg-black/20 pl-12 pr-14 text-sm font-semibold text-white outline-none transition placeholder:text-neutral-600 hover:border-white/15 focus:border-fuchsia-300/40 focus:ring-4 focus:ring-fuchsia-300/5"
              />
              <kbd className="pointer-events-none absolute right-4 top-1/2 hidden -translate-y-1/2 rounded-md border border-white/10 bg-white/5 px-2 py-1 text-[10px] font-black text-neutral-500 sm:block">
                ARA
              </kbd>
            </label>
            <div className="flex items-center gap-2 rounded-xl border border-white/8 bg-white/[0.025] px-3 py-2 text-xs font-bold text-neutral-400">
              {searching ? (
                <ListFilter className="h-4 w-4 text-sky-300" />
              ) : (
                <Star className="h-4 w-4 fill-fuchsia-200 text-fuchsia-200" />
              )}
              {searching
                ? searchSettling || loading
                  ? "Aranıyor…"
                  : `${visibleCoins.length} eşleşme`
                : `${favorites.length} favori`}
            </div>
          </div>
          <div className="mt-4 flex items-center justify-between gap-3">
            <div>
              <h2 className="text-sm font-black text-white">
                {searching ? "Arama sonuçları" : "Favori piyasaların"}
              </h2>
              {searching && (
                <p className="mt-1 text-xs text-neutral-500">
                  Performans için ilk {MAX_SEARCH_RESULTS} eşleşme gösterilir.
                </p>
              )}
            </div>
          </div>
          {favoriteError && (
            <p
              role="status"
              className="mt-4 rounded-xl border border-red-400/20 bg-red-400/5 px-3 py-2 text-xs text-red-200"
            >
              {favoriteError}
            </p>
          )}
          {loadError && visibleCoins.length > 0 && (
            <p
              role="status"
              className="mt-4 rounded-xl border border-amber-300/15 bg-amber-300/5 px-3 py-2 text-xs text-amber-100/80"
            >
              Genel piyasa kataloğu arka planda yenileniyor; favorilerin canlı
              fiyat akışıyla gösterilmeye devam ediyor.
            </p>
          )}
        </div>

        {loading && coins.length === 0 ? (
          <div className="grid min-h-72 place-items-center">
            <div className="flex items-center gap-2 text-sm font-semibold text-neutral-400">
              <LoaderCircle className="h-4 w-4 animate-spin text-fuchsia-200" />
              Piyasa çalışma alanı hazırlanıyor…
            </div>
          </div>
        ) : loadError && visibleCoins.length === 0 ? (
          <div className="grid min-h-72 place-items-center p-6 text-center">
            <div>
              <p className="font-black text-white">Piyasa listesi alınamadı</p>
              <p className="mt-2 max-w-md text-sm leading-6 text-neutral-500">
                {loadError}
              </p>
              <button
                type="button"
                onClick={() => setReloadKey((value) => value + 1)}
                className="mt-5 rounded-xl border border-fuchsia-200/20 bg-fuchsia-200/10 px-4 py-2.5 text-xs font-black text-fuchsia-100"
              >
                Yeniden bağlan
              </button>
            </div>
          </div>
        ) : searching && searchSettling ? (
          <div className="grid min-h-72 place-items-center">
            <div className="flex items-center gap-2 text-sm font-semibold text-neutral-400">
              <LoaderCircle className="h-4 w-4 animate-spin text-fuchsia-200" />
              Pariteler aranıyor…
            </div>
          </div>
        ) : visibleCoins.length === 0 ? (
          <div className="grid min-h-72 place-items-center p-6 text-center">
            <div className="max-w-md">
              <span className="mx-auto grid h-14 w-14 place-items-center rounded-2xl border border-fuchsia-300/15 bg-fuchsia-300/5">
                <Star className="h-6 w-6 text-fuchsia-200" />
              </span>
              <p className="mt-4 font-black text-white">
                {searching ? "Eşleşen parite bulunamadı" : "Henüz favorin yok"}
              </p>
              <p className="mt-2 text-sm leading-6 text-neutral-500">
                {searching
                  ? "Sembolü farklı yazarak yeniden deneyebilirsin."
                  : "Yukarıdaki aramada bir parite bulup yıldız simgesine dokun; boş görünümde yalnız seçtiklerin kalır."}
              </p>
            </div>
          </div>
        ) : (
          <>
            <div className="hidden overflow-x-auto md:block">
              <table className="w-full text-left text-sm">
                <caption className="sr-only">
                  Spot işlem çiftleri, fiyatları ve hızlı işlem seçenekleri
                </caption>
                <thead className="bg-black/15 text-[10px] font-black uppercase tracking-[0.16em] text-neutral-600">
                  <tr>
                    <th scope="col" className="w-16 px-5 py-3 text-center">
                      Favori
                    </th>
                    <th scope="col" className="px-3 py-3">
                      Piyasa
                    </th>
                    <th scope="col" className="px-3 py-3 text-right">
                      Son fiyat
                    </th>
                    <th scope="col" className="px-3 py-3 text-right">
                      24 saat
                    </th>
                    <th scope="col" className="px-3 py-3 text-right">
                      Hacim
                    </th>
                    <th scope="col" className="px-5 py-3 text-right">
                      İşlem
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/[0.055]">
                  {visibleCoins.map((coin) => (
                    <MarketTableRow
                      key={coin.symbol}
                      coin={coin}
                      values={marketValues(coin, effectivePrices)}
                      favorite={favorites.includes(coin.symbol)}
                      saving={favoriteSaving === coin.symbol}
                      onToggleFavorite={handleToggleFavorite}
                      onTrade={onOpenTradeModal}
                    />
                  ))}
                </tbody>
              </table>
            </div>

            <div className="grid gap-3 p-3 md:hidden">
              {visibleCoins.map((coin) => (
                <MarketMobileCard
                  key={coin.symbol}
                  coin={coin}
                  values={marketValues(coin, effectivePrices)}
                  favorite={favorites.includes(coin.symbol)}
                  saving={favoriteSaving === coin.symbol}
                  onToggleFavorite={handleToggleFavorite}
                  onTrade={onOpenTradeModal}
                />
              ))}
            </div>
          </>
        )}
      </div>
    </section>
  );
}

function PendingOrdersCard({
  orders,
  cancellingOrderId,
  error,
  onCancel,
}: {
  orders: OpenOrder[];
  cancellingOrderId: string | null;
  error: string;
  onCancel: (order: OpenOrder) => void;
}) {
  return (
    <section
      aria-label="Bekleyen limit emirleri"
      className="overflow-hidden rounded-[1.75rem] border border-amber-300/15 bg-[radial-gradient(circle_at_top_right,rgba(251,191,36,.08),transparent_42%),#191a20]"
    >
      <header className="flex items-center justify-between gap-3 border-b border-white/8 px-4 py-4 sm:px-5">
        <div className="flex min-w-0 items-center gap-3">
          <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-amber-300/15 bg-amber-300/[0.07] text-amber-200">
            <Clock3 className="h-4 w-4" />
          </span>
          <div className="min-w-0">
            <p className="text-[9px] font-black uppercase tracking-[0.18em] text-amber-200">
              Aktif limit emirleri
            </p>
            <h2 className="mt-0.5 truncate text-base font-black text-white">
              Bekleyen emirler
            </h2>
          </div>
        </div>
        <span className="shrink-0 rounded-full border border-amber-300/15 bg-amber-300/[0.06] px-2.5 py-1.5 text-[10px] font-black text-amber-100">
          {orders.length} aktif
        </span>
      </header>

      {error && (
        <p className="border-b border-amber-300/10 px-4 py-2.5 text-[11px] text-amber-100 sm:px-5">
          {error}
        </p>
      )}

      <div className="divide-y divide-white/[0.055]">
        {orders.map((order, index) => {
          const symbol = normalizeSymbol(order.symbol);
          const pair = splitTradingSymbol(symbol);
          const side = String(order.side || "").toUpperCase();
          const buy = side === "BUY";
          const price = finite(order.price);
          const originalQty = finite(order.origQty) ?? 0;
          const executedQty = finite(order.executedQty) ?? 0;
          const remainingQty = Math.max(0, originalQty - executedQty);
          const total = price === null ? null : remainingQty * price;
          const orderId = String(order.orderId ?? `${symbol}-${index}`);
          const cancelling = cancellingOrderId === orderId;
          return (
            <article
              key={orderId}
              className="grid gap-3 px-4 py-3.5 sm:grid-cols-[minmax(180px,1.2fr)_repeat(3,minmax(110px,.75fr))_auto] sm:items-center sm:px-5"
            >
              <div className="flex min-w-0 items-center gap-3">
                <CoinLogo symbol={symbol} size={38} />
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <p className="truncate text-sm font-black text-white">
                      {pair.label}
                    </p>
                    <span
                      className={`rounded-full px-2 py-1 text-[9px] font-black ${
                        buy
                          ? "bg-emerald-300/[0.08] text-emerald-200"
                          : "bg-red-300/[0.08] text-red-200"
                      }`}
                    >
                      {buy ? "ALIŞ" : "SATIŞ"}
                    </span>
                  </div>
                  <p className="mt-1 text-[10px] font-semibold text-neutral-600">
                    {formatOrderTime(order.time ?? order.updateTime)}
                  </p>
                </div>
              </div>

              <PendingOrderValue
                label="Limit fiyatı"
                value={
                  price === null
                    ? "—"
                    : `${formatPrice(price)} ${pair.quote}`
                }
              />
              <PendingOrderValue
                label="Kalan miktar"
                value={`${PRICE_FORMAT.format(remainingQty)} ${pair.base}`}
              />
              <PendingOrderValue
                label="Emir toplamı"
                value={
                  total === null
                    ? "—"
                    : `${PRICE_FORMAT.format(total)} ${pair.quote}`
                }
              />

              <button
                type="button"
                disabled={Boolean(cancellingOrderId)}
                onClick={() => onCancel(order)}
                className="flex min-h-10 items-center justify-center gap-2 rounded-xl border border-red-300/15 bg-red-300/[0.055] px-3 text-[10px] font-black text-red-200 transition hover:bg-red-300/[0.1] disabled:cursor-wait disabled:opacity-50"
              >
                {cancelling ? (
                  <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <XCircle className="h-3.5 w-3.5" />
                )}
                {cancelling ? "İptal ediliyor" : "Emri iptal et"}
              </button>
            </article>
          );
        })}
      </div>
    </section>
  );
}

function PendingOrderValue({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-center justify-between gap-3 sm:block">
      <p className="text-[9px] font-black uppercase tracking-wider text-neutral-600">
        {label}
      </p>
      <p className="mt-0.5 truncate font-mono text-xs font-black text-neutral-200">
        {value}
      </p>
    </div>
  );
}

interface MarketRowProps {
  key?: string;
  coin: MarketCoin;
  values: ReturnType<typeof marketValues>;
  favorite: boolean;
  saving: boolean;
  onToggleFavorite: (
    event: MouseEvent<HTMLButtonElement>,
    symbol: string,
  ) => void;
  onTrade: (symbol: string, side: "BUY" | "SELL") => void;
}

function MarketTableRow({
  coin,
  values,
  favorite,
  saving,
  onToggleFavorite,
  onTrade,
}: MarketRowProps) {
  const pair = splitTradingSymbol(coin.symbol);
  const isUp = (values.change ?? 0) >= 0;
  return (
    <tr className="group transition hover:bg-white/[0.025]">
      <td className="px-5 py-3.5 text-center">
        <button
          type="button"
          onClick={(event) => onToggleFavorite(event, coin.symbol)}
          disabled={saving}
          aria-label={
            favorite
              ? `${coin.symbol} favorilerden çıkar`
              : `${coin.symbol} favorilere ekle`
          }
          className="inline-grid h-10 w-10 place-items-center rounded-xl text-neutral-600 transition hover:bg-fuchsia-200/10 hover:text-fuchsia-200 disabled:cursor-wait disabled:opacity-50"
        >
          {saving ? (
            <LoaderCircle className="h-4 w-4 animate-spin" />
          ) : (
            <Star
              className={`h-4 w-4 ${
                favorite ? "fill-fuchsia-200 text-fuchsia-200" : ""
              }`}
            />
          )}
        </button>
      </td>
      <td className="px-3 py-3.5">
        <div className="flex items-center gap-3">
          <CoinLogo symbol={coin.symbol} size={38} />
          <div>
            <p className="font-black text-white">{pair.base}</p>
            <p className="mt-0.5 text-[11px] font-semibold text-neutral-600">
              {pair.quote}
            </p>
          </div>
        </div>
      </td>
      <td className="px-3 py-3.5 text-right font-mono font-black text-neutral-200">
        {values.price === null ? (
          <span className="ml-auto block h-4 w-20 animate-pulse rounded-full bg-white/6" aria-label="Canlı fiyat yükleniyor" />
        ) : (
          <LiveValue value={values.price}>
          {formatPrice(values.price)} {pair.quote}
          </LiveValue>
        )}
      </td>
      <td
        className={`px-3 py-3.5 text-right font-black ${
          isUp ? "text-emerald-300" : "text-red-300"
        }`}
      >
        {values.change === null ? (
          <span className="ml-auto block h-4 w-14 animate-pulse rounded-full bg-white/6" aria-label="24 saatlik değişim yükleniyor" />
        ) : (
          <span className="inline-flex items-center gap-1">
            {isUp ? (
              <ArrowUpRight className="h-3.5 w-3.5" />
            ) : (
              <ArrowDownLeft className="h-3.5 w-3.5" />
            )}
            <LiveValue value={values.change} toneBySign>
              {formatChange(values.change)}
            </LiveValue>
          </span>
        )}
      </td>
      <td className="px-3 py-3.5 text-right text-xs font-semibold text-neutral-500">
        {values.volume === null ? (
          <span className="ml-auto block h-4 w-16 animate-pulse rounded-full bg-white/6" aria-label="Hacim yükleniyor" />
        ) : (
          formatVolume(values.volume, pair.quote)
        )}
      </td>
      <td className="px-5 py-3.5">
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={() => onTrade(coin.symbol, "BUY")}
            className="h-10 rounded-xl border border-emerald-300/15 bg-emerald-300/10 px-4 text-xs font-black text-emerald-200 transition hover:bg-emerald-300/15"
          >
            AL
          </button>
          <button
            type="button"
            onClick={() => onTrade(coin.symbol, "SELL")}
            className="h-10 rounded-xl border border-red-300/15 bg-red-300/10 px-4 text-xs font-black text-red-200 transition hover:bg-red-300/15"
          >
            SAT
          </button>
        </div>
      </td>
    </tr>
  );
}

function MarketMobileCard(props: MarketRowProps) {
  const { coin, values, favorite, saving, onToggleFavorite, onTrade } = props;
  const pair = splitTradingSymbol(coin.symbol);
  const isUp = (values.change ?? 0) >= 0;
  return (
    <article
      className="overflow-hidden rounded-2xl border border-white/8 bg-[radial-gradient(circle_at_top_left,rgba(217,70,239,.07),transparent_48%),#18191f] p-3.5 shadow-[0_14px_36px_rgba(0,0,0,.2)]"
      style={{ contentVisibility: "auto", containIntrinsicSize: "290px" }}
    >
      <div className="grid grid-cols-[44px_1fr_44px] items-center gap-3">
        <CoinLogo symbol={coin.symbol} size={44} />
        <div className="min-w-0 text-center">
          <p className="truncate text-sm font-black text-white">{pair.base}</p>
          <p className="mt-0.5 text-[10px] font-bold uppercase tracking-[0.14em] text-neutral-600">
            {pair.quote} piyasası
          </p>
        </div>
        <button
          type="button"
          onClick={(event) => onToggleFavorite(event, coin.symbol)}
          disabled={saving}
          aria-label={favorite ? `${coin.symbol} favorilerden çıkar` : `${coin.symbol} favorilere ekle`}
          className="grid h-11 w-11 place-items-center rounded-xl border border-fuchsia-300/12 bg-fuchsia-300/[0.045] text-neutral-600 transition active:scale-95"
        >
          {saving ? <LoaderCircle className="h-4 w-4 animate-spin" /> : (
            <Star className={`h-4 w-4 ${favorite ? "fill-fuchsia-200 text-fuchsia-200" : ""}`} />
          )}
        </button>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2">
        <div className="min-w-0 rounded-xl border border-white/7 bg-black/15 p-3">
          <p className="text-[9px] font-black uppercase tracking-wider text-neutral-600">Canlı fiyat</p>
          <p className="mt-1 truncate font-mono text-sm font-black text-white">
            {values.price === null ? (
              <span className="block h-5 w-20 animate-pulse rounded-lg bg-white/6" aria-label="Canlı fiyat yükleniyor" />
            ) : (
              <LiveValue value={values.price}>{formatPrice(values.price)} {pair.quote}</LiveValue>
            )}
          </p>
        </div>
        <div className="min-w-0 rounded-xl border border-white/7 bg-black/15 p-3 text-right">
          <p className="text-[9px] font-black uppercase tracking-wider text-neutral-600">24 saat</p>
          {values.change === null ? (
            <span className="ml-auto mt-1 block h-5 w-14 animate-pulse rounded-full bg-white/6" aria-label="24 saatlik değişim yükleniyor" />
          ) : (
            <p className={`mt-1 font-mono text-sm font-black ${isUp ? "text-emerald-300" : "text-red-300"}`}>
              <LiveValue value={values.change} toneBySign>{formatChange(values.change)}</LiveValue>
            </p>
          )}
        </div>
      </div>

      <div className="mt-2 flex min-h-8 items-center justify-between rounded-xl border border-white/6 bg-white/[0.02] px-3 text-[10px] text-neutral-500">
        <span>24s hacim</span>
        {values.volume === null ? (
          <span className="h-3.5 w-16 animate-pulse rounded-full bg-white/6" aria-label="Hacim yükleniyor" />
        ) : (
          <span className="font-mono font-bold text-neutral-400">{formatVolume(values.volume, pair.quote)}</span>
        )}
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2">
        <button type="button" onClick={() => onTrade(coin.symbol, "BUY")} className="h-11 rounded-xl border border-emerald-300/15 bg-emerald-400/10 text-xs font-black text-emerald-200 transition active:scale-[.98]">
          ALIŞ
        </button>
        <button type="button" onClick={() => onTrade(coin.symbol, "SELL")} className="h-11 rounded-xl border border-red-300/15 bg-red-400/10 text-xs font-black text-red-200 transition active:scale-[.98]">
          SATIŞ
        </button>
      </div>
    </article>
  );
}
