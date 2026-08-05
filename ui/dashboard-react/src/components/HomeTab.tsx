import {
  Activity,
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  Bot as BotIcon,
  ChevronLeft,
  ChevronRight,
  CircleDollarSign,
  Clock3,
  Info,
  Layers3,
  Repeat2,
  ShieldCheck,
  Sparkles,
  Star,
  WalletCards,
  X,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useDashboard } from "../context/DashboardContext";
import { apiFetch } from "../lib/api";
import type {
  Bot,
  LeaderboardItem,
  Trade,
  WalletAsset,
  WalletState,
} from "../types";
import CoinLogo, { splitTradingSymbol } from "./coin/CoinLogo";
import LiveValue from "./live/LiveValue";

interface HomeTabProps {
  bots: Bot[];
  wallet: WalletState;
  prices: Record<string, { price?: number; change24h?: number; volume24h?: number }>;
  onOpenTradeModal: (symbol: string, side: "BUY" | "SELL") => void;
  onApplyLeaderboard: (params: unknown) => void;
  isTestAccount: boolean;
  onOpenBot?: (botId: number) => void;
  isActive?: boolean;
}

type Period = "daily" | "weekly" | "monthly" | "all";
type TransactionType = "all" | "buysell" | "depositwithdraw";
type TransactionPagination = {
  total: number;
  page: number;
  perPage: number;
  totalPages: number;
};

const PERIOD_LABELS: Record<Period, string> = {
  daily: "Gün",
  weekly: "Hafta",
  monthly: "Ay",
  all: "Genel",
};

