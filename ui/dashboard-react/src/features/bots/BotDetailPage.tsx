import {
  Activity,
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  BarChart3,
  Bot,
  CheckCircle2,
  CircleDollarSign,
  Gauge,
  Grid3X3,
  Layers3,
  LoaderCircle,
  Play,
  ShieldAlert,
  Sparkles,
  Trash2,
  Target,
  WifiOff,
  Zap,
  X,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import CoinLogo, {
  splitTradingSymbol,
} from "../../components/coin/CoinLogo";
import LiveValue from "../../components/live/LiveValue";
import { ApiError } from "../../lib/api";
import { deleteEngineBot, startEngineBot } from "./api";
import {
  getBotCycles,
  getBotDetail,
  getBotGrid,
  getBotHealth,
  getBotLive,
  getBotPerformance,
  getBotTrades,
  type BotCycles,
  type BotDetail,
  type BotGridData,
  type BotHealth,
  type BotLiveSnapshot,
  type BotPerformance,
  type BotTrade,
  type BotTrades,
} from "./detailApi";

type DetailTab = "summary" | "grid" | "activity";
type MutationName = "start" | "delete";
type PerformancePeriod = "all" | "day" | "week" | "month";

export interface BotDetailPageProps {
  botId: number;
  accountId: number;
  onDeleted: (botId: number) => void;
}

const TABS: Array<{
  id: DetailTab;
  label: string;
  shortLabel: string;
  icon: typeof Bot;
}> = [
  { id: "summary", label: "Özet", shortLabel: "Özet", icon: Bot },
  { id: "grid", label: "Grid", shortLabel: "Grid", icon: Grid3X3 },
  {
    id: "activity",
    label: "Turlar ve işlemler",
    shortLabel: "İşlemler",
    icon: CircleDollarSign,
  },
];

const STATUS_LABELS: Record<string, string> = {
  running: "Çalışıyor",
  starting: "Başlatılıyor",
  stopping: "Durduruluyor",
  waiting: "İlk alım bekleniyor",
  stopped: "Durduruldu",
  error: "Hata",
  deleted: "Silindi",
};

const MAIN_REGIME_LABELS: Record<string, string> = {
  R1: "Güçlü yükseliş var",
  R2: "Piyasa dengeli",
  R3: "Piyasa kararsız",
  R4: "Sert dalgalanma var",
  R5: "Toparlanma başlıyor",
  R6: "Yavaş toparlanma var",
  R7: "Düşüş eğilimi var",
  R8: "Sert düşüş var",
};

const MAIN_REGIME_DETAILS: Record<string, string> = {
  R1: "Trend yukarı ve momentum güçlü. Bu turda satış kademeleri öne çıkar; alışlar daha seçici tutulur.",
  R2: "Belirgin yön yok; fiyat dengeli bir bantta. Alış ve satış gridleri simetrik ve orta genişlikte çalışır.",
  R3: "Yön belirsiz, gürültü yüksek. Gridler biraz açılır; sahte kırılımlara karşı daha temkinli plan uygulanır.",
  R4: "Volatilite yüksek. Seviyeler daha geniş tutulur; sermaye uzak kademelerde beklemeye bırakılmaz.",
  R5: "Düşüş sonrası toparlanma sinyali var. Yakın alışlar değerlendirilir; satışlar erişilebilir tepelere yerleştirilir.",
  R6: "Toparlanma daha kontrollü ilerliyor. Dağılım dengelenir; aceleci alış yerine kademeli plan korunur.",
  R7: "Ana eğilim aşağı. Alışlar derinleştirilir veya koşullu tutulur; satış yönetimi önceliklidir.",
  R8: "Sert düşüş / riskli rejim. Uygulanabilir plan yoksa yeni tur açılmaz; güvenli rejim gelene kadar beklenir.",
};

function mainRegimeCode(value: string): string | null {
  const raw = value.trim();
  const code = raw.toUpperCase().match(/\bR[1-8]\b/)?.[0];
  if (code) return code;
  const lower = raw.toLocaleLowerCase("tr-TR");
  if (lower.includes("sert düş") || lower.includes("crash")) return "R8";
  if (lower.includes("düşüş")) return "R7";
  if (lower.includes("yavaş topar")) return "R6";
  if (lower.includes("toparlan") || lower.includes("kırılım") || lower.includes("breakout"))
    return "R5";
  if (lower.includes("dalgalan") || lower.includes("volatil")) return "R4";
  if (lower.includes("kararsız") || lower.includes("gürültü")) return "R3";
  if (lower.includes("dengeli") || lower.includes("yatay") || lower.includes("sakin")) return "R2";
  if (lower.includes("yükseliş") || lower.includes("güçlü")) return "R1";
  return null;
}

function shortMainRegime(value: string): string {
  const raw = value.trim();
  const code = mainRegimeCode(raw);
  if (code && MAIN_REGIME_LABELS[code]) return MAIN_REGIME_LABELS[code];
  const lower = raw.toLocaleLowerCase("tr-TR");
  if (lower.includes("sert düş") || lower.includes("crash")) return "Sert düşüş var";
  if (lower.includes("düşüş")) return "Düşüş eğilimi var";
  if (lower.includes("toparlan")) return "Toparlanma başlıyor";
  if (lower.includes("yükseliş")) return "Güçlü yükseliş var";
  if (lower.includes("volatil") || lower.includes("dalgal")) {
    return "Sert dalgalanma var";
  }
  if (lower.includes("gürült") || lower.includes("kararsız")) {
    return "Piyasa kararsız";
  }
  if (lower.includes("dengeli") || lower.includes("yatay")) return "Piyasa dengeli";
  return raw.split(/\s+/).slice(0, 4).join(" ") || "—";
}

function explainMainRegime(value: string): string {
  const code = mainRegimeCode(value);
  if (code && MAIN_REGIME_DETAILS[code]) return MAIN_REGIME_DETAILS[code];
  return "Motor bu tur için piyasa yapısını okudu; aşağıdaki parametreler bu okumaya göre uygulandı.";
}

function toFiniteNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function readNumber(
  record: Record<string, unknown>,
  keys: string[],
): number | null {
  for (const key of keys) {
    const value = toFiniteNumber(record[key]);
    if (value !== null) return value;
  }
  return null;
}

function readText(
  record: Record<string, unknown>,
  keys: string[],
): string | null {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "string" && value.trim()) return value;
    if (typeof value === "number") return String(value);
  }
  return null;
}

function money(value: unknown, digits = 2): string {
  const number = toFiniteNumber(value);
  if (number === null) return "—";
  return new Intl.NumberFormat("tr-TR", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(number);
}

function decimal(value: unknown, digits = 4): string {
  const number = toFiniteNumber(value);
  if (number === null) return "—";
  return new Intl.NumberFormat("tr-TR", {
    maximumFractionDigits: digits,
  }).format(number);
}

function coinPrice(value: unknown): string {
  const number = toFiniteNumber(value);
  if (number === null) return "—";
  const absolute = Math.abs(number);
  const maximumFractionDigits =
    absolute >= 1_000
      ? 2
      : absolute >= 100
        ? 3
        : absolute >= 10
          ? 4
          : absolute >= 1
            ? 5
            : absolute >= 0.1
              ? 7
              : absolute >= 0.01
                ? 8
                : 10;
  return new Intl.NumberFormat("tr-TR", {
    minimumFractionDigits: 0,
    maximumFractionDigits,
  }).format(number);
}

function assetQuantity(value: unknown): string {
  const number = toFiniteNumber(value);
  if (number === null) return "—";
  const absolute = Math.abs(number);
  const digits =
    absolute >= 1_000
      ? 2
      : absolute >= 100
        ? 3
        : absolute >= 10
          ? 4
          : absolute >= 1
            ? 4
            : absolute >= 0.1
              ? 5
              : absolute >= 0.01
                ? 6
                : 8;
  return new Intl.NumberFormat("tr-TR", {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  }).format(number);
}

function quoteAmount(value: unknown): string {
  const number = toFiniteNumber(value);
  if (number === null) return "—";
  const absolute = Math.abs(number);
  return decimal(number, absolute >= 10 ? 4 : absolute >= 1 ? 5 : 6);
}

function heroBalance(value: unknown, asset: string): string {
  const number = toFiniteNumber(value);
  if (number === null) return "—";
  const quoteLike = /^(USDT|USDC|BUSD|FDUSD|TUSD)$/i.test(asset.trim());
  if (quoteLike) {
    const absolute = Math.abs(number);
    const digits = absolute >= 100 ? 2 : absolute >= 1 ? 3 : 4;
    return new Intl.NumberFormat("tr-TR", {
      minimumFractionDigits: 0,
      maximumFractionDigits: digits,
    }).format(number);
  }
  return assetQuantity(number);
}

function percent(value: unknown): string {
  const number = toFiniteNumber(value);
  if (number === null) return "—";
  return `${number > 0 ? "+" : ""}${decimal(number, 2)}%`;
}

function metricTone(value: unknown): "positive" | "negative" | undefined {
  const number = toFiniteNumber(value);
  if (number === null) return undefined;
  return number >= 0 ? "positive" : "negative";
}

function dateTime(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  const raw =
    typeof value === "number" && value < 10_000_000_000 ? value * 1000 : value;
  const date = new Date(raw as string | number);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("tr-TR", {
    dateStyle: "short",
    timeStyle: "medium",
  }).format(date);
}

function dateTimeMinute(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  const raw =
    typeof value === "number" && value < 10_000_000_000 ? value * 1000 : value;
  const date = new Date(raw as string | number);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("tr-TR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function ageInSeconds(value: unknown): number | null {
  if (value === null || value === undefined) return null;
  const raw =
    typeof value === "number" && value < 10_000_000_000 ? value * 1000 : value;
  const time = new Date(raw as string | number).getTime();
  return Number.isFinite(time) ? Math.max(0, (Date.now() - time) / 1000) : null;
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

function humanize(value: string): string {
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

const PARAMETER_LABELS: Record<string, string> = {
  base_alloc_pct: "Base dağılımı",
  quote_alloc_pct: "Quote dağılımı",
  buy_trigger_trailing_pct: "Alış trailing",
  sell_trigger_trailing_pct: "Satış trailing",
  profit_reentry_drop_pct: "Kâr alışı tetiği",
  profit_reentry_rise_pct: "Kâr alışı trailing",
  profit_exit_rise_pct: "Kâr satışı tetiği",
  profit_exit_drop_pct: "Kâr satışı trailing",
  max_buy_levels: "Azami alış seviyesi",
  max_slippage_pct: "Azami kayma",
  min_notional_guard: "Minimum işlem tutarı",
};

function parameterLabel(key: string): string {
  return PARAMETER_LABELS[key] || humanize(key);
}

function parameterDisplay(key: string, value: unknown): string {
  if (typeof value === "boolean") return value ? "Açık" : "Kapalı";
  const number = toFiniteNumber(value);
  if (number === null) return String(value);
  if (
    key.endsWith("_pct") ||
    key.includes("_alloc_") ||
    key.includes("trailing")
  ) {
    return `%${decimal(number, 3)}`;
  }
  if (key.includes("notional")) return `${quoteAmount(number)} USDT`;
  return decimal(number, 4);
}

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function objectList(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.filter(
        (item): item is Record<string, unknown> =>
          Boolean(item) && typeof item === "object" && !Array.isArray(item),
      )
    : [];
}

function strategyGridList(
  params: Record<string, unknown>,
  side: "buy" | "sell",
): Record<string, unknown>[] {
  const direct = objectList(params[`${side}_grids`]);
  if (direct.length) return direct;
  const nested = objectValue(params[side === "sell" ? "up" : "down"]);
  return objectList(nested.grids);
}

function parameterValue(
  params: Record<string, unknown>,
  keys: string[],
): number | null {
  const direct = readNumber(params, keys);
  if (direct !== null) return direct;
  const allocation = objectValue(params.allocation);
  const allocationValue = readNumber(allocation, keys);
  if (allocationValue !== null) return allocationValue;
  const primaryKey = keys[0];
  const nestedMap: Record<string, [string, string]> = {
    buy_trigger_trailing_pct: ["down", "trail_pct"],
    sell_trigger_trailing_pct: ["up", "trail_pct"],
    profit_reentry_drop_pct: ["profit", "rebuy_trigger_pct"],
    profit_reentry_rise_pct: ["profit", "rebuy_trail_pct"],
    profit_exit_rise_pct: ["profit", "resell_trigger_pct"],
    profit_exit_drop_pct: ["profit", "resell_trail_pct"],
  };
  const nestedPath = nestedMap[primaryKey];
  if (!nestedPath) return null;
  return readNumber(objectValue(params[nestedPath[0]]), [nestedPath[1]]);
}

function gridParameterValue(
  grid: Record<string, unknown>,
  side: "buy" | "sell",
  kind: "trigger" | "quantity",
): number | null {
  return readNumber(
    grid,
    kind === "trigger"
      ? [side === "buy" ? "buy_grid_pct" : "sell_grid_pct", "trigger_pct"]
      : [
          side === "buy" ? "buy_qty_pct_of_quote" : "sell_qty_pct_of_base",
          "qty_pct",
        ],
  );
}

function ratioMultiplier(current: number | null, baseline: number | null): number | null {
  if (current === null || baseline === null || Math.abs(baseline) < 1e-9) return null;
  return current / baseline;
}

function multiplierLabel(value: unknown): string | null {
  const number = toFiniteNumber(value);
  if (number === null) return null;
  return `×${decimal(number, 3)}`;
}

function deepText(
  value: unknown,
  keys: string[],
  depth = 0,
): string | null {
  if (!value || typeof value !== "object" || depth > 5) return null;
  const record = value as Record<string, unknown>;
  for (const key of keys) {
    const candidate = record[key];
    if (
      (typeof candidate === "string" || typeof candidate === "number") &&
      String(candidate).trim()
    ) {
      return String(candidate).trim();
    }
  }
  for (const child of Object.values(record)) {
    const found = deepText(child, keys, depth + 1);
    if (found) return found;
  }
  return null;
}

type GridPhase = "waiting" | "triggered" | "trailing" | "completed" | "disabled";
type GridSide = "buy" | "sell" | "profit";

function gridPointSide(point: Record<string, unknown>, fallback = "grid"): GridSide {
  const raw = String(
    point.side || point.type || point.kind || point.grid_type || fallback,
  ).toLowerCase();
  if (
    raw.includes("buy") ||
    raw.includes("down") ||
    raw.includes("reentry") ||
    raw.includes("alış")
  ) {
    return raw.includes("reentry") ? "profit" : "buy";
  }
  if (
    raw.includes("sell") ||
    raw.includes("up") ||
    raw.includes("profit") ||
    raw.includes("satış")
  ) {
    return raw.includes("profit") ? "profit" : "sell";
  }
  return fallback === "profit" ? "profit" : "sell";
}

function gridPointPhase(point: Record<string, unknown>): GridPhase {
  const raw = String(point.status || point.state || "").toLowerCase();
  if (
    point.enabled === false ||
    point.disabled === true ||
    raw.includes("disabled") ||
    raw.includes("devre")
  ) {
    return "disabled";
  }
  if (
    point.completed === true ||
    point.filled === true ||
    point.executed === true ||
    point.is_filled === true ||
    raw.includes("complete") ||
    raw.includes("tamam") ||
    raw.includes("filled")
  ) {
    return "completed";
  }
  if (raw.includes("waiting") || raw.includes("pending") || raw.includes("bekli")) {
    return "waiting";
  }
  if (point.fired === false && point.active === false) {
    return "waiting";
  }
  if (
    point.active === true ||
    raw.includes("trail") ||
    raw.includes("izle")
  ) {
    return "trailing";
  }
  if (
    point.fired === true ||
    point.trigger_hit === true ||
    raw.includes("trigger") ||
    raw.includes("tetik")
  ) {
    return "triggered";
  }
  return "waiting";
}

const GRID_PHASE_LABELS: Record<GridPhase, string> = {
  waiting: "Tetik bekleniyor",
  triggered: "Tetiklendi",
  trailing: "Trailing izliyor",
  completed: "Tamamlandı",
  disabled: "Devre dışı",
};

function gridDirectionLabel(raw: string | null): string {
  const value = String(raw || "").toLowerCase();
  if (value.includes("down") || value.includes("buy") || value.includes("dca")) {
    return "Alış Gridler Aktif";
  }
  if (value.includes("up") || value.includes("sell") || value.includes("trb")) {
    return "Satış Gridler Aktif";
  }
  if (value.includes("both") || value.includes("dual")) {
    return "İki yön açık · ilk tamamlanan grid bekleniyor";
  }
  return "İki yön açık · ilk tamamlanan grid bekleniyor";
}

function readableDuration(value: unknown): string {
  const seconds = toFiniteNumber(value);
  if (seconds === null || seconds < 0) return "—";
  if (seconds < 60) return `${Math.floor(seconds)} sn`;
  const minutes = Math.max(1, Math.floor(seconds / 60));
  if (minutes < 60) return `${minutes} dk`;
  const hours = Math.floor(minutes / 60);
  const remainderMinutes = minutes % 60;
  if (hours < 24) return `${hours} sa${remainderMinutes ? ` ${remainderMinutes} dk` : ""}`;
  const days = Math.floor(hours / 24);
  const remainderHours = hours % 24;
  if (days < 30) return `${days} gün${remainderHours ? ` ${remainderHours} sa` : ""}`;
  const months = Math.floor(days / 30);
  const remainderDays = days % 30;
  return `${months} ay${remainderDays ? ` ${remainderDays} gün` : ""}`;
}

function tradeReasonTitle(trade: BotTrade, initial = false): string {
  if (initial) return "Başlangıç base alımı";
  const side = String(trade.side || "").toUpperCase();
  const gridDetail = objectValue(trade.grid_detail);
  const tradeDetail = objectValue(trade.trade_detail);
  const gridIndex = toFiniteNumber(gridDetail.grid_index);
  if (gridIndex !== null) {
    return `${gridIndex + 1}. ${side === "SELL" ? "satış" : "alış"} gridi`;
  }
  const detailLabel = readText(tradeDetail, ["label"]);
  if (detailLabel) return detailLabel;
  const reason = String(trade.reason || "").toLowerCase();
  const labels: Record<string, string> = {
    trail_sell_grid: "Grid satışı",
    trail_buy_grid: "Grid alışı",
    trail_profit_sell: "Kâr satışı",
    trail_reentry_buy: "Kâr alışı",
    initial_allocation: "Başlangıç base alımı",
  };
  return labels[reason] || (side === "SELL" ? "Base satışı" : "Base alışı");
}

function tradePercentLabel(value: unknown, side: string): string {
  const percent = toFiniteNumber(value);
  if (percent === null) return "";
  const sign = side === "BUY" ? "−" : "+";
  return `${sign}%${decimal(Math.abs(percent), 3)}`;
}

function TradeActivityCard({
  trade,
  pair,
  initial = false,
}: {
  trade: BotTrade;
  pair: { base: string; quote: string };
  initial?: boolean;
}) {
  const side = String(trade.side || "").toUpperCase();
  const sell = side === "SELL";
  const gridDetail = objectValue(trade.grid_detail);
  const closeDetail = objectValue(trade.trade_detail);
  const detail = Object.keys(gridDetail).length ? gridDetail : closeDetail;
  const triggerPct = detail.grid_pct ?? detail.trigger_pct;
  const trailingPct = detail.trailing_pct;
  const triggerPrice = detail.trigger_level_price ?? detail.trigger_price;
  const extremePrice =
    detail.extreme_price ?? (sell ? detail.tepe_price : detail.dip_price);
  const completionPrice =
    detail.execution_price ?? detail.fill_price ?? trade.price;
  const referencePrice = detail.reference_price ?? trade.reference_price;
  const quantityPercent = detail.qty_pct;
  const extremePct = detail.extreme_pct_from_reference;
  const completionReferencePct = detail.completion_pct_from_reference;
  const completionCostPct = closeDetail.completion_pct_from_cost;
  const completionExtremePct = detail.completion_pct_from_extreme;
  const averageCost = closeDetail.average_cost;
  const closeTrade = Object.keys(closeDetail).length > 0;
  const total =
    toFiniteNumber(trade.qty) !== null && toFiniteNumber(trade.price) !== null
      ? Number(trade.qty) * Number(trade.price)
      : null;
  const feeAsset = String(trade.fee_asset || pair.quote).toUpperCase();
  const storedRawFee =
    toFiniteNumber(trade.fee_raw) ?? toFiniteNumber(trade.fee_amount);
  const feeUsdt =
    toFiniteNumber(trade.fee_usdt) ?? toFiniteNumber(trade.fee);
  const displayedFee =
    storedRawFee ??
    (feeAsset === pair.quote.toUpperCase()
      ? feeUsdt
      : feeUsdt !== null &&
          toFiniteNumber(trade.price) !== null &&
          Number(trade.price) > 0
        ? feeUsdt / Number(trade.price)
        : toFiniteNumber(trade.fee));
  const completionDirection = sell ? "tepeden" : "dipten";
  const completionSign = sell ? "−" : "+";
  const reason = tradeReasonTitle(trade, initial);

  return (
    <article className={`rounded-2xl border p-4 ${initial ? "border-emerald-300/15 bg-emerald-300/[0.035]" : sell ? "border-red-300/15 bg-red-300/[0.03]" : "border-emerald-300/15 bg-emerald-300/[0.03]"}`}>
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`rounded-full px-2.5 py-1 text-[9px] font-black uppercase tracking-[0.12em] ${sell ? "bg-red-300/10 text-red-200" : "bg-emerald-300/10 text-emerald-200"}`}>
              {sell ? "Satış" : "Alış"}
            </span>
            <h3 className="text-sm font-black text-white">{reason}</h3>
          </div>
          <p className="mt-1.5 text-[10px] text-neutral-500">{dateTime(trade.ts)}</p>
        </div>
        {!initial && toFiniteNumber(quantityPercent) !== null && (
          <span className="shrink-0 rounded-lg border border-white/8 bg-white/[0.035] px-2 py-1 text-[9px] font-black text-neutral-300">
            Pay %{decimal(quantityPercent, 2)}
          </span>
        )}
      </header>

      <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <MiniGridValue label={`Miktar · ${pair.base}`} value={assetQuantity(trade.qty)} />
        <MiniGridValue label={`İşlem fiyatı · ${pair.quote}`} value={coinPrice(trade.price)} />
        <MiniGridValue label={`İşlem toplamı · ${pair.quote}`} value={quoteAmount(total)} />
        <MiniGridValue
          label="Komisyon"
          value={`${assetQuantity(displayedFee)} ${feeAsset}`.trim()}
        />
      </div>

      {!initial && closeTrade && toFiniteNumber(averageCost) !== null && (
        <div className="mt-3 rounded-xl border border-fuchsia-300/12 bg-fuchsia-300/[0.045] p-3">
          <p className="text-[9px] font-black uppercase tracking-wider text-fuchsia-200/70">
            {sell ? "Ağırlıklı ort. alış maliyeti" : "Ağırlıklı ort. satış maliyeti"}
          </p>
          <p className="mt-1 font-mono text-sm font-black text-fuchsia-100">
            {coinPrice(averageCost)} {pair.quote}
          </p>
          <p className="mt-1 text-[9px] leading-4 text-neutral-500">
            Bu turdaki grid işlemlerinin fiyatı, gerçekleşen miktarıyla ağırlıklandırılır.
          </p>
        </div>
      )}

      {!initial && Object.keys(detail).length > 0 && (
        <div className="mt-3 grid gap-2 sm:grid-cols-3">
          <div className="rounded-xl border border-white/7 bg-black/15 p-3">
            <p className="text-[9px] font-black uppercase tracking-wider text-neutral-600">
              Tetik noktası {tradePercentLabel(triggerPct, side)}
            </p>
            <p className="mt-1 font-mono text-xs font-black text-white">
              {coinPrice(triggerPrice)} {pair.quote}
            </p>
            {closeTrade && toFiniteNumber(averageCost) !== null ? (
              <p className="mt-1 text-[9px] text-neutral-500">
                Ort. maliyet {coinPrice(averageCost)} {pair.quote}
              </p>
            ) : toFiniteNumber(referencePrice) !== null ? (
              <p className="mt-1 text-[9px] text-neutral-500">
                Referans {coinPrice(referencePrice)} {pair.quote}
              </p>
            ) : null}
          </div>
          <div className="rounded-xl border border-white/7 bg-black/15 p-3">
            <p className="text-[9px] font-black uppercase tracking-wider text-neutral-600">
              {sell ? "Takip tepesi" : "Takip dibi"}{" "}
              {toFiniteNumber(extremePct) === null
                ? ""
                : `· ${Number(extremePct) >= 0 ? "+" : ""}%${decimal(extremePct, 3)}`}
            </p>
            <p className="mt-1 font-mono text-xs font-black text-white">
              {coinPrice(extremePrice)} {pair.quote}
            </p>
            <p className="mt-1 text-[9px] text-neutral-500">
              Tetikten sonra izlenen {sell ? "en yüksek" : "en düşük"} fiyat
            </p>
          </div>
          <div className="rounded-xl border border-white/7 bg-black/15 p-3">
            <p className="text-[9px] font-black uppercase tracking-wider text-neutral-600">
              Tamamlanma ·{" "}
              {toFiniteNumber(completionCostPct ?? completionReferencePct) === null
                ? `${completionDirection} ${completionSign}%${decimal(trailingPct, 3)}`
                : `${Number(completionCostPct ?? completionReferencePct) >= 0 ? "+" : "−"}%${decimal(Math.abs(Number(completionCostPct ?? completionReferencePct)), 3)}`}
            </p>
            <p className="mt-1 font-mono text-xs font-black text-white">
              {coinPrice(completionPrice)} {pair.quote}
            </p>
            <p className="mt-1 text-[9px] text-neutral-500">
              {toFiniteNumber(completionExtremePct) === null
                ? "Emrin gerçekleştiği nokta"
                : `${sell ? "Tepeden" : "Dipten"} ${Number(completionExtremePct) >= 0 ? "+" : "−"}%${decimal(Math.abs(Number(completionExtremePct)), 3)}`}
            </p>
          </div>
        </div>
      )}
    </article>
  );
}

function StatusBadge({ status }: { status: string }) {
  const normalized = status.toLowerCase();
  const active = ["running", "starting", "waiting"].includes(normalized);
  const pending = normalized === "stopping";
  const danger = normalized === "error";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold ${
        danger
          ? "border-red-400/30 bg-red-400/10 text-red-300"
          : active
            ? "border-emerald-400/30 bg-emerald-400/10 text-emerald-300"
            : pending
              ? "border-amber-400/30 bg-amber-400/10 text-amber-300"
            : "border-neutral-700 bg-neutral-800 text-neutral-300"
      }`}
    >
      <span
        className={`h-1.5 w-1.5 rounded-full ${
          danger
            ? "bg-red-400"
            : active
              ? "bg-emerald-400"
              : pending
                ? "bg-amber-400"
              : "bg-neutral-500"
        }`}
      />
      {STATUS_LABELS[normalized] || status}
    </span>
  );
}

function Metric({
  label,
  value,
  tone,
  icon: Icon = Gauge,
  liveValue,
}: {
  label: string;
  value: string;
  tone?: "positive" | "negative";
  icon?: typeof Gauge;
  liveValue?: unknown;
}) {
  return (
    <div className="rounded-2xl border border-white/8 bg-[#181a20] p-4 shadow-[0_12px_35px_rgba(0,0,0,.12)]">
      <p className="flex items-center gap-2 text-[10px] font-black uppercase tracking-wider text-neutral-600">
        <Icon className="h-3.5 w-3.5" />
        {label}
      </p>
      <p
        className={`mt-2 truncate text-lg font-semibold ${
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

function ClosedCycleProfitCard({
  label,
  value,
  unit,
  completedCycles,
}: {
  label: string;
  value: number | null;
  unit: string;
  completedCycles: number;
}) {
  const tone = metricTone(value);
  const formatted = value === null
    ? "—"
    : `${value > 0 ? "+" : ""}${decimal(value, unit === "USDT" ? 4 : 8)} ${unit}`;
  return (
    <article className={`rounded-2xl border p-4 ${tone === "positive" ? "border-emerald-300/15 bg-emerald-300/[0.035]" : tone === "negative" ? "border-red-300/15 bg-red-300/[0.035]" : "border-white/8 bg-[#181a20]"}`}>
      <p className="text-[10px] font-black uppercase tracking-[0.14em] text-neutral-500">
        {label}
      </p>
      <p className={`mt-2 font-mono text-xl font-black ${tone === "positive" ? "text-emerald-300" : tone === "negative" ? "text-red-300" : "text-white"}`}>
        <LiveValue value={value} toneBySign>{formatted}</LiveValue>
      </p>
      <p className="mt-2 text-[11px] font-semibold text-neutral-500">
        {completedCycles} tur tamamlandı
      </p>
    </article>
  );
}

function ErrorPanel({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div
      role="alert"
      className="flex flex-col gap-3 rounded-xl border border-red-400/20 bg-red-400/10 p-4 text-sm text-red-200 sm:flex-row sm:items-center sm:justify-between"
    >
      <span className="flex items-start gap-2">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
        {message}
      </span>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="self-start rounded-lg border border-red-300/20 px-3 py-1.5 text-xs font-semibold transition hover:bg-red-300/10 sm:self-auto"
        >
          Yeniden dene
        </button>
      )}
    </div>
  );
}

function LoadingPanel() {
  return (
    <div className="flex min-h-56 items-center justify-center rounded-2xl border border-neutral-800 bg-[#181a20]">
      <div className="flex items-center gap-2 text-sm text-neutral-400">
        <LoaderCircle className="h-4 w-4 animate-spin" />
        Veriler hazırlanıyor
      </div>
    </div>
  );
}

function EmptyPanel({ message }: { message: string }) {
  return (
    <div className="flex min-h-32 items-center justify-center rounded-xl border border-dashed border-neutral-700 bg-neutral-900/40 p-6 text-center text-sm text-neutral-500">
      {message}
    </div>
  );
}

interface ParameterComparison {
  label: string;
  baseline: number | null;
  applied: number | null;
  multiplier?: unknown;
}

function ParameterValueLine({
  item,
}: {
  key?: string;
  item: ParameterComparison;
}) {
  const shown = item.applied ?? item.baseline;
  return (
    <div className="rounded-xl border border-white/7 bg-black/15 p-3">
      <p className="text-[9px] font-black uppercase tracking-wider text-neutral-600">
        {item.label}
      </p>
      <p className="mt-2 font-mono text-sm font-black text-white">
        {shown === null ? "—" : `%${decimal(shown, 3)}`}
      </p>
    </div>
  );
}

function DynamicGridComparison({
  side,
  applied,
  trailing,
}: {
  side: "buy" | "sell";
  applied: Record<string, unknown>[];
  trailing: ParameterComparison;
}) {
  if (!applied.length) return null;
  const isBuy = side === "buy";
  const trail = trailing.applied ?? trailing.baseline;
  return (
    <section
      className={`rounded-2xl border p-4 ${
        isBuy
          ? "border-sky-300/12 bg-sky-300/[0.025]"
          : "border-emerald-300/12 bg-emerald-300/[0.025]"
      }`}
    >
      <div className="flex min-h-7 items-center justify-between gap-3">
        <h3 className={`shrink-0 whitespace-nowrap text-xs font-black ${isBuy ? "text-sky-200" : "text-emerald-200"}`}>
          {isBuy ? "Aşağı alış gridleri" : "Yukarı satış gridleri"}
        </h3>
        <div className="flex min-h-7 items-center justify-end">
          <span className={`inline-flex min-h-7 items-center whitespace-nowrap rounded-full px-2.5 py-1 text-[9px] font-black ${isBuy ? "bg-sky-300/10 text-sky-200" : "bg-emerald-300/10 text-emerald-200"}`}>
            {isBuy ? "Alış trailing" : "Satış trailing"} ·{" "}
            {trail === null ? "—" : `%${decimal(trail, 3)}`}
          </span>
        </div>
      </div>
      <div className="mt-3 space-y-2">
        {applied.map((gridRow, index) => {
          const trigger = gridParameterValue(gridRow, side, "trigger");
          const quantity = gridParameterValue(gridRow, side, "quantity");
          return (
            <div key={`${side}-${index}`} className="rounded-xl border border-white/7 bg-black/15 p-3">
              <p className="text-[9px] font-black uppercase tracking-wider text-neutral-600">
                {index + 1}. grid
              </p>
              <div className="mt-2 grid gap-2 sm:grid-cols-2">
                <ParameterValueLine
                  item={{
                    label: "Tetik mesafesi",
                    baseline: trigger,
                    applied: trigger,
                  }}
                />
                <ParameterValueLine
                  item={{
                    label: isBuy ? "Alış miktarı" : "Satış miktarı",
                    baseline: quantity,
                    applied: quantity,
                  }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function StrategyParametersCard({
  detail,
  dynamicEnabled,
  cycleId,
  cycleOpenedAt,
  botStartedAt,
  regime,
  tourCount,
  performance,
  liveDailyUsd,
  liveDailyPct,
}: {
  detail: BotDetail;
  dynamicEnabled: boolean;
  cycleId: number | null;
  cycleOpenedAt: string | number | null;
  botStartedAt: string | number | null;
  regime: string;
  tourCount: number;
  performance: BotPerformance | null;
  liveDailyUsd?: number | null;
  liveDailyPct?: number | null;
}) {
  const dynamic = objectValue(detail.dynamic_mode);
  const snapshot = objectValue(dynamic.snapshot);
  const snapshotBaseline = objectValue(snapshot.baseline);
  const config = objectValue(detail.config);
  const baseline = Object.keys(snapshotBaseline).length ? snapshotBaseline : config;
  const snapshotApplied = objectValue(snapshot.applied);
  const dynamicApplied =
    dynamicEnabled &&
    Object.keys(snapshotApplied).length > 0;
  // Always show the live round plan when dynamic snapshot exists; else form config.
  const applied = dynamicApplied ? snapshotApplied : baseline;
  const displayCycle = toFiniteNumber(snapshot.cycle_id) ?? cycleId;
  const regimeTitle = shortMainRegime(regime);
  const regimeDetail = explainMainRegime(regime);

  return (
    <section className="overflow-hidden rounded-[1.75rem] border border-fuchsia-300/15 bg-[#191a20] shadow-[0_24px_80px_rgba(0,0,0,.2)]">
      <header className="relative overflow-hidden border-b border-white/8 p-5 sm:p-6">
        <div className="pointer-events-none absolute -right-20 -top-24 h-64 w-64 rounded-full bg-fuchsia-400/10 blur-3xl" />
        <div className="relative space-y-4">
          <div>
            <p className="flex items-center gap-2 text-[10px] font-black uppercase tracking-[0.18em] text-fuchsia-200">
              <Layers3 className="h-4 w-4" /> Bu turun parametreleri
            </p>
            <h2 className="mt-2 text-xl font-black text-white">
              {dynamicEnabled
                ? displayCycle === null
                  ? "Aktif tur planı bekleniyor"
                  : `${decimal(displayCycle, 0)}. turda uygulanan plan`
                : "Botun çalışan parametre planı"}
            </h2>
            {!dynamicEnabled && (
              <p className="mt-2 max-w-2xl text-xs leading-5 text-neutral-500">
                Bot, oluşturulurken belirlenen dağılım, grid, trailing ve kâr döngüsü değerlerini kullanır.
              </p>
            )}
          </div>

          <section className="rounded-2xl border border-fuchsia-300/18 bg-fuchsia-300/[0.06] p-4 text-center">
            <p className="text-[10px] font-black uppercase tracking-wider text-fuchsia-100">
              Ana rejim
            </p>
            <p className="mt-2 text-base font-black leading-6 text-white">{regimeTitle}</p>
            <p className="mx-auto mt-2 max-w-xl text-xs leading-5 text-neutral-300">{regimeDetail}</p>
          </section>

          <div className="grid gap-2 sm:grid-cols-3">
            <div className={`flex min-h-16 flex-col justify-center rounded-xl border px-3 py-2.5 text-center ${dynamicEnabled ? "border-emerald-300/20 bg-emerald-300/[0.07]" : "border-white/8 bg-white/[0.025]"}`}>
              <span className="text-[9px] font-black uppercase tracking-[0.14em] text-neutral-500">Çalışma modu</span>
              <span className={`mt-1 text-[11px] font-black ${dynamicEnabled ? "text-emerald-200" : "text-neutral-300"}`}>
                {dynamicEnabled ? "Dinamik · Açık" : "Sabit"}
              </span>
            </div>
            <div className="flex min-h-16 flex-col justify-center rounded-xl border border-emerald-300/15 bg-emerald-300/[0.05] px-3 py-2.5 text-center">
              <span className="text-[9px] font-black uppercase tracking-[0.14em] text-neutral-500">Bot süresi</span>
              <span className="mt-1 text-[11px] font-black text-emerald-100">
                {readableDuration(ageInSeconds(botStartedAt))}
              </span>
            </div>
            <div className="flex min-h-16 flex-col justify-center rounded-xl border border-sky-300/15 bg-sky-300/[0.05] px-3 py-2.5 text-center">
              <span className="text-[9px] font-black uppercase tracking-[0.14em] text-neutral-500">Tur süresi</span>
              <span className="mt-1 text-[11px] font-black text-sky-100">
                {readableDuration(ageInSeconds(cycleOpenedAt))}
              </span>
            </div>
          </div>

          <div className="flex min-h-16 flex-col justify-center rounded-xl border border-violet-300/15 bg-violet-300/[0.05] px-3 py-2.5 text-center">
            <span className="text-[9px] font-black uppercase tracking-[0.14em] text-neutral-500">Tur sayısı</span>
            <span className="mt-1 text-[11px] font-black text-violet-100">
              {decimal(tourCount, 0)}
            </span>
          </div>

          {performance && (
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {performance.price_stale && (
                <div className="sm:col-span-2 xl:col-span-3 rounded-xl border border-amber-300/15 bg-amber-300/[0.05] px-4 py-3 text-xs text-amber-100">
                  Canlı fiyat gecikiyor. Bakiye ve performans kartları son güvenilir
                  snapshot değerini gösteriyor; eski fiyatla yeniden hesaplama yapılmıyor.
                </div>
              )}
              <Metric
                label="Başlangıç bakiyesi"
                value={money(performance.initial_usd)}
              />
              <Metric
                label="Güncel bakiye"
                value={money(performance.balance_end_usd ?? performance.total_usd)}
                liveValue={performance.balance_end_usd ?? performance.total_usd}
              />
              <Metric
                label="Toplam kazanç"
                value={`${money(
                  (toFiniteNumber(performance.balance_end_usd ?? performance.total_usd) ?? 0) -
                    (toFiniteNumber(performance.initial_usd) ?? 0),
                )} · ${percent(
                  (() => {
                    const start = toFiniteNumber(performance.initial_usd);
                    const end = toFiniteNumber(
                      performance.balance_end_usd ?? performance.total_usd,
                    );
                    if (start !== null && start > 0 && end !== null) {
                      return ((end - start) / start) * 100;
                    }
                    return performance.balance_change_pct;
                  })(),
                )}`}
                tone={metricTone(
                  (toFiniteNumber(performance.balance_end_usd ?? performance.total_usd) ?? 0) -
                    (toFiniteNumber(performance.initial_usd) ?? 0),
                )}
                liveValue={`${performance.balance_end_usd ?? performance.total_usd ?? ""}:${performance.initial_usd ?? ""}`}
              />
              <Metric
                label="Günlük kazanç"
                value={`${money(performance.daily_gain_usd ?? liveDailyUsd ?? detail.daily_pnl_usd)} · ${percent(performance.daily_gain_pct ?? liveDailyPct ?? detail.daily_pnl_pct)}`}
                tone={metricTone(performance.daily_gain_usd ?? liveDailyUsd ?? detail.daily_pnl_usd)}
                liveValue={`${performance.daily_gain_usd ?? liveDailyUsd ?? detail.daily_pnl_usd ?? ""}:${performance.daily_gain_pct ?? liveDailyPct ?? detail.daily_pnl_pct ?? ""}`}
              />
              <Metric
                label="Aylık kazanç"
                value={`${money(performance.monthly_gain_usd)} · ${percent(performance.monthly_gain_pct)}`}
                tone={metricTone(performance.monthly_gain_usd)}
                liveValue={`${performance.monthly_gain_usd ?? ""}:${performance.monthly_gain_pct ?? ""}`}
              />
              <Metric
                label="Tahmini yıllık USDT getirisi"
                value={percent(performance.estimated_annual_return_pct_12m)}
                tone={metricTone(performance.estimated_annual_return_pct_12m)}
                liveValue={performance.estimated_annual_return_pct_12m}
              />
            </div>
          )}
        </div>
      </header>

      <div className="space-y-4 p-5 sm:p-6">
        <CycleParametersCard
          parameters={applied}
          cycleId={displayCycle}
          isOpen
          regime={regime}
          title="Aktif turun uygulanan parametreleri"
          subtitle={
            displayCycle !== null
              ? `Tur #${decimal(displayCycle, 0)} şu anda bu değerlerle çalışıyor.`
              : "Botun şu anda uyguladığı parametre planı."
          }
        />
      </div>
    </section>
  );
}

function gridStageText(
  entries: Array<{ point: Record<string, unknown>; fallback: "grid" | "profit" }>,
  direction: string,
): string {
  if (direction.includes("İki yön")) {
    return "İki yön açık · Referans gridleri bekliyor";
  }
  const side: GridSide = direction.includes("Satış") ? "sell" : "buy";
  const main = entries.filter(
    ({ point, fallback }) =>
      gridPointSide(point, fallback) === side && gridPointPhase(point) !== "disabled",
  );
  const directionText = side === "sell" ? "Yukarı yön aktif" : "Aşağı yön aktif";
  if (!main.length) return `${directionText} · 1. grid tetik bekliyor`;
  const completed = main.filter(({ point }) => gridPointPhase(point) === "completed").length;
  if (completed >= main.length) {
    return side === "sell"
      ? `${directionText} · Bütün gridler satıldı, kârlı geri alış bekleniyor.`
      : `${directionText} · Bütün gridler alındı, kâr satışı bekleniyor.`;
  }
  const next = main.find(({ point }) => gridPointPhase(point) !== "completed");
  const nextPhase = next ? gridPointPhase(next.point) : "waiting";
  const state =
    nextPhase === "triggered"
      ? "tetiklendi"
      : nextPhase === "trailing"
        ? "trailing ile dönüş izliyor"
        : "tetik bekliyor";
  if (!completed) return `${directionText} · 1. grid ${state}`;
  return `${directionText} · ${completed} grid ${side === "sell" ? "satıldı" : "alındı"}, ${completed + 1}. grid ${state}`;
}

function GridCommandCenter({
  grid,
  entries,
  direction,
}: {
  grid: BotGridData;
  entries: Array<{
    point: Record<string, unknown>;
    fallback: "grid" | "profit";
  }>;
  direction: string;
}) {
  const sell = entries.filter(
    ({ point, fallback }) => gridPointSide(point, fallback) === "sell",
  );
  const buy = entries.filter(
    ({ point, fallback }) => gridPointSide(point, fallback) === "buy",
  );
  const profit = entries.filter(
    ({ point, fallback }) => gridPointSide(point, fallback) === "profit",
  );
  const directionPending = direction.includes("İki yön");
  const showSell =
    directionPending ||
    direction.includes("Satış") ||
    direction.includes("belirleniyor");
  const showBuy =
    directionPending ||
    direction.includes("Alış") ||
    direction.includes("belirleniyor");
  const stage = gridStageText(entries, direction);
  const stageTone = directionPending
    ? "purple"
    : direction.includes("Alış")
      ? "red"
      : "green";
  const gridPair = splitTradingSymbol(grid.symbol);
  const referencePrice =
    toFiniteNumber(grid.reference_display) ??
    readNumber(grid.meta || {}, ["reference_price", "reference_display"]) ??
    readNumber(grid.config || {}, ["reference_price"]);

  return (
    <section className="overflow-hidden rounded-[1.75rem] border border-fuchsia-300/15 bg-[#17181e] shadow-[0_24px_80px_rgba(0,0,0,.22)]">
      <header className="relative overflow-hidden border-b border-white/8 p-5 sm:p-6">
        <div className="pointer-events-none absolute -right-24 -top-28 h-72 w-72 rounded-full bg-fuchsia-400/10 blur-3xl" />
        <div className="relative grid gap-5 lg:grid-cols-[1fr_360px] lg:items-start">
          <div>
            <p className="flex items-center gap-2 text-[10px] font-black uppercase tracking-[0.2em] text-fuchsia-200">
              <Zap className="h-4 w-4" />
              Canlı grid motoru
            </p>
            <h2
              className={`mt-2 text-2xl font-black tracking-[-0.03em] ${
                directionPending
                  ? "text-white"
                  : stageTone === "green"
                  ? "text-emerald-200"
                  : stageTone === "purple"
                    ? "text-fuchsia-200"
                    : "text-red-200"
              }`}
            >
              {stage}
            </h2>
          </div>
          <div className="grid gap-2">
            <GridStatusChip
              icon={Activity}
              label="Aşama"
              value={stage}
              tone={stageTone}
            />
            <GridStatusChip
              icon={Target}
              label="Referans fiyat"
              value={`${coinPrice(referencePrice)} ${gridPair.quote}`}
              tone="violet"
            />
          </div>
        </div>
      </header>

      <div className="space-y-4 p-4 sm:p-5">
        {showSell && <GridLane title="Yukarı Satış Gridleri" side="sell" entries={sell} baseAsset={gridPair.base} quoteAsset={gridPair.quote} />}
        {showBuy && <GridLane title="Aşağı Alış Gridleri" side="buy" entries={buy} baseAsset={gridPair.base} quoteAsset={gridPair.quote} />}
        {profit.length > 0 && (
          <GridLane
            title={
              direction.includes("Satış")
                ? "Kâr döngüsü · Düşük fiyattan avantajlı geri alış"
                : "Kâr döngüsü · Yüksek fiyattan avantajlı satış"
            }
            detail={
              direction.includes("Satış")
                ? "Yüksek fiyattan satılan coinler maliyet fiyatının altından kar ile geri alınır ve adet arttırılır"
                : "Düşük fiyattan alınan coinler maliyet fiyatının üstüne çıkınca kar satışı yapılır ve dolar rezervi arttırılır."
            }
            side="profit"
            entries={profit}
            baseAsset={gridPair.base}
            quoteAsset={gridPair.quote}
          />
        )}
      </div>
    </section>
  );
}

function GridStatusChip({
  icon: Icon,
  label,
  value,
  tone,
}: {
  icon: typeof Activity;
  label: string;
  value: string;
  tone: "violet" | "purple" | "blue" | "green" | "amber" | "red";
}) {
  const tones = {
    violet: "border-violet-300/12 bg-violet-300/[0.045] text-violet-200",
    purple: "border-fuchsia-300/12 bg-fuchsia-300/[0.045] text-fuchsia-200",
    blue: "border-sky-300/12 bg-sky-300/[0.045] text-sky-200",
    green: "border-emerald-300/12 bg-emerald-300/[0.045] text-emerald-200",
    amber: "border-amber-300/12 bg-amber-300/[0.045] text-amber-200",
    red: "border-red-300/15 bg-red-300/[0.055] text-red-200",
  };
  return (
    <div className={`min-w-0 rounded-xl border p-3 ${tones[tone]}`}>
      <p className="flex items-center gap-1.5 text-[8px] font-black uppercase tracking-wider text-neutral-600">
        <Icon className="h-3 w-3" />
        {label}
      </p>
      <p className="mt-1.5 text-[10px] font-black leading-4" title={value}>
        {value}
      </p>
    </div>
  );
}

function GridLane({
  title,
  detail,
  side,
  entries,
  baseAsset,
  quoteAsset,
}: {
  title: string;
  detail?: string;
  side: GridSide;
  entries: Array<{
    point: Record<string, unknown>;
    fallback: "grid" | "profit";
  }>;
  baseAsset: string;
  quoteAsset: string;
}) {
  const Icon = side === "buy" ? ArrowDown : side === "sell" ? ArrowUp : Sparkles;
  return (
    <section
      className={`overflow-hidden rounded-2xl border ${
        side === "buy"
          ? "border-sky-300/12 bg-sky-300/[0.025]"
          : side === "sell"
            ? "border-emerald-300/12 bg-emerald-300/[0.025]"
            : "border-fuchsia-300/12 bg-fuchsia-300/[0.025]"
      }`}
    >
      <header className="flex items-start justify-between gap-3 border-b border-white/7 px-4 py-3">
        <div>
          <p
            className={`flex items-center gap-2 text-xs font-black ${
              side === "buy"
                ? "text-sky-200"
                : side === "sell"
                  ? "text-emerald-200"
                  : "text-fuchsia-200"
            }`}
          >
            <Icon className="h-4 w-4" />
            {title}
          </p>
          {detail && <p className="mt-1 text-[10px] leading-4 text-neutral-500">{detail}</p>}
        </div>
        <span className="shrink-0 rounded-full bg-black/15 px-2 py-1 text-[9px] font-black text-neutral-500">
          {entries.length} grid
        </span>
      </header>
      {entries.length ? (
        <div className="flex snap-x snap-mandatory scroll-px-3 gap-2 overflow-x-auto px-3 pb-3 pt-2 sm:scroll-px-4 sm:px-4">
          {entries.map(({ point }, index) => (
            <GridPointVisualCard
              key={`${title}-${readText(point, ["i", "index", "grid_index"]) || index}`}
              point={point}
              side={side}
              index={index}
              baseAsset={baseAsset}
              quoteAsset={quoteAsset}
              fullWidth={side === "profit" && entries.length === 1}
            />
          ))}
        </div>
      ) : (
        <p className="p-4 text-[11px] text-neutral-600">
          Bu yönde tanımlı seviye yok.
        </p>
      )}
    </section>
  );
}

function GridPointVisualCard({
  point,
  side,
  index,
  baseAsset,
  quoteAsset,
  fullWidth = false,
}: {
  key?: string;
  point: Record<string, unknown>;
  side: GridSide;
  index: number;
  baseAsset: string;
  quoteAsset: string;
  fullWidth?: boolean;
}) {
  const phase = gridPointPhase(point);
  const hasTriggered =
    phase === "triggered" || phase === "trailing" || phase === "completed";
  const hasCompleted = phase === "completed";
  const phaseIndex =
    phase === "waiting"
      ? 0
      : phase === "triggered"
        ? 1
        : phase === "trailing"
          ? 2
          : phase === "completed"
            ? 3
            : -1;
  const triggerPrice = readNumber(point, [
    "trigger_price",
    "price",
    "target_price",
    "level_price",
  ]);
  const extreme = hasTriggered
    ? readNumber(point, [
        "anchor",
        "dip",
        "tepe",
        "peak",
        "trigger_hit_price",
      ])
    : null;
  const execution = hasTriggered
    ? readNumber(point, ["execution_price"])
    : null;
  const triggerPct = readNumber(point, [
    "trigger_pct_from_reference",
    "trigger_pct",
    "profit_pct",
  ]);
  const trailingPct = readNumber(point, [
    "trailing_pct",
    "trail_pct",
    "profit_trailing_pct",
  ]);
  const extremePct = hasTriggered
    ? readNumber(point, ["extreme_pct_from_reference"])
    : null;
  const executionPct = hasTriggered
    ? readNumber(point, ["execution_pct_from_reference"])
    : null;
  const qtyPct = readNumber(point, ["qty_pct", "notional_pct"]);
  const averageCost = readNumber(point, ["average_cost", "cost_basis_price"]);
  const profitType =
    `${readText(point, ["type"])} ${readText(point, ["order_type"])}`.toLowerCase();
  const averageCostLabel =
    profitType.includes("reentry") || profitType.includes("rebuy")
      ? "Ortalama satış maliyeti"
      : "Ortalama alış maliyeti";
  const profitRebuy =
    profitType.includes("reentry") || profitType.includes("rebuy");
  const profitAmount = profitRebuy
    ? readNumber(point, ["planned_quote_usd", "notional_usdt"])
    : readNumber(point, ["planned_base_qty"]);
  const profitAmountLabel = profitRebuy ? "Alış tutarı" : "Satış miktarı";
  const profitAmountValue = profitRebuy
    ? `${decimal(profitAmount, 2)} USDT`
    : `${decimal(profitAmount, 8)} ${baseAsset}`;
  const extremeLabel =
    side === "buy" || (side === "profit" && profitRebuy) ? "Dip" : "Tepe";
  const tone =
    phase === "completed"
      ? "border-emerald-300/20"
      : phase === "trailing"
        ? "border-fuchsia-300/25 shadow-[0_0_30px_rgba(217,70,239,.08)]"
        : phase === "triggered"
          ? "border-amber-300/22"
          : phase === "disabled"
            ? "border-red-300/12 opacity-55"
            : "border-white/8";
  return (
    <article
      className={`${fullWidth ? "min-w-full" : "min-w-[calc(100%-0.25rem)] sm:min-w-[360px]"} snap-start rounded-xl border bg-[#17181e] p-3.5 ${tone}`}
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          {side !== "profit" && (
            <p className="text-[9px] font-black uppercase tracking-wider text-neutral-600">
              {index + 1}. Grid
            </p>
          )}
          {side === "profit" && (
            <p className="text-[9px] font-black uppercase tracking-wider text-neutral-600">
              Kar döngüsü
            </p>
          )}
          <p
            className={`mt-1 text-xs font-black ${
              phase === "completed"
                ? "text-emerald-200"
                : phase === "trailing"
                  ? "text-fuchsia-200"
                  : phase === "triggered"
                    ? "text-amber-200"
                    : "text-neutral-300"
            }`}
          >
            {side === "profit" && phase === "waiting"
              ? "Tetiklenmeyi bekliyor"
              : GRID_PHASE_LABELS[phase]}
          </p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          {phase === "completed" ? (
            <span className="grid h-7 w-7 place-items-center rounded-full bg-emerald-300/15 text-emerald-200" aria-label="Grid tamamlandı">
              <CheckCircle2 className="h-4 w-4" />
            </span>
          ) : (
            <span className={`rounded-full px-2 py-1 text-[9px] font-black ${side === "buy" ? "bg-sky-300/[0.07] text-sky-200" : side === "sell" ? "bg-emerald-300/[0.07] text-emerald-200" : "bg-fuchsia-300/[0.07] text-fuchsia-200"}`}>
              {percent(triggerPct)}
            </span>
          )}
          {trailingPct !== null && (
            <span className="rounded-full border border-white/8 bg-black/25 px-2 py-0.5 text-[8px] font-black text-neutral-300">
              Trail {percent(trailingPct)}
            </span>
          )}
        </div>
      </div>

      <div className="mt-2.5 grid grid-cols-4 gap-1">
        {[0, 1, 2, 3].map((step) => (
          <span
            key={step}
            className={`h-1.5 rounded-full ${
              phase !== "disabled" && step <= phaseIndex
                ? step === 3
                  ? "bg-emerald-300"
                  : step === 2
                    ? "bg-fuchsia-300"
                    : step === 1
                      ? "bg-amber-300"
                      : "bg-sky-300"
                : "bg-white/6"
            }`}
          />
        ))}
      </div>
      <div className="mt-2.5 grid grid-cols-2 gap-1.5">
        <MiniGridValue
          label={`Tetik fiyatı${
            triggerPct !== null ? ` · ${percent(triggerPct)}` : ""
          }`}
          value={
            triggerPrice === null
              ? "—"
              : `${coinPrice(triggerPrice)} ${quoteAsset}`
          }
        />
        <MiniGridValue
          label={
            side === "profit"
              ? profitAmountLabel
              : side === "buy"
                ? "Alış miktarı"
                : "Satış miktarı"
          }
          value={
            side === "profit"
              ? profitAmount === null
                ? "—"
                : profitAmountValue
              : qtyPct === null
                ? "—"
                : `%${decimal(qtyPct, 2)}`
          }
        />
        <MiniGridValue
          label={`${extremeLabel}${
            extremePct !== null ? ` · ${percent(extremePct)}` : ""
          }`}
          value={
            extreme === null ? "—" : `${coinPrice(extreme)} ${quoteAsset}`
          }
        />
        <MiniGridValue
          label={`${hasCompleted ? "Gerçekleşme" : hasTriggered ? "Tamamlanma eşiği" : "Tamamlanma"}${
            executionPct !== null
              ? ` · ${percent(executionPct)}`
              : ""
          }`}
          value={
            execution === null
              ? "—"
              : `${coinPrice(execution)} ${quoteAsset}`
          }
        />
      </div>
      {side === "profit" && phase !== "disabled" && averageCost !== null && (
        <div className="mt-1.5 rounded-md border border-fuchsia-300/10 bg-fuchsia-300/[0.045] px-2 py-1.5">
          <p className="text-[7px] font-black uppercase tracking-wider text-fuchsia-200/70">
            {averageCostLabel}
          </p>
          <p className="mt-0.5 font-mono text-[12px] font-black text-fuchsia-100">
            {coinPrice(averageCost)} {quoteAsset}
          </p>
        </div>
      )}
      {readText(point, ["disabled_reason"]) && (
        <p className="mt-1.5 rounded-md bg-red-300/[0.05] px-2 py-1.5 text-[9px] leading-4 text-red-200">
          {readText(point, ["disabled_reason"])}
        </p>
      )}
    </article>
  );
}

function MiniGridValue({
  label,
  value,
}: {
  key?: string;
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-md border border-white/[0.04] bg-black/20 px-2 py-1.5">
      <p className="text-[7px] font-black uppercase tracking-wider text-neutral-500">
        {label}
      </p>
      <p
        className="mt-0.5 truncate font-mono text-[12px] font-black leading-4 text-white"
        title={value}
      >
        {value}
      </p>
    </div>
  );
}

function CycleParametersCard({
  summary,
  parameters: parametersProp,
  cycleId,
  isOpen: isOpenProp,
  regime: regimeProp,
  title,
  subtitle,
}: {
  summary?: Record<string, unknown>;
  parameters?: Record<string, unknown>;
  cycleId?: number | null;
  isOpen?: boolean;
  regime?: string;
  title?: string;
  subtitle?: string;
}) {
  const parameters = parametersProp
    ? objectValue(parametersProp)
    : objectValue(summary?.cycle_parameters);
  const buyGrids = strategyGridList(parameters, "buy");
  const sellGrids = strategyGridList(parameters, "sell");
  const baseAlloc = parameterValue(parameters, ["base_alloc_pct", "base_pct"]);
  const quoteAlloc = parameterValue(parameters, ["quote_alloc_pct", "quote_pct"]);
  const sellTrail = parameterValue(parameters, ["sell_trigger_trailing_pct"]);
  const buyTrail = parameterValue(parameters, ["buy_trigger_trailing_pct"]);
  const profitBuyTrigger = parameterValue(parameters, ["profit_reentry_drop_pct"]);
  const profitBuyTrail = parameterValue(parameters, ["profit_reentry_rise_pct"]);
  const profitSellTrigger = parameterValue(parameters, ["profit_exit_rise_pct"]);
  const profitSellTrail = parameterValue(parameters, ["profit_exit_drop_pct"]);
  const hasProfitBuy = profitBuyTrigger !== null || profitBuyTrail !== null;
  const hasProfitSell = profitSellTrigger !== null || profitSellTrail !== null;
  if (
    baseAlloc === null &&
    quoteAlloc === null &&
    !buyGrids.length &&
    !sellGrids.length &&
    !hasProfitBuy &&
    !hasProfitSell
  ) {
    return null;
  }
  const isOpen = isOpenProp ?? summary?.is_open === true;
  const regime = regimeProp || readText(summary || {}, ["dynamic_regime"]);
  const formatPctValue = (value: number | null) =>
    value === null ? "—" : `%${decimal(value, 3)}`;
  const gridGroup = (
    side: "buy" | "sell",
    grids: Record<string, unknown>[],
    trail: number | null,
  ) => (
    <div
      className={`rounded-xl border p-3 ${
        side === "buy"
          ? "border-emerald-300/15 bg-emerald-300/[0.025]"
          : "border-red-300/15 bg-red-300/[0.025]"
      }`}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p
          className={`text-[10px] font-black uppercase tracking-[0.14em] ${
            side === "buy" ? "text-emerald-200" : "text-red-200"
          }`}
        >
          {side === "buy" ? "Aşağı alış gridleri" : "Yukarı satış gridleri"}
        </p>
        <div className="flex items-center gap-2">
          {trail !== null && (
            <span className="rounded-full border border-white/8 bg-black/20 px-2 py-1 text-[9px] font-black text-white">
              Trailing · {formatPctValue(trail)}
            </span>
          )}
          <span className="text-[9px] font-bold text-neutral-600">
            {grids.length} seviye
          </span>
        </div>
      </div>
      <div className="mt-2 grid gap-2 sm:grid-cols-2">
        {grids.map((grid, index) => {
          const trigger = gridParameterValue(grid, side, "trigger");
          const quantity = gridParameterValue(grid, side, "quantity");
          return (
            <div
              key={`${side}-${index}`}
              className="rounded-lg border border-white/7 bg-black/15 px-2.5 py-2"
            >
              <p className="text-[9px] font-black text-neutral-300">
                {index + 1}. grid
              </p>
              <div className="mt-1.5 grid grid-cols-2 gap-2 font-mono text-[11px]">
                <span className="text-neutral-500">
                  Tetik{" "}
                  <b className="ml-1 text-white">
                    {trigger === null
                      ? "—"
                      : `${side === "buy" ? "−" : "+"}%${decimal(Math.abs(trigger), 3)}`}
                  </b>
                </span>
                <span className="text-right text-neutral-500">
                  Pay{" "}
                  <b className="ml-1 text-white">
                    {quantity === null ? "—" : `%${decimal(quantity, 2)}`}
                  </b>
                </span>
              </div>
            </div>
          );
        })}
        {!grids.length && (
          <p className="text-[10px] text-neutral-600">
            Bu yönde grid tanımlı değil.
          </p>
        )}
      </div>
    </div>
  );
  const profitBox = (
    kind: "buy" | "sell",
    trigger: number | null,
    trail: number | null,
  ) => (
    <div
      className={`rounded-xl border p-3 ${
        kind === "buy"
          ? "border-sky-300/15 bg-sky-300/[0.03]"
          : "border-fuchsia-300/15 bg-fuchsia-300/[0.03]"
      }`}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p
          className={`text-[10px] font-black uppercase tracking-[0.14em] ${
            kind === "buy" ? "text-sky-200" : "text-fuchsia-200"
          }`}
        >
          {kind === "buy" ? "Kâr alışı" : "Kâr satışı"}
        </p>
        {trail !== null && (
          <span className="rounded-full border border-white/8 bg-black/20 px-2 py-1 text-[9px] font-black text-white">
            Trailing · {formatPctValue(trail)}
          </span>
        )}
      </div>
      <div className="mt-2 grid gap-2 sm:grid-cols-2">
        <div className="rounded-lg border border-white/7 bg-black/15 px-2.5 py-2">
          <p className="text-[9px] font-black text-neutral-300">Tetik</p>
          <p className="mt-1 font-mono text-[12px] font-black text-white">
            {formatPctValue(trigger)}
          </p>
        </div>
        <div className="rounded-lg border border-white/7 bg-black/15 px-2.5 py-2">
          <p className="text-[9px] font-black text-neutral-300">Trailing</p>
          <p className="mt-1 font-mono text-[12px] font-black text-white">
            {formatPctValue(trail)}
          </p>
        </div>
      </div>
    </div>
  );
  return (
    <section className="rounded-2xl border border-fuchsia-300/15 bg-fuchsia-300/[0.035] p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-[10px] font-black uppercase tracking-[0.16em] text-fuchsia-200">
            {title ||
              (isOpen
                ? "Aktif turun uygulanan parametreleri"
                : "Bu turda uygulanan parametreler")}
          </p>
          <p className="mt-1 text-xs leading-5 text-neutral-500">
            {subtitle ||
              (isOpen
                ? `Tur #${cycleId ?? "—"} şu anda bu değerlerle çalışıyor.`
                : "Dinamik modun bu tur başlarken dondurduğu gerçek değerler.")}
          </p>
        </div>
        {regime && (
          <span className="rounded-full border border-fuchsia-300/15 bg-fuchsia-300/[0.07] px-3 py-1.5 text-[10px] font-black text-fuchsia-100">
            {shortMainRegime(regime)}
          </span>
        )}
      </div>
      {(baseAlloc !== null || quoteAlloc !== null) && (
        <div className="mt-4 grid gap-2 sm:grid-cols-2">
          {baseAlloc !== null && (
            <MiniGridValue label="Base dağılımı" value={formatPctValue(baseAlloc)} />
          )}
          {quoteAlloc !== null && (
            <MiniGridValue label="Quote dağılımı" value={formatPctValue(quoteAlloc)} />
          )}
        </div>
      )}
      <div className="mt-3 grid gap-3 lg:grid-cols-2">
        {(sellGrids.length > 0 || sellTrail !== null) &&
          gridGroup("sell", sellGrids, sellTrail)}
        {(buyGrids.length > 0 || buyTrail !== null) &&
          gridGroup("buy", buyGrids, buyTrail)}
      </div>
      {(hasProfitSell || hasProfitBuy) && (
        <div className="mt-3 grid gap-3 lg:grid-cols-2">
          {hasProfitSell && profitBox("sell", profitSellTrigger, profitSellTrail)}
          {hasProfitBuy && profitBox("buy", profitBuyTrigger, profitBuyTrail)}
        </div>
      )}
    </section>
  );
}

export default function BotDetailPage({
  botId,
  accountId,
  onDeleted,
}: BotDetailPageProps) {
  const [activeTab, setActiveTab] = useState<DetailTab>("summary");
  const [detail, setDetail] = useState<BotDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(true);
  const [detailError, setDetailError] = useState("");
  const [live, setLive] = useState<BotLiveSnapshot | null>(null);
  const [liveError, setLiveError] = useState("");
  const [health, setHealth] = useState<BotHealth | null>(null);
  const [grid, setGrid] = useState<BotGridData | null>(null);
  const [cycles, setCycles] = useState<BotCycles | null>(null);
  const [trades, setTrades] = useState<BotTrades | null>(null);
  const [initialBuyTrade, setInitialBuyTrade] = useState<BotTrade | null>(null);
  const [selectedCycle, setSelectedCycle] = useState<number | undefined>();
  const [selectedCycleType, setSelectedCycleType] =
    useState<"dca" | "trb" | undefined>();
  const [tradesLoading, setTradesLoading] = useState(false);
  const [performance, setPerformance] = useState<BotPerformance | null>(null);
  const [performancePeriod, setPerformancePeriod] =
    useState<PerformancePeriod>("all");
  const [tabLoading, setTabLoading] = useState<DetailTab | null>(null);
  const [tabErrors, setTabErrors] = useState<
    Partial<Record<DetailTab, string>>
  >({});
  const [pageVisible, setPageVisible] = useState(
    () => typeof document === "undefined" || !document.hidden,
  );
  const [mutation, setMutation] = useState<MutationName | null>(null);
  const [actionError, setActionError] = useState("");
  const [actionNotice, setActionNotice] = useState("");
  const [mutationNeedsReview, setMutationNeedsReview] = useState(false);
  const [deleted, setDeleted] = useState(false);
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);

  const loadedTabsRef = useRef(new Set<DetailTab>(["summary"]));
  const tabRequestsRef = useRef(new Map<DetailTab, AbortController>());
  const tradesRequestRef = useRef<AbortController | null>(null);
  const liveInFlightRef = useRef(false);
  const healthInFlightRef = useRef(false);
  const detailInFlightRef = useRef(false);
  const selectedCycleRef = useRef<number | undefined>(undefined);
  const selectedCycleTypeRef = useRef<"dca" | "trb" | undefined>(undefined);
  const activityVersionRef = useRef(0);
  const mutationLockRef = useRef(false);
  const lastCycleRef = useRef<number | null | undefined>(undefined);

  const loadDetail = useCallback(
    async (signal?: AbortSignal) => {
      if (detailInFlightRef.current) return;
      detailInFlightRef.current = true;
      setDetailLoading(true);
      setDetailError("");
      try {
        const response = await getBotDetail(botId, accountId, signal);
        if (!signal?.aborted) setDetail(response);
      } catch (error) {
        if (!signal?.aborted) {
          setDetailError(errorMessage(error, "Bot ayrıntıları alınamadı."));
        }
      } finally {
        detailInFlightRef.current = false;
        if (!signal?.aborted) setDetailLoading(false);
      }
    },
    [accountId, botId],
  );

  useEffect(() => {
    const controller = new AbortController();
    tabRequestsRef.current.forEach((request) => request.abort());
    tabRequestsRef.current.clear();
    tradesRequestRef.current?.abort();
    setDetail(null);
    setLive(null);
    setHealth(null);
    setGrid(null);
    setCycles(null);
    setTrades(null);
    setInitialBuyTrade(null);
    setPerformance(null);
    setPerformancePeriod("all");
    setSelectedCycle(undefined);
    setSelectedCycleType(undefined);
    selectedCycleRef.current = undefined;
    selectedCycleTypeRef.current = undefined;
    activityVersionRef.current += 1;
    setTradesLoading(false);
    setDeleted(false);
    setTabLoading(null);
    setTabErrors({});
    setLiveError("");
    setActionError("");
    setActionNotice("");
    setMutationNeedsReview(false);
    setShowDeleteDialog(false);
    lastCycleRef.current = undefined;
    setActiveTab("summary");
    loadedTabsRef.current = new Set(["summary"]);
    void loadDetail(controller.signal);
    return () => controller.abort();
  }, [loadDetail]);

  useEffect(() => {
    if (typeof document === "undefined") return;
    const onVisibilityChange = () => setPageVisible(!document.hidden);
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () =>
      document.removeEventListener("visibilitychange", onVisibilityChange);
  }, []);

  const loadLive = useCallback(
    async (signal?: AbortSignal) => {
      if (liveInFlightRef.current || deleted) return;
      liveInFlightRef.current = true;
      try {
        const response = await getBotLive(botId, accountId, signal);
        if (!signal?.aborted) {
          setLive(response);
          setLiveError("");
        }
      } catch (error) {
        if (!signal?.aborted) {
          setLiveError(errorMessage(error, "Canlı durum güncellenemedi."));
        }
      } finally {
        liveInFlightRef.current = false;
      }
    },
    [accountId, botId, deleted],
  );

  const loadHealth = useCallback(
    async (signal?: AbortSignal) => {
      if (healthInFlightRef.current || deleted) return;
      healthInFlightRef.current = true;
      try {
        const response = await getBotHealth(botId, accountId, signal);
        if (!signal?.aborted) setHealth(response);
      } catch {
        // Canlı durum akışı çalışmaya devam eder; son sağlık verisi korunur.
      } finally {
        healthInFlightRef.current = false;
      }
    },
    [accountId, botId, deleted],
  );

  useEffect(() => {
    if (!pageVisible || deleted) return;
    const controller = new AbortController();
    void loadLive(controller.signal);
    void loadHealth(controller.signal);
    const interval = window.setInterval(
      () => void loadLive(controller.signal),
      1_000,
    );
    return () => {
      window.clearInterval(interval);
      controller.abort();
    };
  }, [deleted, loadHealth, loadLive, pageVisible]);

  useEffect(() => {
    if (!pageVisible || deleted) return;
    const controller = new AbortController();
    const interval = window.setInterval(
      () => void loadHealth(controller.signal),
      5_000,
    );
    return () => {
      window.clearInterval(interval);
      controller.abort();
    };
  }, [deleted, loadHealth, pageVisible]);

  useEffect(() => {
    if (!pageVisible || deleted) return;
    const controller = new AbortController();
    const interval = window.setInterval(
      () => void loadDetail(controller.signal),
      5_000,
    );
    return () => {
      window.clearInterval(interval);
      controller.abort();
    };
  }, [deleted, loadDetail, pageVisible]);

  const loadTab = useCallback(
    async (tab: DetailTab, force = false) => {
      if (!force && loadedTabsRef.current.has(tab) && tab !== "summary") return;
      if (tabRequestsRef.current.has(tab)) return;

      const controller = new AbortController();
      const activityVersion = activityVersionRef.current;
      tabRequestsRef.current.set(tab, controller);
      setTabLoading(tab);
      setTabErrors((current) => ({ ...current, [tab]: "" }));

      try {
        if (tab === "summary") {
          if (force) {
            await loadDetail(controller.signal);
          }
          const performanceResponse = await getBotPerformance(
            botId,
            accountId,
            performancePeriod,
            controller.signal,
          );
          setPerformance(performanceResponse);
        } else if (tab === "grid") {
          setGrid(await getBotGrid(botId, accountId, controller.signal));
        } else if (tab === "activity") {
          const cycleResponse = await getBotCycles(
            botId,
            accountId,
            controller.signal,
          );
          const allCycles = [
            ...cycleResponse.cycles,
            ...cycleResponse.dca_cycles,
            ...cycleResponse.trb_cycles,
          ];
          const latestCycle = [...new Set(allCycles)].sort(
            (left, right) => right - left,
          )[0];
          const latestCycleType = cycleResponse.trb_cycles.includes(latestCycle)
            ? "trb"
            : cycleResponse.dca_cycles.includes(latestCycle)
              ? "dca"
              : undefined;
          const requestedCycle = selectedCycleRef.current ?? latestCycle;
          const requestedCycleType =
            selectedCycleRef.current === undefined
              ? latestCycleType
              : selectedCycleTypeRef.current;
          const [tradeResponse, allTradeResponse] = await Promise.all([
            getBotTrades(
              botId,
              accountId,
              requestedCycle,
              requestedCycleType,
              controller.signal,
            ),
            getBotTrades(botId, accountId, undefined, undefined, controller.signal),
          ]);
          const buyTrades = [...allTradeResponse.trades]
            .filter((trade) => String(trade.side || "").toUpperCase() === "BUY")
            .sort((left, right) => {
              const leftTime = new Date(left.ts || 0).getTime();
              const rightTime = new Date(right.ts || 0).getTime();
              return leftTime - rightTime;
            });
          const firstBuy =
            buyTrades.find((trade) => {
              const reason = String(trade.reason || "").toLowerCase();
              const clientOrderId = String(trade.client_order_id || "").toLowerCase();
              return reason === "initial_allocation" || clientOrderId.startsWith("init_");
            }) ||
            buyTrades.find((trade) => Number(trade.cycle_id || 1) === 1) ||
            null;
          if (
            activityVersion === activityVersionRef.current &&
            (selectedCycleRef.current === undefined ||
              (selectedCycleRef.current === requestedCycle &&
                selectedCycleTypeRef.current === requestedCycleType))
          ) {
            setCycles(cycleResponse);
            setSelectedCycle(requestedCycle);
            setSelectedCycleType(requestedCycleType);
            selectedCycleRef.current = requestedCycle;
            selectedCycleTypeRef.current = requestedCycleType;
            setTrades(tradeResponse);
            setInitialBuyTrade(firstBuy);
          }
        }
        if (!controller.signal.aborted) loadedTabsRef.current.add(tab);
      } catch (error) {
        if (!controller.signal.aborted) {
          setTabErrors((current) => ({
            ...current,
            [tab]: errorMessage(error, "Sekme verileri alınamadı."),
          }));
        }
      } finally {
        tabRequestsRef.current.delete(tab);
        if (!controller.signal.aborted) {
          setTabLoading((current) => (current === tab ? null : current));
        }
      }
    },
    [accountId, botId, loadDetail, performancePeriod],
  );

  useEffect(() => {
    void loadTab(activeTab);
  }, [activeTab, loadTab]);

  useEffect(() => {
    if (activeTab !== "summary") return;
    loadedTabsRef.current.delete("summary");
    void loadTab("summary", true);
  }, [performancePeriod]);

  useEffect(() => {
    if (activeTab !== "grid" || !pageVisible || deleted) return;
    const interval = window.setInterval(() => void loadTab("grid", true), 1_000);
    return () => window.clearInterval(interval);
  }, [activeTab, deleted, loadTab, pageVisible]);

  useEffect(() => {
    if (activeTab !== "activity" || !pageVisible || deleted) return;
    const interval = window.setInterval(() => void loadTab("activity", true), 1_000);
    return () => window.clearInterval(interval);
  }, [activeTab, deleted, loadTab, pageVisible]);

  useEffect(() => {
    if (activeTab !== "summary" || !pageVisible || deleted) return;
    const interval = window.setInterval(() => void loadTab("summary", true), 5_000);
    return () => window.clearInterval(interval);
  }, [activeTab, deleted, loadTab, pageVisible]);

  useEffect(() => {
    const cycleId = live?.cycle_id;
    if (cycleId === undefined || cycleId === null) return;
    if (lastCycleRef.current === undefined) {
      lastCycleRef.current = cycleId;
      return;
    }
    if (lastCycleRef.current === cycleId) return;
    lastCycleRef.current = cycleId;
    for (const tab of ["summary", "grid", "activity"] as DetailTab[]) {
      if (tab === "summary" || loadedTabsRef.current.has(tab)) {
        loadedTabsRef.current.delete(tab);
        void loadTab(tab, true);
      }
    }
  }, [live?.cycle_id, loadTab]);

  useEffect(
    () => () => {
      tabRequestsRef.current.forEach((controller) => controller.abort());
      tabRequestsRef.current.clear();
      tradesRequestRef.current?.abort();
    },
    [],
  );

  useEffect(() => {
    if (!showDeleteDialog) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [showDeleteDialog]);

  useEffect(() => {
    if (!showDeleteDialog) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && mutation !== "delete") {
        setShowDeleteDialog(false);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [mutation, showDeleteDialog]);

  const loadTrades = async (
    cycleId: number,
    cycleType?: "dca" | "trb",
  ) => {
    activityVersionRef.current += 1;
    const activityVersion = activityVersionRef.current;
    const tabRequest = tabRequestsRef.current.get("activity");
    tabRequest?.abort();
    tabRequestsRef.current.delete("activity");
    tradesRequestRef.current?.abort();
    const controller = new AbortController();
    tradesRequestRef.current = controller;
    setSelectedCycle(cycleId);
    setSelectedCycleType(cycleType);
    selectedCycleRef.current = cycleId;
    selectedCycleTypeRef.current = cycleType;
    setTradesLoading(true);
    setTabErrors((current) => ({ ...current, activity: "" }));
    try {
      const response = await getBotTrades(
        botId,
        accountId,
        cycleId,
        cycleType,
        controller.signal,
      );
      if (
        !controller.signal.aborted &&
        activityVersion === activityVersionRef.current &&
        selectedCycleRef.current === cycleId &&
        selectedCycleTypeRef.current === cycleType
      ) {
        setTrades(response);
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        setTabErrors((current) => ({
          ...current,
          activity: errorMessage(error, "Tur işlemleri alınamadı."),
        }));
      }
    } finally {
      if (tradesRequestRef.current === controller) {
        tradesRequestRef.current = null;
        if (!controller.signal.aborted) setTradesLoading(false);
      }
    }
  };

  const handleMutation = async (
    action: MutationName,
    convertBaseToQuote = false,
  ) => {
    if (mutationLockRef.current || deleted) return;
    if (action === "delete") {
      setShowDeleteDialog(false);
    }

    mutationLockRef.current = true;
    setMutation(action);
    setActionError("");
    setActionNotice("");
    try {
      if (action === "start") {
        const response = await startEngineBot(accountId, botId);
        setDetail((current) =>
          current
            ? { ...current, status: "running", display_status: "starting" }
            : current,
        );
        setLive((current) =>
          current ? { ...current, status: "starting" } : current,
        );
        setActionNotice(
          response.message || "Başlatma komutu motor kuyruğuna alındı.",
        );
      } else {
        const response = await deleteEngineBot(
          accountId,
          botId,
          convertBaseToQuote,
        );
        setDeleted(true);
        setActionNotice(response.message || "Bot silme komutu tamamlandı.");
        onDeleted(botId);
      }
    } catch (error) {
      if (
        error instanceof ApiError &&
        ["timeout", "network", "server", "unknown"].includes(error.kind)
      ) {
        await Promise.all([loadDetail(), loadLive()]);
        setMutationNeedsReview(true);
        setActionError(
          "Komutun sonucu kesinleşmedi. Tekrar komut vermeden önce sunucu durumunu doğrulayın.",
        );
        return;
      }
      setActionError(errorMessage(error, "İşlem tamamlanamadı."));
    } finally {
      mutationLockRef.current = false;
      setMutation(null);
    }
  };

  const engineStatus = deleted
    ? "deleted"
    : live?.status || detail?.display_status || detail?.status || "stopped";
  const status =
    engineStatus.toLowerCase() === "running" &&
    (live?.first_buy_pending ||
      live?.initial_allocation_done === false ||
      detail?.first_buy_pending ||
      detail?.initial_allocation_done === false)
      ? "waiting"
      : engineStatus;
  const isActive = ["running", "starting", "stopping", "waiting"].includes(
    status.toLowerCase(),
  );
  const tickAge = ageInSeconds(live?.last_tick_at);
  const staleThreshold = Math.max(30, (health?.tick_interval_s || 0) * 5);
  const isStale =
    Boolean(live?.stale) ||
    (isActive && tickAge !== null && tickAge > staleThreshold);
  const pair = splitTradingSymbol(detail?.symbol || "");
  const lastPrice = live?.last_price ?? detail?.current_price;
  const priceChange24h = toFiniteNumber(detail?.price_24h_change_pct);
  const dualPerformance = objectValue(performance?.dual_perf);
  const cashClosedCycles = Math.max(
    0,
    Math.round(readNumber(dualPerformance, ["cash_closed_cycles"]) ?? 0),
  );
  const coinClosedCycles = Math.max(
    0,
    Math.round(readNumber(dualPerformance, ["inventory_closed_cycles"]) ?? 0),
  );
  const cashCycleProfit =
    cashClosedCycles > 0
      ? readNumber(dualPerformance, ["cash_pnl_usdt"]) ??
        toFiniteNumber(performance?.pnl_usd)
      : null;
  const coinCycleProfit =
    coinClosedCycles > 0
      ? readNumber(dualPerformance, ["inventory_pnl_coin"])
      : null;
  const completedCycleCount = Object.keys(dualPerformance).length
    ? cashClosedCycles + coinClosedCycles
    : Math.max(0, Math.round(toFiniteNumber(performance?.cycles_count) ?? 0));
  const activeCycleId = toFiniteNumber(live?.cycle_id);
  const tourCount =
    activeCycleId ??
    Math.max(1, completedCycleCount + (isActive ? 1 : 0));
  const equityUnavailable =
    Boolean(live?.equity_unavailable) || Boolean(detail?.equity_unavailable);
  const configuredDynamic = detail?.config?.dynamic_mode;
  const runtimeDynamic = detail?.dynamic_mode;
  const configuredDynamicEnabled =
    typeof configuredDynamic === "boolean"
      ? configuredDynamic
      : configuredDynamic && typeof configuredDynamic === "object"
        ? (configuredDynamic as Record<string, unknown>).enabled !== false
        : null;
  const runtimeDynamicEnabled =
    typeof runtimeDynamic === "boolean"
      ? runtimeDynamic
      : runtimeDynamic && typeof runtimeDynamic === "object"
        ? (runtimeDynamic as Record<string, unknown>).enabled !== false
        : null;
  const dynamicEnabled = configuredDynamicEnabled ?? runtimeDynamicEnabled ?? false;
  const allGridPoints = grid
    ? [
        ...grid.grid_points.map((point) => ({
          point,
          fallback: "grid" as const,
        })),
        ...grid.profit_points.map((point) => ({
          point,
          fallback: "profit" as const,
        })),
      ]
    : [];
  const gridRegime = shortMainRegime(
    deepText(objectValue(objectValue(detail?.dynamic_mode).snapshot).multiplier, [
      "regime_label",
      "regime",
    ]) ||
    deepText(objectValue(detail?.dynamic_mode).snapshot, ["regime"]) ||
    deepText(detail?.dynamic_mode, [
      "display_regime_label",
      "preview_regime_label",
      "regime_label",
      "regime",
      "regime_tag",
    ]) ||
    deepText(detail?.config, [
      "display_regime_label",
      "regime_label",
      "regime_tag",
    ]) ||
    "Manuel ayarlar",
  );
  const gridDirection = gridDirectionLabel(
    deepText(grid?.meta, ["cycle_grid_side"]) ||
      deepText(grid?.state, ["cycle_grid_side"]) ||
      deepText(detail?.state, ["cycle_grid_side"]),
  );
  const visibleTrades = (trades?.trades || []).filter((trade) => {
    if (!initialBuyTrade) return true;
    if (trade.id !== undefined && initialBuyTrade.id !== undefined) {
      return String(trade.id) !== String(initialBuyTrade.id);
    }
    return !(
      String(trade.side || "").toUpperCase() === "BUY" &&
      String(trade.ts ?? "") === String(initialBuyTrade.ts ?? "") &&
      Number(trade.qty) === Number(initialBuyTrade.qty) &&
      Number(trade.price) === Number(initialBuyTrade.price)
    );
  });
  const refreshActiveTab = () => {
    if (activeTab === "summary") {
      const controller = new AbortController();
      void loadDetail(controller.signal);
    } else {
      loadedTabsRef.current.delete(activeTab);
      void loadTab(activeTab, true);
    }
  };

  if (detailLoading && !detail) return <LoadingPanel />;

  if (detailError && !detail) {
    return (
      <ErrorPanel
        message={detailError}
        onRetry={() => {
          const controller = new AbortController();
          void loadDetail(controller.signal);
        }}
      />
    );
  }

  return (
    <section className="space-y-5 text-neutral-200">
      <header className="relative overflow-hidden rounded-[1.75rem] border border-fuchsia-300/15 bg-[#191a21]">
        <div className="pointer-events-none absolute -right-28 -top-32 h-96 w-96 rounded-full bg-fuchsia-400/10 blur-3xl" />
        <div className="relative grid gap-6 p-5 sm:p-7 xl:grid-cols-[1fr_auto] xl:items-end">
          <div className="min-w-0">
            <div className="flex items-center gap-4">
              <CoinLogo symbol={detail?.symbol} size={64} eager />
              <div className="min-w-0">
                <p className="text-[10px] font-black uppercase tracking-[0.2em] text-fuchsia-200">
                  ayserose canlı bot merkezi
                </p>
                <div className="mt-1 flex flex-wrap items-center gap-2">
                  <h1 className="truncate text-2xl font-black tracking-[-0.03em] text-white sm:text-3xl">
                    {detail?.symbol ? pair.label : `Bot #${botId}`}
                  </h1>
                  <StatusBadge status={status} />
                  {isStale && (
                    <span className="inline-flex items-center gap-1 rounded-full border border-amber-400/30 bg-amber-400/10 px-2.5 py-1 text-xs font-semibold text-amber-300">
                      <WifiOff className="h-3 w-3" />
                      Veri gecikiyor
                    </span>
                  )}
                </div>
                <div className="mt-2 flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-1">
                  <span
                    className="max-w-full break-all font-mono text-base font-black text-white sm:text-lg"
                    title={`${coinPrice(lastPrice)} ${pair.quote}`}
                  >
                    <LiveValue value={lastPrice}>
                      {coinPrice(lastPrice)} {pair.quote}
                    </LiveValue>
                  </span>
                  {priceChange24h !== null && (
                    <span
                      className={`font-mono text-sm font-black ${
                        priceChange24h >= 0 ? "text-emerald-300" : "text-red-300"
                      }`}
                    >
                      <LiveValue value={priceChange24h} toneBySign>
                        {priceChange24h >= 0 ? "+" : ""}
                        {priceChange24h.toLocaleString("tr-TR", {
                          maximumFractionDigits: 2,
                          minimumFractionDigits: 2,
                        })}
                        %
                      </LiveValue>
                    </span>
                  )}
                </div>
                <p className="mt-2 text-xs font-semibold text-neutral-500">
                  Başlangıç · {dateTimeMinute(detail?.started_at)}
                </p>
              </div>
            </div>

            <div className="mt-6 grid max-w-2xl grid-cols-1 gap-2 min-[390px]:grid-cols-2 xl:grid-cols-4">
              {[
                {
                  label: "Bot değeri",
                  value: equityUnavailable
                    ? "Fiyat bekleniyor"
                    : money(live?.equity ?? detail?.current_usd),
                  liveValue: live?.equity ?? detail?.current_usd,
                },
                {
                  label: "Aktif tur",
                  value:
                    live?.cycle_id === null || live?.cycle_id === undefined
                      ? "—"
                      : `#${live.cycle_id}`,
                  liveValue: undefined,
                },
                {
                  label: `${pair.base || "Base"} bakiyesi`,
                  value: heroBalance(
                    live?.base_balance ?? detail?.state?.base_balance,
                    pair.base || "BASE",
                  ),
                  liveValue:
                    live?.base_balance ?? detail?.state?.base_balance,
                },
                {
                  label: `${pair.quote || "Quote"} bakiyesi`,
                  value: heroBalance(
                    live?.quote_balance ?? detail?.state?.quote_balance,
                    pair.quote || "USDT",
                  ),
                  liveValue:
                    live?.quote_balance ?? detail?.state?.quote_balance,
                },
              ].map(({ label, value, liveValue }) => (
                <div key={label} className="rounded-xl border border-white/8 bg-black/15 px-3 py-2.5 backdrop-blur">
                  <p className="text-[9px] font-black uppercase tracking-wider text-neutral-600">{label}</p>
                  <p className="mt-1 truncate text-xs font-black text-white" title={value}>
                    {liveValue !== undefined ? (
                      <LiveValue value={liveValue}>
                        {value}
                      </LiveValue>
                    ) : (
                      value
                    )}
                  </p>
                </div>
              ))}
            </div>
          </div>

          <div className="grid w-full grid-cols-1 items-center gap-2 xl:flex xl:w-auto xl:flex-wrap xl:justify-end">
            {!isActive && (
              <button
                type="button"
                disabled={mutation !== null || deleted || mutationNeedsReview}
                onClick={() => void handleMutation("start")}
                className="inline-flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-emerald-300 to-cyan-300 px-4 text-xs font-black text-neutral-950 transition hover:brightness-110 disabled:cursor-wait disabled:opacity-50 xl:w-auto xl:min-w-24"
              >
                {mutation === "start" ? (
                  <LoaderCircle className="h-4 w-4 animate-spin" />
                ) : (
                  <Play className="h-4 w-4" />
                )}
                Başlat
              </button>
            )}
            <button
              type="button"
              disabled={mutation !== null || deleted || mutationNeedsReview}
              onClick={() => setShowDeleteDialog(true)}
              title="Botu güvenle durdur ve sil"
              className="inline-flex h-11 w-full items-center justify-center gap-2 rounded-xl border border-red-400/20 px-4 text-xs font-black text-red-300 transition hover:bg-red-400/10 disabled:cursor-not-allowed disabled:opacity-40 xl:w-auto xl:min-w-24"
            >
              {mutation === "delete" ? (
                <LoaderCircle className="h-4 w-4 animate-spin" />
              ) : (
                <Trash2 className="h-4 w-4" />
              )}
              Sil
            </button>
          </div>
        </div>

        <nav
          aria-label="Bot ayrıntı bölümleri"
          role="tablist"
          className="relative grid grid-cols-3 gap-1 border-t border-white/8 bg-black/10 p-2 sm:px-4"
        >
          {TABS.map((tab) => {
            const Icon = tab.icon;
            const selected = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                type="button"
                role="tab"
                aria-selected={selected}
                onClick={() => setActiveTab(tab.id)}
                className={`relative flex min-w-0 items-center justify-center gap-2 rounded-xl px-2 py-3 text-xs font-black transition sm:px-4 ${
                  selected
                    ? "bg-fuchsia-300/10 text-fuchsia-100"
                    : "text-neutral-500 hover:bg-white/[0.035] hover:text-neutral-200"
                }`}
              >
                <Icon className="h-4 w-4 shrink-0" />
                <span className="truncate sm:hidden">{tab.shortLabel}</span>
                <span className="hidden truncate sm:inline">{tab.label}</span>
              </button>
            );
          })}
        </nav>
      </header>

      {deleted && (
        <div className="flex items-center gap-3 rounded-xl border border-emerald-400/20 bg-emerald-400/10 p-4 text-sm text-emerald-200">
          <CheckCircle2 className="h-5 w-5 shrink-0" />
          Bot silindi. Bu ekran artık canlı veri istemeyecek.
        </div>
      )}
      {actionError && <ErrorPanel message={actionError} />}
      {mutationNeedsReview && (
        <button
          type="button"
          onClick={async () => {
            await Promise.all([loadDetail(), loadLive()]);
            setMutationNeedsReview(false);
            setActionError("");
            setActionNotice("Bot durumu sunucudan yeniden doğrulandı.");
          }}
          className="rounded-xl border border-amber-300/30 bg-amber-300/5 px-4 py-3 text-sm font-black text-amber-200"
        >
          Sunucu durumunu yeniden doğrula
        </button>
      )}
      {actionNotice && !deleted && (
        <div
          role="status"
          className="flex items-center gap-2 rounded-xl border border-emerald-400/20 bg-emerald-400/10 p-4 text-sm text-emerald-200"
        >
          <CheckCircle2 className="h-4 w-4 shrink-0" />
          {actionNotice}
        </div>
      )}
      {liveError && (
        <ErrorPanel
          message={`${liveError} Son başarılı veri ekranda tutuluyor.`}
          onRetry={() => void loadLive()}
        />
      )}
      {health && health.alerts.length > 0 && (
        <section className="hidden rounded-2xl border border-amber-300/20 bg-amber-300/[0.055] p-5 md:block">
          <div className="flex items-center gap-2">
            <ShieldAlert className="h-5 w-5 text-amber-200" />
            <h2 className="font-black text-amber-100">
              Motor uyarıları · {health.alerts.length}
            </h2>
          </div>
          <div className="mt-3 grid gap-3 xl:grid-cols-2">
            {health.alerts.map((alert, index) => {
              const cause = String(alert.cause || alert.message || "Motor denetimi uyarı verdi.");
              const actions = Array.isArray(alert.actions)
                ? alert.actions.map(String).filter(Boolean)
                : [];
              return (
                <article
                  key={`${alert.code || "warning"}-${index}`}
                  className="rounded-xl border border-amber-200/10 bg-black/15 p-4"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded-md bg-amber-200/10 px-2 py-1 font-mono text-[10px] font-black text-amber-100">
                      {alert.code || "ENGINE_WARNING"}
                    </span>
                    <strong className="text-xs text-white">
                      {alert.message || cause}
                    </strong>
                  </div>
                  <p className="mt-2 text-xs leading-5 text-neutral-400">{cause}</p>
                  {actions.length > 0 && (
                    <ul className="mt-2 space-y-1 text-[11px] leading-5 text-neutral-500">
                      {actions.map((action) => (
                        <li key={action}>• {action}</li>
                      ))}
                    </ul>
                  )}
                </article>
              );
            })}
          </div>
        </section>
      )}

      {tabErrors[activeTab] && (
        <ErrorPanel
          message={tabErrors[activeTab] || "Veriler alınamadı."}
          onRetry={refreshActiveTab}
        />
      )}

      {activeTab === "summary" && (
        <div className="space-y-5">
          {detail && (
            <StrategyParametersCard
              detail={detail}
              dynamicEnabled={dynamicEnabled}
              cycleId={toFiniteNumber(live?.cycle_id)}
              cycleOpenedAt={live?.cycle_opened_at ?? null}
              botStartedAt={detail.started_at ?? null}
              regime={gridRegime}
              tourCount={tourCount}
              performance={performance}
              liveDailyUsd={live?.daily_pnl_usd}
              liveDailyPct={live?.daily_pnl_pct}
            />
          )}

          <section className="space-y-5">
            <div className="flex items-end justify-between gap-3">
              <div>
                <p className="flex items-center gap-2 text-[10px] font-black uppercase tracking-[0.18em] text-fuchsia-200">
                  <BarChart3 className="h-4 w-4" />
                  Performans
                </p>
                <p className="mt-1 text-xs text-neutral-500">
                  Bakiye, alpha ve komisyon özeti
                </p>
              </div>
            </div>

            {tabLoading === "summary" && !performance ? (
              <LoadingPanel />
            ) : performance ? (
              <>
                <div className="rounded-2xl border border-white/8 bg-[#1e2026] p-3">
                  <div className="flex gap-1 overflow-x-auto">
                    {(
                      [
                        ["all", "Tüm dönem"],
                        ["day", "Gün"],
                        ["week", "Hafta"],
                        ["month", "Ay"],
                      ] as Array<[PerformancePeriod, string]>
                    ).map(([id, label]) => (
                      <button
                        key={id}
                        type="button"
                        onClick={() => setPerformancePeriod(id)}
                        className={`shrink-0 rounded-xl px-3 py-2 text-xs font-black transition ${
                          performancePeriod === id
                            ? "bg-fuchsia-300/10 text-fuchsia-100"
                            : "text-neutral-500 hover:bg-white/[0.035] hover:text-white"
                        }`}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                </div>

                <section className="rounded-2xl border border-fuchsia-300/12 bg-[#1e2026] p-4 sm:p-5">
                  <div className="mb-4 flex flex-wrap items-end justify-between gap-2">
                    <div>
                      <p className="text-[10px] font-black uppercase tracking-[0.16em] text-fuchsia-200">
                        Kesinleşen tur kazancı
                      </p>
                      <p className="mt-1 text-xs leading-5 text-neutral-500">
                        Yalnız tamamlanarak kesinleşmiş turların sonuçları
                      </p>
                    </div>
                    <span className="rounded-full border border-white/8 bg-white/[0.035] px-3 py-1.5 text-[10px] font-black text-neutral-300">
                      Toplam {completedCycleCount} tur tamamlandı
                    </span>
                  </div>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <ClosedCycleProfitCard
                      label="USDT kazancı"
                      value={cashCycleProfit}
                      unit="USDT"
                      completedCycles={cashClosedCycles}
                    />
                    <ClosedCycleProfitCard
                      label={`${pair.base || "Coin"} kazancı`}
                      value={coinCycleProfit}
                      unit={pair.base || "Coin"}
                      completedCycles={coinClosedCycles}
                    />
                  </div>
                </section>

                <section className="rounded-2xl border border-cyan-300/12 bg-[#1e2026] p-4 sm:p-5">
                  <div>
                    <p className="text-[10px] font-black uppercase tracking-[0.16em] text-cyan-200">
                      Alpha performansı
                    </p>
                    <h2 className="mt-1 text-lg font-black text-white">
                      Botun pariteye göre ürettiği ek performans
                    </h2>
                    <p className="mt-2 max-w-3xl text-xs leading-5 text-neutral-500">
                      Alpha, bot bakiyesindeki yüzdesel değişimden aynı dönemdeki coin
                      fiyat değişiminin çıkarılmasıdır. Pozitif değer botun yalnızca coini
                      elde tutmaya göre daha iyi, negatif değer daha zayıf kaldığını gösterir.
                    </p>
                  </div>
                  <div className="mt-4 grid gap-3 sm:grid-cols-3">
                    <Metric
                      label="Bot bakiye değişimi"
                      value={percent(performance.balance_change_pct)}
                      tone={metricTone(performance.balance_change_pct)}
                    />
                    <Metric
                      label={`${pair.base || "Coin"} fiyat değişimi`}
                      value={percent(performance.price_change_pct)}
                      tone={metricTone(performance.price_change_pct)}
                    />
                    <Metric
                      label="Net alpha"
                      value={percent(performance.real_performance_pct)}
                      tone={metricTone(performance.real_performance_pct)}
                      liveValue={performance.real_performance_pct}
                    />
                  </div>
                </section>

                <section className="rounded-2xl border border-amber-300/12 bg-[#1e2026] p-4 sm:p-5">
                  <div>
                    <p className="text-[10px] font-black uppercase tracking-[0.16em] text-amber-200">
                      Komisyon etkisi
                    </p>
                    <h2 className="mt-1 text-lg font-black text-white">
                      İşlem maliyetlerinin açık dökümü
                    </h2>
                    <p className="mt-2 max-w-3xl text-xs leading-5 text-neutral-500">
                      Komisyon toplamı seçili dönemdeki gerçekleşen işlemlerden gelir.
                    </p>
                  </div>
                  <div className="mt-4 grid gap-3 sm:grid-cols-2">
                    <Metric label="Toplam komisyon" value={money(performance.fees_usd)} />
                    <Metric
                      label="İşlem sayısı"
                      value={decimal(performance.trades_count, 0)}
                    />
                  </div>
                </section>
              </>
            ) : tabErrors.summary ? null : (
              <EmptyPanel message="Performans verisi henüz yok." />
            )}
          </section>
        </div>
      )}

      {activeTab === "grid" &&
        (tabLoading === "grid" && !grid ? (
          <LoadingPanel />
        ) : grid ? (
          <div className="space-y-5">
            <GridCommandCenter
              grid={grid}
              entries={allGridPoints}
              direction={gridDirection}
            />
          </div>
        ) : null)}

      {activeTab === "activity" &&
        (tabLoading === "activity" && !cycles ? (
          <LoadingPanel />
        ) : (
          <div className="space-y-5">
            <div className="rounded-2xl border border-neutral-800 bg-[#1e2026] p-5">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <h2 className="font-semibold text-white">Turlar</h2>
                  <p className="mt-1 text-xs text-neutral-500">
                    Bir tur seçildiğinde yalnız o turun işlemleri alınır.
                  </p>
                </div>
                <span className="text-xs text-neutral-500">
                  Toplam{" "}
                  {
                    new Set([
                      ...(cycles?.cycles || []),
                      ...(cycles?.dca_cycles || []),
                      ...(cycles?.trb_cycles || []),
                    ]).size
                  }{" "}
                  tur
                </span>
              </div>
              {cycles &&
              (cycles.cycles.length ||
                cycles.dca_cycles.length ||
                cycles.trb_cycles.length) ? (
                <div className="mt-4 flex gap-2 overflow-x-auto pb-1">
                  {[
                    ...cycles.dca_cycles.map((cycle) => ({
                      cycle,
                      type: "dca" as const,
                    })),
                    ...cycles.trb_cycles.map((cycle) => ({
                      cycle,
                      type: "trb" as const,
                    })),
                    ...cycles.cycles
                      .filter(
                        (cycle) =>
                          !cycles.dca_cycles.includes(cycle) &&
                          !cycles.trb_cycles.includes(cycle),
                      )
                      .map((cycle) => ({
                        cycle,
                        type: undefined,
                      })),
                  ]
                    .sort((left, right) => right.cycle - left.cycle)
                    .map(({ cycle, type }) => (
                      <button
                        key={`${type || "cycle"}-${cycle}`}
                        type="button"
                        onClick={() => void loadTrades(cycle, type)}
                        className={`shrink-0 rounded-lg border px-3 py-2 text-xs font-semibold transition ${
                          selectedCycle === cycle && selectedCycleType === type
                            ? "border-fuchsia-300/40 bg-fuchsia-300/10 text-fuchsia-100"
                            : "border-neutral-700 bg-neutral-800 text-neutral-400 hover:text-white"
                        }`}
                      >
                        {type === "trb" ? "TRB" : "Tur"} #{cycle}
                      </button>
                    ))}
                </div>
              ) : (
                <div className="mt-4">
                  <EmptyPanel message="Henüz tamamlanmış veya açık tur yok." />
                </div>
              )}
            </div>

            {trades?.cycle_summary && (
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <Metric
                  label="Tur"
                  value={
                    selectedCycle
                      ? `${selectedCycleType === "trb" || trades.cycle_type === "trb" ? "TRB" : "Tur"} #${selectedCycle}`
                      : "Tüm turlar"
                  }
                />
                <Metric
                  label="Referans fiyat"
                  value={
                    toFiniteNumber(trades.cycle_summary.reference_price) !== null
                      ? `${coinPrice(trades.cycle_summary.reference_price)} ${pair.quote}`
                      : "—"
                  }
                />
                <Metric
                  label="İşlem sayısı"
                  value={decimal(
                    trades.cycle_summary.trade_count ?? trades.trades.length,
                    0,
                  )}
                />
                {trades.cycle_summary.is_open !== true && (
                  <Metric
                    label={`Tur sonucu · ${
                      String(trades.cycle_summary.result_kind || "") === "coin"
                        ? pair.base
                        : pair.quote
                    }`}
                    value={
                      toFiniteNumber(trades.cycle_summary.result_amount) !== null
                        ? `${
                            Number(trades.cycle_summary.result_amount) > 0 ? "+" : ""
                          }${
                            String(trades.cycle_summary.result_kind || "") === "coin"
                              ? assetQuantity(trades.cycle_summary.result_amount)
                              : quoteAmount(trades.cycle_summary.result_amount)
                          } ${
                            trades.cycle_summary.result_unit ||
                            (String(trades.cycle_summary.result_kind || "") === "coin"
                              ? pair.base
                              : pair.quote)
                          } · ${percent(trades.cycle_summary.result_pct)}`
                        : "—"
                    }
                    tone={metricTone(
                      trades.cycle_summary.result_amount,
                    )}
                  />
                )}
              </div>
            )}

            <div className="overflow-hidden rounded-2xl border border-neutral-800 bg-[#1e2026]">
              <div className="flex items-center justify-between border-b border-neutral-800 p-5">
                <h2 className="font-semibold text-white">İşlemler</h2>
                {tradesLoading && (
                  <LoaderCircle className="h-4 w-4 animate-spin text-[#f0b90b]" />
                )}
              </div>
              {visibleTrades.length ? (
                <div className="grid gap-3 p-3 sm:p-4 xl:grid-cols-2">
                  {visibleTrades.map((trade, index) => (
                    <div key={String(trade.id ?? `${trade.ts}-${index}`)}>
                      <TradeActivityCard trade={trade} pair={pair} />
                    </div>
                  ))}
                </div>
              ) : (
                <div className="p-5">
                  <EmptyPanel message="Seçilen tur için işlem kaydı yok." />
                </div>
              )}
            </div>

            {selectedCycle === 1 && initialBuyTrade && (
              <section>
                <p className="mb-2 text-[10px] font-black uppercase tracking-[0.16em] text-neutral-500">
                  Tur başlangıcı
                </p>
                <TradeActivityCard trade={initialBuyTrade} pair={pair} initial />
              </section>
            )}

            {trades?.cycle_summary && trades.cycle_summary.is_open !== true && (
              <CycleParametersCard
                summary={trades.cycle_summary}
                cycleId={selectedCycle}
              />
            )}
          </div>
        ))}

      {showDeleteDialog && (
        <div
          className="fixed inset-0 z-[60] grid place-items-center bg-black/80 p-4 backdrop-blur-sm"
          role="dialog"
          aria-modal="true"
          aria-labelledby="detail-delete-title"
        >
          <section className="w-full max-w-lg overflow-hidden rounded-[1.5rem] border border-red-300/15 bg-[#191a20] shadow-2xl">
            <header className="flex items-start justify-between gap-4 border-b border-white/8 p-5">
              <div className="flex items-center gap-3">
                <CoinLogo symbol={detail?.symbol} size={46} eager />
                <div>
                  <p className="text-[10px] font-black uppercase tracking-wider text-red-200">
                    Kalıcı işlem
                  </p>
                  <h2 id="detail-delete-title" className="mt-1 text-lg font-black text-white">
                    {pair.label} botunu sil
                  </h2>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setShowDeleteDialog(false)}
                disabled={mutation === "delete"}
                aria-label="Silme penceresini kapat"
                className="grid h-9 w-9 place-items-center rounded-xl text-neutral-500 hover:bg-white/5 hover:text-white disabled:opacity-40"
              >
                <X className="h-4 w-4" />
              </button>
            </header>
            <div className="space-y-3 p-5">
              <p className="text-sm leading-6 text-neutral-400">
                Bot aktifse önce otomatik olarak güvenle durdurulur. Eldeki <strong className="text-white">{pair.base}</strong> varlığının nasıl korunacağını seçin.
              </p>
              <button
                type="button"
                onClick={() => void handleMutation("delete", true)}
                disabled={mutation === "delete"}
                className="w-full rounded-2xl border border-red-300/15 bg-red-300/[0.05] p-4 text-left transition hover:bg-red-300/[0.08] disabled:opacity-40"
              >
                <span className="block text-sm font-black text-red-100">
                  Varlığı {pair.quote}'a çevir ve sil
                </span>
                <span className="mt-1 block text-xs leading-5 text-neutral-500">
                  Base bakiye piyasa emriyle quote bakiyeye dönüştürülür.
                </span>
              </button>
              <button
                type="button"
                onClick={() => void handleMutation("delete", false)}
                disabled={mutation === "delete"}
                className="w-full rounded-2xl border border-white/10 bg-white/[0.025] p-4 text-left transition hover:bg-white/[0.05] disabled:opacity-40"
              >
                <span className="block text-sm font-black text-white">
                  Varlığı cüzdanda bırak ve sil
                </span>
                <span className="mt-1 block text-xs leading-5 text-neutral-500">
                  Satış yapılmaz; mevcut coin bakiyesi korunur.
                </span>
              </button>
            </div>
          </section>
        </div>
      )}
    </section>
  );
}