function finite(value: unknown, fallback = 0): number {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function displayNumber(value: unknown, digits = 2): string {
  if (value === null || value === undefined || value === "") return "—";
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "—";
  return numeric.toLocaleString("tr-TR", {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  });
}

/** Adet/bakiye: coin’e ve büyüklüğe göre dinamik ondalık (USDT kısa, küçük coinler daha hassas). */
function assetAmountDigits(asset: string, value: unknown): number {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return 2;
  const absolute = Math.abs(numeric);
  const symbol = asset.trim().toUpperCase();
  const quoteLike = /^(USDT|USDC|BUSD|FDUSD|TUSD|USD|TRY|EUR)$/.test(symbol);
  if (quoteLike) {
    if (absolute >= 100) return 2;
    if (absolute >= 1) return 3;
    return 4;
  }
  if (absolute >= 1_000) return 2;
  if (absolute >= 100) return 3;
  if (absolute >= 10) return 4;
  if (absolute >= 1) return 5;
  if (absolute >= 0.1) return 6;
  if (absolute >= 0.01) return 7;
  return 8;
}

function displayAssetAmount(asset: string, value: unknown): string {
  return displayNumber(value, assetAmountDigits(asset, value));
}

function money(value: unknown): string {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "—";
  return new Intl.NumberFormat("tr-TR", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(numeric);
}

function formatTime(value: unknown): string {
  const date = new Date(String(value ?? ""));
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("tr-TR", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(date);
}

function sideLabel(side: string): string {
  const normalized = side.toUpperCase();
  if (normalized === "BUY") return "Alış";
  if (normalized === "SELL") return "Satış";
  return side || "Hareket";
}

function tradeSourceLabel(trade: Trade): string {
  const named = String(
    (trade as Trade & { bot_name?: string | null }).bot_name || "",
  ).trim();
  if (trade.is_bot) {
    return named ? `Bot · ${named}` : "Bot";
  }
  const label = String(
    (trade as Trade & { source_label?: string }).source_label || "",
  ).trim();
  if (label && !["manuel", "spot", "manual"].includes(label.toLowerCase())) {
    return label;
  }
  const platform = String(
    (trade as Trade & { platform?: string | null }).platform || "",
  ).trim();
  if (platform) {
    const p = platform.toLowerCase();
    if (p === "ayserose" || p === "tradetrailing" || p === "tradertrailing") {
      return "Ayserose";
    }
    if (p === "binance") return "Binance";
    return platform;
  }
  return "Binance";
}

type TemplateGrid = {
  triggerPct: number | null;
  qtyPct: number | null;
};

type TemplateStrategy = {
  basePct: number | null;
  quotePct: number | null;
  upTrail: number | null;
  downTrail: number | null;
  sellGrids: TemplateGrid[];
  buyGrids: TemplateGrid[];
  rebuyTrigger: number | null;
  rebuyTrail: number | null;
  resellTrigger: number | null;
  resellTrail: number | null;
  referencePrice: number | null;
  strategyLabel: string;
};

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function optionalNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function readTemplateGrids(
  preferred: unknown,
  legacy: unknown,
  triggerKeys: string[],
  qtyKeys: string[],
): TemplateGrid[] {
  const rows = Array.isArray(preferred)
    ? preferred
    : Array.isArray(legacy)
      ? legacy
      : [];
  return rows.map((value) => {
    const row = asRecord(value);
    return {
      triggerPct: optionalNumber(
        triggerKeys.map((key) => row[key]).find((candidate) => candidate !== undefined),
      ),
      qtyPct: optionalNumber(
        qtyKeys.map((key) => row[key]).find((candidate) => candidate !== undefined),
      ),
    };
  });
}

function parseTemplateStrategy(paramsValue: unknown): TemplateStrategy {
  const params = asRecord(paramsValue);
  const allocation = asRecord(params.allocation);
  const up = asRecord(params.up);
  const down = asRecord(params.down);
  const profit = asRecord(params.profit);
  const strategyId = String(params.strategy_id || "dca_grid_trailing");
  return {
    basePct: optionalNumber(params.base_alloc_pct ?? allocation.base_pct),
    quotePct: optionalNumber(params.quote_alloc_pct ?? allocation.quote_pct),
    upTrail: optionalNumber(
      up.trail_pct ?? params.sell_trigger_trailing_pct,
    ),
    downTrail: optionalNumber(
      down.trail_pct ?? params.buy_trigger_trailing_pct,
    ),
    sellGrids: readTemplateGrids(
      up.grids,
      params.sell_grids,
      ["trigger_pct", "sell_grid_pct"],
      ["qty_pct", "sell_qty_pct_of_base"],
    ),
    buyGrids: readTemplateGrids(
      down.grids,
      params.buy_grids,
      ["trigger_pct", "buy_grid_pct"],
      ["qty_pct", "buy_qty_pct_of_quote"],
    ),
    rebuyTrigger: optionalNumber(
      profit.rebuy_trigger_pct ?? params.profit_reentry_drop_pct,
    ),
    rebuyTrail: optionalNumber(
      profit.rebuy_trail_pct ?? params.profit_reentry_rise_pct,
    ),
    resellTrigger: optionalNumber(
      profit.resell_trigger_pct ?? params.profit_exit_rise_pct,
    ),
    resellTrail: optionalNumber(
      profit.resell_trail_pct ?? params.profit_exit_drop_pct,
    ),
    referencePrice: optionalNumber(params.reference_price),
    strategyLabel:
      strategyId === "dca_grid_trailing"
        ? "Trailing DCA grid"
        : strategyId.replaceAll("_", " "),
  };
}

function templatePrice(value: unknown): string {
  const numeric = optionalNumber(value);
  if (numeric === null) return "—";
  const digits = numeric < 0.01 ? 8 : numeric < 1 ? 6 : 2;
  return `$${numeric.toLocaleString("tr-TR", {
    minimumFractionDigits: Math.min(digits, 2),
    maximumFractionDigits: digits,
  })}`;
}

function templatePct(value: number | null): string {
  return value === null
    ? "—"
    : `%${value.toLocaleString("tr-TR", { maximumFractionDigits: 4 })}`;
}

function elapsedSince(value: string | null | undefined): string {
  if (!value) return "—";
  const startedAt = new Date(value).getTime();
  if (!Number.isFinite(startedAt)) return "—";
  const seconds = Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
  const days = Math.floor(seconds / 86_400);
  if (days >= 365) {
    const years = Math.floor(days / 365);
    const remainingMonths = Math.floor((days % 365) / 30);
    return `${years} yıl${remainingMonths ? ` ${remainingMonths} ay` : ""}`;
  }
  if (days >= 30) {
    const months = Math.floor(days / 30);
    const remainingDays = days % 30;
    return `${months} ay${remainingDays ? ` ${remainingDays} gün` : ""}`;
  }
  if (days > 0) return `${days} gün`;
  const hours = Math.floor(seconds / 3600);
  if (hours > 0) return `${hours} sa`;
  return `${Math.max(1, Math.floor(seconds / 60))} dk`;
}

export default function HomeTab({
  bots,
  wallet,
  prices,
  onOpenTradeModal,
  onApplyLeaderboard,
  isTestAccount,
  onOpenBot,
  isActive = true,
}: HomeTabProps) {
  const [selectedPeriod, setSelectedPeriod] = useState<Period>("all");
  // "daily" hides older live-account fills (often empty); show a useful window by default.
  const [txPeriod, setTxPeriod] = useState<Period>("monthly");
  const [txType, setTxType] = useState<TransactionType>("buysell");
  const [txPage, setTxPage] = useState(1);
  const txSyncOnceRef = useRef<Record<number, boolean>>({});
  const [txPagination, setTxPagination] = useState<TransactionPagination>({
    total: 0,
    page: 1,
    perPage: 8,
    totalPages: 0,
  });
  const [trades, setTrades] = useState<Trade[]>([]);
  const [leaderboard, setLeaderboard] = useState<LeaderboardItem[]>([]);
  const [selectedLeaderboardItem, setSelectedLeaderboardItem] =
    useState<LeaderboardItem | null>(null);
  const [perfPnl, setPerfPnl] = useState(0);
  const [perfFees, setPerfFees] = useState(0);
  const [dailyWalletPnl, setDailyWalletPnl] = useState(0);
  const [dailyBotPnl, setDailyBotPnl] = useState(0);
  const [dataNotice, setDataNotice] = useState("");
  const [manualRefreshKey, setManualRefreshKey] = useState(0);
  const { accountId } = useDashboard();

  useEffect(() => {
    const onManualRefresh = () => setManualRefreshKey((value) => value + 1);
    window.addEventListener("ayserose:manual-refresh", onManualRefresh);
    return () => window.removeEventListener("ayserose:manual-refresh", onManualRefresh);
  }, []);

  useEffect(() => {
    if (!accountId || !isActive) return;
    let cancelled = false;
    let timer = 0;
    const normalizeItems = (items: Trade[]) =>
      items.map((trade) => {
        const side = String(trade.side || trade.type || "").toUpperCase();
        const normalizedSide =
          side === "BUY" ||
          side === "SELL" ||
          side === "DEPOSIT" ||
          side === "WITHDRAW"
            ? side
            : String(trade.side || "");
        const source = String(
          (trade as Trade & { source?: string; bot_id?: number }).source || "",
        ).toLowerCase();
        return {
          ...trade,
          side: normalizedSide,
          is_bot:
            trade.is_bot === true ||
            source === "bot" ||
            Number((trade as Trade & { bot_id?: number }).bot_id) > 0,
          executed_qty: finite(trade.executed_qty ?? trade.qty),
          avg_price: finite(trade.avg_price ?? trade.price),
        };
      });
    const fetchTrades = (opts?: { forceSync?: boolean }) => {
      if (document.hidden) return;
      const needsSync =
        Boolean(opts?.forceSync) || !txSyncOnceRef.current[accountId];
      if (needsSync) txSyncOnceRef.current[accountId] = true;
      const query = new URLSearchParams({
        period: txPeriod,
        type_filter: txType,
        page: String(txPage),
        per_page: "8",
      });
      if (needsSync) query.set("sync", "1");
      apiFetch<{
        items?: Trade[];
        total?: number;
        page?: number;
        per_page?: number;
        total_pages?: number;
      }>(`/api/accounts/${accountId}/transaction-history?${query}`)
        .then(async (data) => {
          if (cancelled) return;
          let totalPages = Math.max(0, finite(data?.total_pages));
          let resolvedPage = Math.max(1, finite(data?.page, txPage));
          const items = Array.isArray(data?.items) ? data.items : [];
          const total = Math.max(0, finite(data?.total));

          setTrades(normalizeItems(items));
          setTxPagination({
            total,
            page: resolvedPage,
            perPage: Math.max(1, finite(data?.per_page, 8)),
            totalPages,
          });
          if (totalPages > 0 && resolvedPage > totalPages) {
            setTxPage(totalPages);
          }
        })
        .catch((error) =>
          !cancelled &&
          setDataNotice(
            error instanceof Error
              ? error.message
              : "İşlem geçmişi alınamadı.",
          ),
        );
    };
    const onVisibility = () => fetchTrades();
    fetchTrades({ forceSync: Boolean(manualRefreshKey) });
    timer = window.setInterval(() => fetchTrades(), 30_000);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [accountId, txPage, txPeriod, txType, manualRefreshKey, isActive]);

  useEffect(() => {
    if (!isActive) return;
    apiFetch<{ items?: LeaderboardItem[] }>(
      "/api/leaderboard/global/top?limit=5",
    )
      .then((data) =>
        setLeaderboard(Array.isArray(data?.items) ? data.items : []),
      )
      .catch(() => setLeaderboard([]));
  }, [accountId, manualRefreshKey, isActive]);

  useEffect(() => {
    if (!accountId || !isActive) return;
    apiFetch<{
      totals?: { pnl_usd?: number; fees_usd?: number };
      pnl_usd?: number;
    }>(`/api/accounts/${accountId}/bot-performance?period=${selectedPeriod}`)
      .then((data) => {
        setPerfPnl(finite(data?.totals?.pnl_usd ?? data?.pnl_usd));
        setPerfFees(finite(data?.totals?.fees_usd));
      })
      .catch((error) =>
        setDataNotice(
          error instanceof Error ? error.message : "Performans alınamadı.",
        ),
      );
  }, [accountId, selectedPeriod, manualRefreshKey, isActive]);

  useEffect(() => {
    if (!accountId || !isActive) return;
    apiFetch<{
      daily_wallet_pnl_usd?: number;
      daily_bot_pnl_usd?: number;
      data_status?: string;
      error?: string;
    }>(`/api/finance/summary?account_id=${accountId}`)
      .then((data) => {
        setDailyWalletPnl(finite(data.daily_wallet_pnl_usd));
        setDailyBotPnl(finite(data.daily_bot_pnl_usd));
        if (data.data_status === "error") {
          setDataNotice(data.error || "Finans özeti güncel değil.");
        }
      })
      .catch((error) =>
        setDataNotice(
          error instanceof Error ? error.message : "Finans özeti alınamadı.",
        ),
      );
  }, [accountId, manualRefreshKey, isActive]);

  const runningBots = bots.filter((bot) =>
    ["running", "starting"].includes(
      String(bot.display_status || bot.status).toLowerCase(),
    ),
  );
  const botValue = bots.reduce(
    (total, bot) => total + finite(bot.current_usd),
    0,
  );
  const dailyWalletPct = wallet.total_usd
    ? (dailyWalletPnl /
        Math.max(1, wallet.total_usd - dailyWalletPnl)) *
      100
    : null;
  const visibleTrades = trades.filter((trade) => {
    const side = String(trade.side || trade.type || "").toUpperCase();
    if (txType === "all") return true;
    if (txType === "buysell") {
      return side === "BUY" || side === "SELL";
    }
    return side !== "BUY" && side !== "SELL";
  });
  const visibleAssets = (wallet.assets || []).filter(
    (asset) => finite(asset.total_usd) >= 1,
  );

  return (
    <div className="space-y-5 sm:space-y-7">
      {dataNotice && (
        <div
          role="status"
          className="flex items-start justify-between gap-3 rounded-2xl border border-amber-300/15 bg-amber-300/[0.055] px-4 py-3 text-xs leading-5 text-amber-100"
        >
          <span>{dataNotice}</span>
          <button
            type="button"
            onClick={() => setDataNotice("")}
            className="grid h-8 w-8 shrink-0 place-items-center rounded-lg text-amber-200 hover:bg-white/5"
            aria-label="Bildirimi kapat"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}

      <section className="home-balance-hero relative overflow-hidden rounded-[1.75rem] border border-fuchsia-300/15 bg-[#191a21] p-5 sm:p-7">
        <div className="relative z-10 grid gap-6 lg:grid-cols-[1fr_auto] lg:items-end">
          <div>
            <p className="flex items-center gap-2 text-[10px] font-black uppercase tracking-[0.2em] text-fuchsia-200">
              <Sparkles className="h-4 w-4" />
              Portföy merkezi
            </p>
            <p className="mt-5 text-xs font-bold text-neutral-500">
              Toplam spot değeri
            </p>
            <h1 className="mt-1 text-4xl font-black tracking-[-0.045em] text-white sm:text-5xl">
              <LiveValue value={wallet.total_usd}>
                {money(wallet.total_usd)}
              </LiveValue>
            </h1>
            <div className="mt-4 flex flex-wrap items-center gap-2">
              <span
                className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1.5 text-[10px] font-black ${
                  wallet.keys_configured
                    ? "border-emerald-300/15 bg-emerald-300/[0.06] text-emerald-200"
                    : "border-amber-300/15 bg-amber-300/[0.06] text-amber-200"
                }`}
              >
                <ShieldCheck className="h-3.5 w-3.5" />
                {wallet.keys_configured
                  ? "Binance canlı verisi"
                  : "API bağlantısı bekleniyor"}
              </span>
              {isTestAccount && (
                <span className="rounded-full border border-violet-300/15 bg-violet-300/[0.06] px-2.5 py-1.5 text-[10px] font-black text-violet-200">
                  Test hesabı
                </span>
              )}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2 sm:min-w-[360px]">
            <HeroMetric
              label="Bugün"
              value={`${dailyWalletPnl >= 0 ? "+" : "−"}${money(
                Math.abs(dailyWalletPnl),
              )}`}
              tone={dailyWalletPnl >= 0 ? "positive" : "negative"}
              icon={dailyWalletPnl >= 0 ? ArrowUpRight : ArrowDownRight}
              liveValue={dailyWalletPnl}
            />
            <HeroMetric
              label="Günlük oran"
              value={
                dailyWalletPct === null
                  ? "Veri bekleniyor"
                  : `${dailyWalletPct >= 0 ? "+" : ""}${dailyWalletPct.toFixed(2)}%`
              }
              tone={
                dailyWalletPct === null
                  ? undefined
                  : dailyWalletPct >= 0
                    ? "positive"
                    : "negative"
              }
              icon={Activity}
              liveValue={dailyWalletPct}
            />
          </div>
        </div>
      </section>

      <section
        aria-label="Hızlı bakiye özeti"
        className="flex snap-x snap-mandatory gap-3 overflow-x-auto px-1 pb-1 sm:grid sm:grid-cols-2 sm:px-0 lg:grid-cols-4"
      >
        <StatCard
          icon={WalletCards}
          label="Kullanılabilir"
          value={money(wallet.available_usd)}
          detail="Yeni işlemlere açık bakiye"
          tone="violet"
          liveValue={wallet.available_usd}
        />
        <StatCard
          icon={Layers3}
          label="Botlarda"
          value={money(botValue || wallet.bot_locked_usd)}
          detail={`${runningBots.length} aktif bot`}
          tone="purple"
          liveValue={botValue || wallet.bot_locked_usd}
        />
        <StatCard
          icon={Clock3}
          label="Emirlerde kilitli"
          value={money(wallet.locked_usd)}
          detail="Açık emirlerde bekliyor"
          tone="neutral"
          liveValue={wallet.locked_usd}
        />
        <StatCard
          icon={dailyBotPnl >= 0 ? ArrowUpRight : ArrowDownRight}
          label="Günlük bot sonucu"
          value={`${dailyBotPnl >= 0 ? "+" : "−"}${money(
            Math.abs(dailyBotPnl),
          )}`}
          detail="Gerçekleşen tur toplamı"
          tone={dailyBotPnl >= 0 ? "green" : "red"}
          liveValue={dailyBotPnl}
        />
      </section>

      <section className="overflow-hidden rounded-[1.65rem] border border-white/8 bg-[#191a20]">
        <SectionHeader
          icon={WalletCards}
          eyebrow="Canlı cüzdan"
          title="Cüzdan varlıkları"
          detail={`${visibleAssets.length} varlık`}
          count={money(wallet.total_usd)}
        />
        {visibleAssets.length ? (
          <div
            aria-label="Cüzdan varlık kartları"
            className="flex snap-x snap-mandatory scroll-px-5 gap-3 overflow-x-auto px-5 pb-5 sm:px-6"
          >
            {visibleAssets.map((asset) => (
              <AssetCard
                key={asset.asset}
                asset={asset}
                prices={prices}
                onTrade={onOpenTradeModal}
              />
            ))}
          </div>
        ) : (
          <EmptyState
            icon={WalletCards}
            title="Cüzdan verisi bekleniyor"
            detail="Bağlantı kurulduğunda varlıkların burada yatay kartlar halinde görünecek."
          />
        )}
      </section>

      <section className="overflow-hidden rounded-[1.65rem] border border-white/8 bg-[#191a20]">
        <SectionHeader
          icon={BotIcon}
          eyebrow="Otomasyon"
          title="Mevcut botlar"
          count={`${runningBots.length} aktif`}
          countTone={runningBots.length ? "positive" : "neutral"}
        />
        {bots.length ? (
          <div
            aria-label="Mevcut bot kartları"
            className="flex snap-x snap-mandatory scroll-px-5 gap-3 overflow-x-auto px-5 pb-5 sm:px-6"
          >
            {bots.map((bot) => (
              <BotCard key={bot.id} bot={bot} onOpen={onOpenBot} />
            ))}
          </div>
        ) : (
          <EmptyState
            icon={BotIcon}
            title="Henüz bot yok"
            detail="Botlar bölümünde oluşturduğun stratejiler burada hızlı özet olarak görünür."
          />
        )}
      </section>

      <div className="grid gap-5 lg:grid-cols-2">
        <section className="rounded-[1.65rem] border border-white/8 bg-[#191a20] p-4 sm:p-5">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-[10px] font-black uppercase tracking-[0.18em] text-fuchsia-200">
                Strateji sonucu
              </p>
              <h2 className="mt-1 text-lg font-black text-white">
                Bot performansı
              </h2>
            </div>
            <PeriodSelector
              value={selectedPeriod}
              onChange={setSelectedPeriod}
            />
          </div>
          <div className="mt-5 grid grid-cols-2 gap-3">
            <PerformanceCard
              label="Net K/Z"
              value={`${perfPnl >= 0 ? "+" : "−"}${money(Math.abs(perfPnl))}`}
              positive={perfPnl >= 0}
            />
            <PerformanceCard
              label="Toplam komisyon"
              value={money(perfFees)}
            />
          </div>
          <p className="mt-4 flex items-start gap-2 rounded-xl border border-white/7 bg-black/10 p-3 text-[11px] leading-5 text-neutral-500">
            <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-fuchsia-200" />
            Kâr/zarar ve komisyonlar seçili dönemde işlem gören botların tamamlanmış
            tur verilerinden gelir. Devam eden turlar burada gösterilmez.
          </p>
        </section>

        <section className="overflow-hidden rounded-[1.65rem] border border-white/8 bg-[#191a20]">
          <SectionHeader
            icon={Star}
            eyebrow="Topluluk verisi"
            title="En iyi botlar"
            detail="İncele veya bot oluşturucuya taşı"
          />
          {leaderboard.length ? (
            <div className="flex snap-x snap-mandatory scroll-px-5 gap-3 overflow-x-auto px-5 pb-5 sm:px-6">
              {leaderboard.map((item, index) => (
                <LeaderboardCard
                  key={`${item.symbol}-${index}`}
                  item={item}
                  rank={index + 1}
                  onInspect={() => setSelectedLeaderboardItem(item)}
                  onApply={() =>
                    onApplyLeaderboard({
                      ...(item.params || {}),
                      symbol: item.symbol,
                    })
                  }
                />
              ))}
            </div>
          ) : (
            <EmptyState
              icon={Star}
              title="Şablon verisi bekleniyor"
              detail="Global sonuçlar geldiğinde burada görünecek."
            />
          )}
        </section>
      </div>

      <section className="overflow-hidden rounded-[1.65rem] border border-white/8 bg-[#191a20]">
        <div className="border-b border-white/8 p-4 sm:p-5">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <p className="text-[10px] font-black uppercase tracking-[0.18em] text-fuchsia-200">
                Hesap hareketleri
              </p>
              <h2 className="mt-1 text-lg font-black text-white">
                İşlem geçmişi
              </h2>
              <p className="mt-1 text-xs leading-5 text-neutral-500">
                Binance emirleri ve cüzdan hareketleri
              </p>
            </div>
            <div className="space-y-2">
              <PeriodSelector
                value={txPeriod}
                onChange={(value) => {
                  setTxPeriod(value);
                  setTxPage(1);
                }}
              />
              <div className="flex gap-1 overflow-x-auto rounded-xl border border-white/8 bg-black/15 p-1">
                {(
                  [
                    ["all", "Tümü"],
                    ["buysell", "Alım / Satım"],
                    ["depositwithdraw", "Yatırım / çekim"],
                  ] as Array<[TransactionType, string]>
                ).map(([value, label]) => (
                  <FilterButton
                    key={value}
                    selected={txType === value}
                    onClick={() => {
                      setTxType(value);
                      setTxPage(1);
                    }}
                  >
                    {label}
                  </FilterButton>
                ))}
              </div>
            </div>
          </div>
        </div>

        {visibleTrades.length ? (
          <>
            <div className="divide-y divide-white/[0.055] sm:hidden">
              {visibleTrades.map((trade, index) => (
                <MobileTradeCard
                  key={`${trade.order_id}-${index}`}
                  trade={trade}
                />
              ))}
            </div>
            <div className="hidden overflow-x-auto sm:block">
              <table className="min-w-full text-left text-sm text-neutral-300">
                <thead className="bg-black/15 text-[10px] font-black uppercase tracking-wider text-neutral-600">
                  <tr>
                    <th className="px-5 py-3">Tarih</th>
                    <th className="px-5 py-3">Sembol</th>
                    <th className="px-5 py-3">Tür</th>
                    <th className="px-5 py-3 text-right">Miktar</th>
                    <th className="px-5 py-3 text-right">Fiyat</th>
                    <th className="px-5 py-3 text-right">Toplam</th>
                    <th className="px-5 py-3 text-right">Komisyon</th>
                    <th className="px-5 py-3 text-right">Kaynak</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/[0.055]">
                  {visibleTrades.map((trade, index) => (
                    <DesktopTradeRow
                      key={`${trade.order_id}-${index}`}
                      trade={trade}
                    />
                  ))}
                </tbody>
              </table>
            </div>
            <TransactionPaginationBar
              pagination={txPagination}
              onPageChange={setTxPage}
            />
          </>
        ) : (
          <EmptyState
            icon={Clock3}
            title="Bu filtrede hareket yok"
            detail="Dönemi veya işlem türünü değiştirerek tekrar bakabilirsin."
          />
        )}
      </section>

      {selectedLeaderboardItem && (
        <LeaderboardDialog
          item={selectedLeaderboardItem}
          onClose={() => setSelectedLeaderboardItem(null)}
          onApply={() => {
            onApplyLeaderboard({
              ...(selectedLeaderboardItem.params || {}),
              symbol: selectedLeaderboardItem.symbol,
            });
            setSelectedLeaderboardItem(null);
          }}
        />
      )}
    </div>
  );
}

function HeroMetric({
  label,
  value,
  tone,
  icon: Icon,
  liveValue,
}: {
  label: string;
  value: string;
  tone?: "positive" | "negative";
  icon: LucideIcon;
  liveValue?: unknown;
}) {
  return (
    <div className="rounded-2xl border border-white/8 bg-black/15 p-3.5 backdrop-blur">
      <p className="flex items-center gap-1.5 text-[9px] font-black uppercase tracking-wider text-neutral-600">
        <Icon className="h-3.5 w-3.5" />
        {label}
      </p>
      <p
        className={`mt-2 truncate text-sm font-black ${
          tone === "positive"
            ? "text-emerald-300"
            : tone === "negative"
              ? "text-red-300"
              : "text-white"
        }`}
        title={value}
      >
        {liveValue !== undefined ? (
          <LiveValue value={liveValue}>{value}</LiveValue>
        ) : (
          value
        )}
      </p>
    </div>
  );
}

function StatCard({
  icon: Icon,
  label,
  value,
  detail,
  tone,
  liveValue,
}: {
  icon: LucideIcon;
  label: string;
  value: string;
  detail: string;
  tone: "violet" | "purple" | "neutral" | "green" | "red";
  liveValue?: unknown;
}) {
  const tones = {
    violet: "border-violet-300/12 text-violet-200",
    purple: "border-fuchsia-300/12 text-fuchsia-200",
    neutral: "border-white/8 text-neutral-400",
    green: "border-emerald-300/12 text-emerald-300",
    red: "border-red-300/12 text-red-300",
  };
  return (
    <article
      className={`min-w-[74vw] snap-start rounded-2xl border bg-[#191a20] p-4 sm:min-w-0 ${tones[tone]}`}
    >
      <p className="flex items-center gap-2 text-[10px] font-black uppercase tracking-wider text-neutral-600">
        <Icon className={`h-4 w-4 ${tones[tone].split(" ")[1]}`} />
        {label}
      </p>
      <p className={`mt-3 text-xl font-black ${tones[tone].split(" ")[1]}`}>
        {liveValue !== undefined ? (
          <LiveValue value={liveValue}>{value}</LiveValue>
        ) : (
          value
        )}
      </p>
      <p className="mt-1 text-[11px] leading-5 text-neutral-500">{detail}</p>
    </article>
  );
}

function SectionHeader({
  icon: Icon,
  eyebrow,
  title,
  detail,
  count,
  countTone = "neutral",
}: {
  icon: LucideIcon;
  eyebrow: string;
  title: string;
  detail?: string;
  count?: string;
  countTone?: "positive" | "neutral";
}) {
  return (
    <header className="flex items-start justify-between gap-4 p-4 sm:p-5">
      <div className="flex min-w-0 items-center gap-3">
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-fuchsia-300/12 bg-fuchsia-300/[0.055] text-fuchsia-200">
          <Icon className="h-4 w-4" />
        </span>
        <div className="min-w-0">
          <p className="text-[9px] font-black uppercase tracking-[0.17em] text-fuchsia-200">
            {eyebrow}
          </p>
          <h2 className="mt-0.5 truncate text-base font-black text-white sm:text-lg">
            {title}
          </h2>
          {detail ? (
            <p className="mt-1 text-[11px] leading-5 text-neutral-500">{detail}</p>
          ) : null}
        </div>
      </div>
      {count && (
        <span
          className={`shrink-0 rounded-full border px-2.5 py-1.5 text-[10px] font-black ${
            countTone === "positive"
              ? "border-emerald-300/15 bg-emerald-300/[0.055] text-emerald-200"
              : "border-white/8 bg-white/[0.035] text-neutral-400"
          }`}
        >
          {count}
        </span>
      )}
    </header>
  );
}

function AssetCard({
  asset,
  prices,
  onTrade,
}: {
  key?: string;
  asset: WalletAsset;
  prices: HomeTabProps["prices"];
  onTrade: HomeTabProps["onOpenTradeModal"];
}) {
  const pairSymbol = asset.asset === "USDT" ? "USDTTRY" : `${asset.asset}USDT`;
  const live = prices[pairSymbol];
  const price =
    asset.asset === "USDT"
      ? 1
      : finite(live?.price ?? asset.price_usd, Number.NaN);
  const change = Number(live?.change24h);
  const hasChange = Number.isFinite(change);
  const total =
    finite(asset.total) ||
    finite(asset.free) + finite(asset.locked) + finite(asset.bot_locked);
  const available = finite(
    asset.available,
    Math.max(0, finite(asset.free) - finite(asset.bot_locked)),
  );
  const botLocked = finite(asset.bot_locked);
  const tradable = Boolean(asset.asset);
  return (
    <article className="min-w-[82vw] max-w-[320px] snap-start rounded-2xl border border-white/8 bg-gradient-to-br from-white/[0.045] to-transparent p-4 sm:min-w-[300px]">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <CoinLogo symbol={asset.asset} size={44} />
          <div>
            <p className="text-base font-black text-white">{asset.asset}</p>
            <p className="mt-0.5 text-[10px] font-bold uppercase tracking-wider text-neutral-600">
              Spot varlık
            </p>
          </div>
        </div>
        {hasChange ? (
          <span
            className={`rounded-full px-2 py-1 text-[10px] font-black ${
              change >= 0
                ? "bg-emerald-300/[0.07] text-emerald-300"
                : "bg-red-300/[0.07] text-red-300"
            }`}
          >
            <LiveValue value={change} toneBySign>
              {change >= 0 ? "+" : ""}
              {change.toFixed(2)}%
            </LiveValue>
          </span>
        ) : null}
      </div>

      <div className="mt-5 grid grid-cols-2 gap-2">
        <MiniValue
          label="USD değeri"
          value={money(asset.total_usd)}
          liveValue={asset.total_usd}
        />
        <MiniValue
          label="Canlı fiyat"
          value={
            Number.isFinite(price)
              ? `$${displayNumber(price, price < 1 ? 6 : 2)}`
              : "—"
          }
          liveValue={price}
        />
        <MiniValue label="Toplam adet" value={displayAssetAmount(asset.asset, total)} />
        <MiniValue
          label="Kullanılabilir"
          value={displayAssetAmount(asset.asset, available)}
        />
        <div className="hidden sm:col-span-2 sm:block">
          <MiniValue
            label="Botlarda kilitli"
            value={displayAssetAmount(asset.asset, botLocked)}
            valueClass="text-fuchsia-200"
          />
        </div>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-2">
        <button
          type="button"
          disabled={!tradable}
          onClick={() => onTrade(pairSymbol, "BUY")}
          className="min-h-11 rounded-xl border border-emerald-300/15 bg-emerald-300/[0.06] text-xs font-black text-emerald-200 transition active:scale-[.98] disabled:cursor-not-allowed disabled:opacity-35"
        >
          {tradable ? "AL" : "Nakit"}
        </button>
        <button
          type="button"
          disabled={!tradable}
          onClick={() => onTrade(pairSymbol, "SELL")}
          className="min-h-11 rounded-xl border border-red-300/15 bg-red-300/[0.06] text-xs font-black text-red-200 transition active:scale-[.98] disabled:cursor-not-allowed disabled:opacity-35"
        >
          {tradable ? "SAT" : "Varlık"}
        </button>
      </div>
    </article>
  );
}

function BotCard({
  bot,
  onOpen,
}: {
  key?: number;
  bot: Bot;
  onOpen?: (botId: number) => void;
}) {
  const id = Number(bot.bot_id ?? bot.id);
  const status = String(bot.display_status || bot.status).toLowerCase();
  const running = ["running", "starting"].includes(status);
  const pnl = finite(bot.total_pnl_pct);
  const pair = splitTradingSymbol(bot.symbol);
  return (
    <article className="min-w-[84vw] max-w-[340px] snap-start overflow-hidden rounded-2xl border border-white/8 bg-gradient-to-br from-white/[0.045] to-transparent sm:min-w-[320px]">
      <div className="flex items-start justify-between gap-3 p-4">
        <div className="flex min-w-0 items-center gap-3">
          <CoinLogo symbol={bot.symbol} size={46} />
          <div className="min-w-0">
            <p className="truncate text-base font-black text-white">
              {pair.label}
            </p>
            <p className="mt-0.5 text-[10px] font-bold uppercase tracking-wider text-neutral-600">
              Bot #{id}
            </p>
          </div>
        </div>
        <span
          className={`shrink-0 rounded-full px-2 py-1 text-[10px] font-black ${
            running
              ? "bg-emerald-300/[0.07] text-emerald-300"
              : status.includes("error")
                ? "bg-red-300/[0.07] text-red-300"
                : "bg-white/5 text-neutral-500"
          }`}
        >
          {status === "starting"
            ? "Başlatılıyor"
            : running
              ? "Çalışıyor"
              : status.includes("error")
                ? "Hata"
                : "Durduruldu"}
        </span>
      </div>
      <div className="mx-3 grid grid-cols-2 gap-px overflow-hidden rounded-xl bg-white/6">
        <MiniValue
          label="Bot değeri"
          value={money(bot.current_usd)}
          liveValue={bot.current_usd}
          boxed
        />
        <MiniValue
          label="Başlangıç"
          value={money(bot.budget_usd)}
          boxed
        />
        <MiniValue
          label="Aktif tur"
          value={String(
            Math.max(
              1,
              Math.round(
                finite(bot.cycle_id, finite(bot.total_cycles_completed) + 1),
              ),
            ),
          )}
          boxed
        />
        <MiniValue
          label="Performans"
          value={`${pnl >= 0 ? "+" : ""}${pnl.toFixed(2)}%`}
          valueClass={pnl >= 0 ? "text-emerald-300" : "text-red-300"}
          liveValue={pnl}
          boxed
        />
      </div>
      <button
        type="button"
        onClick={() => onOpen?.(id)}
        className="m-3 flex min-h-12 w-[calc(100%-1.5rem)] items-center justify-between rounded-xl border border-fuchsia-300/12 bg-fuchsia-300/[0.045] px-4 text-xs font-black text-fuchsia-100 transition hover:bg-fuchsia-300/[0.07] active:bg-fuchsia-300/[0.1]"
      >
        Bot ayrıntısını aç
        <ArrowRight className="h-4 w-4" />
      </button>
    </article>
  );
}

function MiniValue({
  label,
  value,
  valueClass = "",
  boxed = false,
  liveValue,
}: {
  label: string;
  value: string;
  valueClass?: string;
  boxed?: boolean;
  liveValue?: unknown;
}) {
  return (
    <div className={boxed ? "bg-[#191a20] p-3.5" : "rounded-xl bg-black/15 p-3"}>
      <p className="text-[9px] font-black uppercase tracking-wider text-neutral-600">
        {label}
      </p>
      <p
        className={`mt-1.5 truncate text-xs font-black ${valueClass || "text-white"}`}
        title={value}
      >
        {liveValue !== undefined ? (
          <LiveValue value={liveValue} toneBySign={Boolean(valueClass)}>
            {value}
          </LiveValue>
        ) : (
          value
        )}
      </p>
    </div>
  );
}

function PerformanceCard({
  label,
  value,
  positive,
  className = "",
}: {
  label: string;
  value: string;
  positive?: boolean;
  className?: string;
}) {
  return (
    <div className={`rounded-2xl border border-white/8 bg-black/15 p-4 ${className}`}>
      <p className="text-[10px] font-black uppercase tracking-wider text-neutral-600">
        {label}
      </p>
      <p
        className={`mt-2 truncate text-xl font-black ${
          positive === true
            ? "text-emerald-300"
            : positive === false
              ? "text-red-300"
              : "text-white"
        }`}
        title={value}
      >
        {value}
      </p>
    </div>
  );
}

function PeriodSelector({
  value,
  onChange,
}: {
  value: Period;
  onChange: (period: Period) => void;
}) {
  return (
    <div className="flex max-w-full gap-1 overflow-x-auto rounded-xl border border-white/8 bg-black/15 p-1">
      {(Object.keys(PERIOD_LABELS) as Period[]).map((period) => (
        <FilterButton
          key={period}
          selected={value === period}
          onClick={() => onChange(period)}
        >
          {PERIOD_LABELS[period]}
        </FilterButton>
      ))}
    </div>
  );
}

function FilterButton({
  selected,
  onClick,
  children,
}: {
  key?: string;
  selected: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`min-h-9 shrink-0 rounded-lg px-3 text-[10px] font-black transition ${
        selected
          ? "bg-fuchsia-300/12 text-fuchsia-100"
          : "text-neutral-500 hover:bg-white/[0.035] hover:text-neutral-200"
      }`}
    >
      {children}
    </button>
  );
}

function LeaderboardCard({
  item,
  rank,
  onInspect,
  onApply,
}: {
  key?: string;
  item: LeaderboardItem;
  rank: number;
  onInspect: () => void;
  onApply: () => void;
}) {
  const pnl = finite(item.profit_pct);
  const dynamicEnabled = item.dynamic_mode?.enabled === true;
  const dynamicActive = item.dynamic_mode?.active === true;
  return (
    <article className="min-w-[78vw] max-w-[300px] snap-start rounded-2xl border border-white/8 bg-white/[0.025] p-4 sm:min-w-[260px]">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <CoinLogo symbol={item.symbol} size={40} />
          <div>
            <p className="text-sm font-black text-white">{item.symbol}</p>
            <p className="mt-1 text-[10px] font-bold text-neutral-600">
              Trailing DCA
            </p>
          </div>
        </div>
        <span className="grid h-7 w-7 place-items-center rounded-full bg-fuchsia-300/[0.08] text-[10px] font-black text-fuchsia-200">
          {rank}
        </span>
      </div>
      <p
        className={`mt-5 text-2xl font-black ${
          pnl >= 0 ? "text-emerald-300" : "text-red-300"
        }`}
      >
        {pnl >= 0 ? "+" : ""}
        {pnl.toFixed(2)}%
      </p>
      <div className="mt-4 grid grid-cols-2 gap-2">
        <MiniValue
          label="Çalışma süresi"
          value={elapsedSince(item.running_since_iso)}
        />
        <MiniValue
          label="Tamamlanan tur"
          value={String(Math.max(0, Math.round(finite(item.cycles_count))))}
        />
      </div>
      <div className="mt-2 flex items-center justify-between rounded-xl border border-white/8 bg-black/15 px-3 py-2">
        <span className="text-[9px] font-black uppercase tracking-wider text-neutral-600">
          Dinamik mod
        </span>
        <span
          className={`rounded-full px-2 py-1 text-[9px] font-black ${
            dynamicActive
              ? "bg-emerald-300/[0.08] text-emerald-200"
              : dynamicEnabled
                ? "bg-amber-300/[0.08] text-amber-200"
                : "bg-white/5 text-neutral-500"
          }`}
        >
          {dynamicActive ? "Aktif" : dynamicEnabled ? "Açık · bekliyor" : "Kapalı"}
        </span>
      </div>
      <div className="mt-4 grid grid-cols-2 gap-2">
        <button
          type="button"
          onClick={onInspect}
          className="min-h-10 rounded-xl border border-white/8 bg-white/[0.035] text-[10px] font-black text-neutral-300"
        >
          İncele
        </button>
        <button
          type="button"
          onClick={onApply}
          className="min-h-10 rounded-xl border border-fuchsia-300/15 bg-fuchsia-300/[0.07] text-[10px] font-black text-fuchsia-100"
        >
          Botlara taşı
        </button>
      </div>
    </article>
  );
}

function MobileTradeCard({ trade }: { key?: string; trade: Trade }) {
  const side = String(trade.side || "");
  const buy = side.toUpperCase() === "BUY";
  const sell = side.toUpperCase() === "SELL";
  const quantity = finite(trade.executed_qty ?? trade.qty);
  const price = finite(trade.avg_price ?? trade.price);
  const total = finite(trade.quote_qty) || quantity * price;
  return (
    <article className="px-4 py-3.5">
      <div className="flex items-center gap-3">
        <CoinLogo symbol={trade.symbol} size={34} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <p className="truncate text-sm font-black text-white">
              {trade.symbol}
            </p>
            <span
              className={`rounded-full px-2 py-0.5 text-[9px] font-black ${
                buy
                  ? "bg-emerald-300/[0.07] text-emerald-300"
                  : sell
                    ? "bg-red-300/[0.07] text-red-300"
                    : "bg-white/5 text-neutral-400"
              }`}
            >
              {sideLabel(side)}
            </span>
          </div>
          <p className="mt-1 truncate text-[10px] font-semibold text-neutral-600">
            {formatTime(trade.time)} · {tradeSourceLabel(trade)}
          </p>
        </div>
        <div className="shrink-0 text-right">
          <p className="text-[9px] font-black uppercase tracking-wider text-neutral-600">
            Toplam
          </p>
          <p className="mt-0.5 font-mono text-xs font-black text-white">
            {total > 0 ? money(total) : "—"}
          </p>
        </div>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 pl-[46px] text-[10px] text-neutral-500">
        <span>
          {quantity > 0 ? displayNumber(quantity, 6) : "—"} adet
        </span>
        <span className="text-neutral-700">×</span>
        <span>{price > 0 ? money(price) : "—"}</span>
        {finite(trade.commission) > 0 && (
          <>
            <span className="text-neutral-700">•</span>
            <span>
              Komisyon {displayNumber(trade.commission, 4)}{" "}
              {trade.commission_asset || ""}
            </span>
          </>
        )}
      </div>
    </article>
  );
}

function TransactionPaginationBar({
  pagination,
  onPageChange,
}: {
  pagination: TransactionPagination;
  onPageChange: (page: number) => void;
}) {
  if (pagination.totalPages <= 1) return null;
  return (
    <nav
      aria-label="İşlem geçmişi sayfaları"
      className="flex items-center justify-between gap-3 border-t border-white/8 px-4 py-3 sm:px-5"
    >
      <p className="text-[10px] font-semibold text-neutral-600">
        {pagination.total} işlem · Bölüm {pagination.page}/
        {pagination.totalPages}
      </p>
      <div className="flex items-center gap-2">
        <button
          type="button"
          disabled={pagination.page <= 1}
          onClick={() => onPageChange(pagination.page - 1)}
          aria-label="Önceki işlem bölümü"
          className="grid h-9 w-9 place-items-center rounded-xl border border-white/8 bg-white/[0.03] text-neutral-300 transition hover:bg-white/[0.06] disabled:cursor-not-allowed disabled:opacity-30"
        >
          <ChevronLeft className="h-4 w-4" />
        </button>
        <span
          className="min-w-16 text-center text-[10px] font-black text-neutral-400"
          aria-live="polite"
        >
          {pagination.page} / {pagination.totalPages}
        </span>
        <button
          type="button"
          disabled={pagination.page >= pagination.totalPages}
          onClick={() => onPageChange(pagination.page + 1)}
          aria-label="Sonraki işlem bölümü"
          className="grid h-9 w-9 place-items-center rounded-xl border border-white/8 bg-white/[0.03] text-neutral-300 transition hover:bg-white/[0.06] disabled:cursor-not-allowed disabled:opacity-30"
        >
          <ChevronRight className="h-4 w-4" />
        </button>
      </div>
    </nav>
  );
}

function DesktopTradeRow({ trade }: { key?: string; trade: Trade }) {
  const side = String(trade.side || "");
  const buy = side.toUpperCase() === "BUY";
  const sell = side.toUpperCase() === "SELL";
  const commissionUsd =
    (trade as Trade & { commission_usdt?: number }).commission_usd ??
    (trade as Trade & { commission_usdt?: number }).commission_usdt;
  const quantity = finite(trade.executed_qty ?? trade.qty);
  const price = finite(trade.avg_price ?? trade.price);
  const total = finite(trade.quote_qty) || quantity * price;
  return (
    <tr className="transition hover:bg-white/[0.025]">
      <td className="whitespace-nowrap px-5 py-3.5 text-xs text-neutral-500">
        {formatTime(trade.time)}
      </td>
      <td className="px-5 py-3.5">
        <span className="flex items-center gap-2 font-black text-white">
          <CoinLogo symbol={trade.symbol} size={28} />
          {trade.symbol}
        </span>
      </td>
      <td
        className={`px-5 py-3.5 text-xs font-black ${
          buy
            ? "text-emerald-300"
            : sell
              ? "text-red-300"
              : "text-neutral-400"
        }`}
      >
        {sideLabel(side)}
      </td>
      <td className="px-5 py-3.5 text-right font-mono text-xs text-neutral-300">
        {quantity > 0 ? displayNumber(quantity, 6) : "—"}
      </td>
      <td className="px-5 py-3.5 text-right font-mono text-xs text-neutral-300">
        {price > 0 ? money(price) : "—"}
      </td>
      <td className="px-5 py-3.5 text-right text-xs font-black text-white">
        {total > 0 ? money(total) : "—"}
      </td>
      <td className="px-5 py-3.5 text-right text-xs text-neutral-500">
        {finite(trade.commission) > 0
          ? `${displayNumber(trade.commission, 4)} ${trade.commission_asset || ""}${finite(commissionUsd) ? ` · ${money(commissionUsd)}` : ""}`
          : "—"}
      </td>
      <td className="px-5 py-3.5 text-right">
        <span className="rounded-full bg-white/5 px-2 py-1 text-[9px] font-black text-neutral-500">
          {tradeSourceLabel(trade)}
        </span>
      </td>
    </tr>
  );
}

function EmptyState({
  icon: Icon,
  title,
  detail,
}: {
  icon: LucideIcon;
  title: string;
  detail: string;
}) {
  return (
    <div className="mx-4 mb-5 grid min-h-40 place-items-center rounded-2xl border border-dashed border-white/8 bg-black/10 p-6 text-center sm:mx-5">
      <div className="max-w-sm">
        <Icon className="mx-auto h-5 w-5 text-fuchsia-200" />
        <p className="mt-3 text-sm font-black text-white">{title}</p>
        <p className="mt-1 text-xs leading-5 text-neutral-500">{detail}</p>
      </div>
    </div>
  );
}

function LeaderboardDialog({
  item,
  onClose,
  onApply,
}: {
  item: LeaderboardItem;
  onClose: () => void;
  onApply: () => void;
}) {
  const pnl = finite(item.profit_pct);
  const strategy = parseTemplateStrategy(item.params);
  const referencePrice =
    optionalNumber(item.reference_price) ?? strategy.referencePrice;
  const pair = splitTradingSymbol(item.symbol);
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    const previousFocus = document.activeElement as HTMLElement | null;
    const focusFrame = window.requestAnimationFrame(() => closeButtonRef.current?.focus());
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.cancelAnimationFrame(focusFrame);
      window.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
      previousFocus?.focus();
    };
  }, [onClose]);
  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-black/80 p-3 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="leaderboard-dialog-title"
    >
      <section className="max-h-[calc(100dvh-1.5rem)] w-full max-w-3xl overflow-y-auto rounded-[1.5rem] border border-fuchsia-300/15 bg-[#191a20] shadow-[0_35px_120px_rgba(0,0,0,.65)]">
        <header className="sticky top-0 z-10 flex items-center justify-between gap-3 border-b border-white/8 bg-[#191a20]/95 p-4 backdrop-blur sm:p-5">
          <div className="flex min-w-0 items-center gap-3">
            <CoinLogo symbol={item.symbol} size={48} eager />
            <div className="min-w-0">
              <p className="text-[9px] font-black uppercase tracking-wider text-fuchsia-200">
                Şablon ayrıntısı
              </p>
              <h2
                id="leaderboard-dialog-title"
                className="mt-1 truncate text-base font-black text-white"
              >
                {pair.label} strateji planı
              </h2>
              <p className="mt-1 text-[10px] font-semibold text-neutral-500">
                {strategy.strategyLabel} · Bot oluşturucuya hazır strateji
              </p>
            </div>
          </div>
          <button
            ref={closeButtonRef}
            type="button"
            onClick={onClose}
            aria-label="Şablon penceresini kapat"
            className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-white/8 text-neutral-400 focus:outline-none focus:ring-2 focus:ring-fuchsia-300/70"
          >
            <X className="h-4 w-4" />
          </button>
        </header>
        <div className="space-y-4 p-4 sm:p-5">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <PerformanceCard
              label="Net K/Z"
              value={`${pnl >= 0 ? "+" : ""}${pnl.toFixed(2)}%`}
              positive={pnl >= 0}
            />
            <PerformanceCard
              label="Referans fiyat"
              value={templatePrice(referencePrice)}
            />
            <PerformanceCard
              label="Başlangıç dengesi"
              value={`${templatePct(strategy.basePct)} coin · ${templatePct(strategy.quotePct)} nakit`}
            />
          </div>

          <TemplatePlainSummary symbol={pair.base} strategy={strategy} />

          <TemplateAllocation
            symbol={pair.base}
            quote={pair.quote}
            basePct={strategy.basePct}
            quotePct={strategy.quotePct}
          />

          <div className="grid gap-3 lg:grid-cols-2">
            <TemplateGridPlan
              side="sell"
              grids={strategy.sellGrids}
              trail={strategy.upTrail}
            />
            <TemplateGridPlan
              side="buy"
              grids={strategy.buyGrids}
              trail={strategy.downTrail}
            />
          </div>

          <TemplateProfitCycle strategy={strategy} />

          <div className="grid grid-cols-2 gap-2">
            <button
              type="button"
              onClick={onClose}
              className="min-h-11 rounded-xl border border-white/8 text-xs font-black text-neutral-300"
            >
              Kapat
            </button>
            <button
              type="button"
              onClick={onApply}
              className="min-h-11 rounded-xl border border-fuchsia-300/15 bg-fuchsia-300/[0.08] text-xs font-black text-fuchsia-100"
            >
              Bu değerler ile Bot Başlat
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}

function TemplatePlainSummary({
  symbol,
  strategy,
}: {
  symbol: string;
  strategy: TemplateStrategy;
}) {
  const sellTriggers = strategy.sellGrids
    .map((grid) => templatePct(grid.triggerPct))
    .join(", ");
  const buyTriggers = strategy.buyGrids
    .map((grid) => templatePct(grid.triggerPct))
    .join(", ");
  return (
    <section className="rounded-2xl border border-fuchsia-300/12 bg-gradient-to-br from-fuchsia-300/[0.065] to-transparent p-4">
      <p className="flex items-center gap-2 text-xs font-black text-white">
        <Info className="h-4 w-4 text-fuchsia-200" />
        Bu şablon ne yapıyor?
      </p>
      <p className="mt-2 text-xs leading-6 text-neutral-400">
        Başlangıçta sermayenin{" "}
        <strong className="text-fuchsia-100">
          {templatePct(strategy.basePct)}
        </strong>{" "}
        kadarı {symbol},{" "}
        <strong className="text-sky-200">
          {templatePct(strategy.quotePct)}
        </strong>{" "}
        kadarı base dağılımı için korunur.
        {strategy.sellGrids.length > 0 &&
          ` Fiyat referansın ${sellTriggers} üzerine çıktığında satış seviyeleri izlenir.`}
        {strategy.buyGrids.length > 0 &&
          ` Fiyat referansın ${buyTriggers} altına indiğinde alış seviyeleri izlenir.`}{" "}
        Emir, tetik görüldüğü anda değil; trailing dönüşü doğrulandığında
        uygulanır.
      </p>
    </section>
  );
}

function TemplateAllocation({
  symbol,
  quote,
  basePct,
  quotePct,
}: {
  symbol: string;
  quote: string;
  basePct: number | null;
  quotePct: number | null;
}) {
  const safeBase = Math.max(0, Math.min(100, basePct ?? 0));
  return (
    <section className="rounded-2xl border border-white/8 bg-white/[0.025] p-4">
      <div className="flex items-center justify-between gap-3">
        <p className="flex items-center gap-2 text-xs font-black text-white">
          <WalletCards className="h-4 w-4 text-fuchsia-200" />
          Başlangıç dağılımı
        </p>
        <span className="text-[10px] font-black text-neutral-500">
          Toplam %{finite(basePct) + finite(quotePct)}
        </span>
      </div>
      <div className="mt-3 flex h-3 overflow-hidden rounded-full bg-white/5">
        <div
          className="bg-gradient-to-r from-fuchsia-400 to-violet-400"
          style={{ width: `${safeBase}%` }}
        />
        <div className="flex-1 bg-gradient-to-r from-sky-400 to-cyan-300" />
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2">
        <TemplateSmallValue
          label={`${symbol} · coin`}
          value={templatePct(basePct)}
          tone="violet"
        />
        <TemplateSmallValue
          label={`${quote} · base dağılımı`}
          value={templatePct(quotePct)}
          tone="blue"
        />
      </div>
    </section>
  );
}

function TemplateGridPlan({
  side,
  grids,
  trail,
}: {
  side: "buy" | "sell";
  grids: TemplateGrid[];
  trail: number | null;
}) {
  const sell = side === "sell";
  const Icon = sell ? ArrowUpRight : ArrowDownRight;
  return (
    <section
      className={`overflow-hidden rounded-2xl border ${
        sell
          ? "border-emerald-300/12 bg-emerald-300/[0.025]"
          : "border-sky-300/12 bg-sky-300/[0.025]"
      }`}
    >
      <header className="border-b border-white/7 p-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p
              className={`flex items-center gap-2 text-xs font-black ${
                sell ? "text-emerald-200" : "text-sky-200"
              }`}
            >
              <Icon className="h-4 w-4" />
              {sell ? "Yukarı Satış Gridleri" : "Aşağı Alış Gridleri"}
            </p>
            <p className="mt-1 text-[10px] leading-5 text-neutral-500">
              {sell
                ? "Tetik sonrası tepeyi izler, geri dönüşte satış yapar."
                : "Tetik sonrası dibi izler, toparlanmada alış yapar."}
            </p>
          </div>
          <span
            className={`shrink-0 rounded-full px-2.5 py-1 text-[9px] font-black ${
              sell
                ? "bg-emerald-300/[0.07] text-emerald-200"
                : "bg-sky-300/[0.07] text-sky-200"
            }`}
          >
            {grids.length} grid · Trailing {templatePct(trail)}
          </span>
        </div>
      </header>
      <div className="space-y-2 p-3">
        {grids.length ? (
          grids.map((grid, index) => (
            <div
              key={`${side}-${index}`}
              className="grid grid-cols-[32px_1fr_auto] items-center gap-3 rounded-xl border border-white/7 bg-black/15 p-2.5"
            >
              <span
                className={`grid h-8 w-8 place-items-center rounded-lg text-[10px] font-black ${
                  sell
                    ? "bg-emerald-300/[0.07] text-emerald-200"
                    : "bg-sky-300/[0.07] text-sky-200"
                }`}
              >
                {index + 1}
              </span>
              <div className="min-w-0">
                <p className="text-[9px] font-black uppercase tracking-wider text-neutral-600">
                  {sell ? "Yükseliş tetiği" : "Düşüş tetiği"}
                </p>
                <p className="mt-1 text-xs font-black text-white">
                  {templatePct(grid.triggerPct)}
                </p>
              </div>
              <div className="text-right">
                <p className="text-[9px] font-black uppercase tracking-wider text-neutral-600">
                  {sell ? "Satış miktarı" : "Alış miktarı"}
                </p>
                <p className="mt-1 text-xs font-black text-neutral-200">
                  {templatePct(grid.qtyPct)}
                </p>
              </div>
            </div>
          ))
        ) : (
          <p className="rounded-xl border border-dashed border-white/8 p-4 text-center text-[10px] text-neutral-600">
            Bu yönde kademe tanımlanmamış.
          </p>
        )}
      </div>
    </section>
  );
}

function TemplateProfitCycle({ strategy }: { strategy: TemplateStrategy }) {
  return (
    <section className="overflow-hidden rounded-2xl border border-amber-300/12 bg-amber-300/[0.025]">
      <header className="border-b border-white/7 p-4">
        <p className="flex items-center gap-2 text-xs font-black text-amber-100">
          <Repeat2 className="h-4 w-4" />
          Kâr sonrası yeniden giriş döngüsü
        </p>
        <p className="mt-1 text-[10px] leading-5 text-neutral-500">
          Satıştan sonra yeniden alış, alıştan sonra yeniden satış koşulları.
        </p>
      </header>
      <div className="grid grid-cols-2 gap-2 p-3 sm:grid-cols-4">
        <TemplateSmallValue
          label="Kâr alışı tetiği"
          value={templatePct(strategy.rebuyTrigger)}
          tone="blue"
        />
        <TemplateSmallValue
          label="Dipten dönüş"
          value={templatePct(strategy.rebuyTrail)}
          tone="violet"
        />
        <TemplateSmallValue
          label="Yeniden satış tetiği"
          value={templatePct(strategy.resellTrigger)}
          tone="green"
        />
        <TemplateSmallValue
          label="Tepeden dönüş"
          value={templatePct(strategy.resellTrail)}
          tone="amber"
        />
      </div>
    </section>
  );
}

function TemplateSmallValue({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "violet" | "blue" | "green" | "amber";
}) {
  const tones = {
    violet: "text-fuchsia-200",
    blue: "text-sky-200",
    green: "text-emerald-200",
    amber: "text-amber-200",
  };
  return (
    <div className="rounded-xl border border-white/7 bg-black/15 p-3">
      <p className="text-[9px] font-black uppercase tracking-wider text-neutral-600">
        {label}
      </p>
      <p className={`mt-1.5 text-xs font-black ${tones[tone]}`}>{value}</p>
    </div>
  );
}
