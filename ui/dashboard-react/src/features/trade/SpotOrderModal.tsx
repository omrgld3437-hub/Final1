import {
  AlertTriangle,
  Info,
  LoaderCircle,
  RefreshCw,
  X,
} from "lucide-react";
import {
  type FormEvent,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import { ApiError, apiRequest } from "../../core/api/http";
import CoinLogo, {
  splitTradingSymbol,
} from "../../components/coin/CoinLogo";
import LiveValue from "../../components/live/LiveValue";
import {
  compareDecimal,
  divideAndQuantize,
  isPositiveDecimal,
  multiplyByRatio,
  multiplyDecimal,
  normalizeDecimal,
  quantizeDown,
} from "./decimal";

export type SpotOrderSide = "BUY" | "SELL";
export type SpotOrderType = "MARKET" | "LIMIT";

export interface SpotOrderResult {
  success: true;
  order: unknown;
  tx_revision?: string;
}

export interface SpotOrderModalProps {
  accountId: number;
  symbol: string;
  side: SpotOrderSide;
  onClose: () => void;
  onSuccess: (result: SpotOrderResult) => void | Promise<void>;
}

interface QuickDataResponse {
  ok?: boolean;
  error_code?: string;
  symbol?: string;
  price?: string | number;
  priceChange24h?: string | number;
  baseAsset?: string;
  quoteAsset?: string;
  baseAvailable?: string | number;
  quoteAvailable?: string | number;
  baseLockedByBots?: string | number;
  quoteLockedByBots?: string | number;
  filters?: {
    tickSize?: string | number;
    stepSize?: string | number;
    minQty?: string | number;
    minNotional?: string | number;
  };
}

interface LivePriceEntry {
  price?: string | number;
  change24h?: string | number | null;
}

interface QuickData {
  symbol: string;
  price: string;
  priceChange24h: number;
  baseAsset: string;
  quoteAsset: string;
  baseAvailable: string;
  quoteAvailable: string;
  baseLockedByBots: string;
  quoteLockedByBots: string;
  tickSize: string;
  stepSize: string;
  minQty: string;
  minNotional: string;
}

interface OrderPayload {
  account_id: number;
  symbol: string;
  side: SpotOrderSide;
  type: SpotOrderType;
  quantity?: number;
  quote_order_qty?: number;
  price?: number;
}

interface PreparedOrder {
  payload: OrderPayload;
  quantity: string;
  notional: string;
  price: string;
}

const PERCENT_OPTIONS = [25, 50, 75, 100] as const;
const QUOTE_STEP = "0.00000001";
const activeOrderFingerprints = new Set<string>();

function decimalOrNull(value: unknown): string | null {
  if (typeof value !== "string" && typeof value !== "number") return null;
  return normalizeDecimal(value);
}

function normalizeQuickData(
  response: QuickDataResponse,
  requestedSymbol: string,
): QuickData {
  if (response.ok === false) {
    throw new Error(
      response.error_code === "INVALID_SYMBOL"
        ? "Bu işlem çifti geçerli değil."
        : "İşlem bilgileri alınamadı.",
    );
  }

  const price = decimalOrNull(response.price);
  const baseAvailable = decimalOrNull(response.baseAvailable);
  const quoteAvailable = decimalOrNull(response.quoteAvailable);
  const baseLockedByBots = decimalOrNull(response.baseLockedByBots);
  const quoteLockedByBots = decimalOrNull(response.quoteLockedByBots);
  const tickSize = decimalOrNull(response.filters?.tickSize);
  const stepSize = decimalOrNull(response.filters?.stepSize);
  const minQty = decimalOrNull(response.filters?.minQty);
  const minNotional = decimalOrNull(response.filters?.minNotional);

  if (
    !price ||
    !baseAvailable ||
    !quoteAvailable ||
    !baseLockedByBots ||
    !quoteLockedByBots ||
    !tickSize ||
    !stepSize ||
    !minQty ||
    !minNotional ||
    !isPositiveDecimal(price) ||
    !isPositiveDecimal(tickSize) ||
    !isPositiveDecimal(stepSize) ||
    !isPositiveDecimal(minQty) ||
    !isPositiveDecimal(minNotional) ||
    !response.baseAsset ||
    !response.quoteAsset
  ) {
    throw new Error(
      "Canlı fiyat, bakiye veya işlem kuralları doğrulanamadı. Emir ekranı güvenlik için kapalı tutuldu.",
    );
  }

  return {
    symbol: String(response.symbol || requestedSymbol).toUpperCase(),
    price,
    priceChange24h: Number(response.priceChange24h || 0),
    baseAsset: response.baseAsset.toUpperCase(),
    quoteAsset: response.quoteAsset.toUpperCase(),
    baseAvailable,
    quoteAvailable,
    baseLockedByBots,
    quoteLockedByBots,
    tickSize,
    stepSize,
    minQty,
    minNotional,
  };
}

function formatAmount(value: string, maximumFractionDigits = 8): string {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return value;
  return new Intl.NumberFormat("tr-TR", {
    maximumFractionDigits,
  }).format(numeric);
}

function cleanDecimalInput(value: string): string {
  const cleaned = value
    .replace(",", ".")
    .replace(/[^\d.]/g, "")
    .slice(0, 64);
  const separator = cleaned.indexOf(".");
  if (separator === -1) return cleaned;
  return `${cleaned.slice(0, separator + 1)}${cleaned
    .slice(separator + 1)
    .replace(/\./g, "")}`;
}

function apiErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) {
    return error instanceof Error ? error.message : "Emir gönderilemedi.";
  }
  const body =
    error.details && typeof error.details === "object"
      ? (error.details as Record<string, unknown>)
      : null;
  const detail =
    body?.detail && typeof body.detail === "object"
      ? (body.detail as Record<string, unknown>)
      : null;
  const detailedMessage =
    typeof detail?.detail === "string"
      ? detail.detail
      : typeof detail?.message === "string"
        ? detail.message
        : null;
  const requestSuffix = error.requestId
    ? ` (İstek: ${error.requestId})`
    : "";
  return `${detailedMessage || error.message}${requestSuffix}`;
}

function isUnknownMutationOutcome(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    (error.kind === "timeout" ||
      error.kind === "network" ||
      error.kind === "server" ||
      error.kind === "unknown")
  );
}

export default function SpotOrderModal({
  accountId,
  symbol,
  side: initialSide,
  onClose,
  onSuccess,
}: SpotOrderModalProps) {
  const normalizedSymbol = symbol.trim().toUpperCase();
  const titleId = useId();
  const descriptionId = useId();
  const errorId = useId();
  const quantityHelpId = useId();
  const priceHelpId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const submitGuardRef = useRef(false);
  const submittingRef = useRef(false);

  const [quickData, setQuickData] = useState<QuickData | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [orderSide, setOrderSide] = useState<SpotOrderSide>(initialSide);
  const [orderType, setOrderType] = useState<SpotOrderType>("MARKET");
  const [quantity, setQuantity] = useState("");
  const [quoteAmount, setQuoteAmount] = useState("");
  const [limitPrice, setLimitPrice] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [unknownOutcome, setUnknownOutcome] = useState(false);

  submittingRef.current = submitting;

  useEffect(() => {
    previousFocusRef.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const focusFrame = window.requestAnimationFrame(() => {
      closeButtonRef.current?.focus();
    });

    const handleKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape" && !submittingRef.current) {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab" || !dialogRef.current) return;
      const focusable = (
        Array.from(
          dialogRef.current.querySelectorAll(
            'button:not([disabled]), input:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
          ),
        ) as HTMLElement[]
      ).filter((element) => !element.hasAttribute("aria-hidden"));
      if (focusable.length === 0) {
        event.preventDefault();
        dialogRef.current.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      window.cancelAnimationFrame(focusFrame);
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = previousOverflow;
      previousFocusRef.current?.focus();
    };
  }, [onClose]);

  useEffect(() => {
    const controller = new AbortController();
    let retryTimer = 0;
    setLoading(true);
    setLoadError("");
    setQuickData(null);
    const params = new URLSearchParams({
      account_id: String(accountId),
      symbol: normalizedSymbol,
    });

    void apiRequest<QuickDataResponse>(
      `/api/spot/quick_data?${params.toString()}`,
      {
        signal: controller.signal,
        dedupe: false,
        timeoutMs: 15_000,
      },
    )
      .then((response) => {
        if (controller.signal.aborted) return;
        const normalized = normalizeQuickData(response, normalizedSymbol);
        setQuickData(normalized);
        setLimitPrice(
          quantizeDown(normalized.price, normalized.tickSize) ||
            normalized.price,
        );
        setLoading(false);
      })
      .catch((requestError: unknown) => {
        if (controller.signal.aborted) return;
        const message = apiErrorMessage(requestError);
        const invalidSymbol = message.includes("işlem çifti geçerli değil");
        if (!invalidSymbol && loadAttempt < 2) {
          retryTimer = window.setTimeout(
            () => setLoadAttempt((attempt) => attempt + 1),
            loadAttempt === 0 ? 450 : 1_000,
          );
          return;
        }
        setLoadError(message);
        setLoading(false);
      });

    return () => {
      controller.abort();
      window.clearTimeout(retryTimer);
    };
  }, [accountId, normalizedSymbol, loadAttempt]);

  useEffect(() => {
    if (!quickData?.symbol) return;
    let stopped = false;
    let inFlight = false;
    let activeController: AbortController | null = null;

    const loadLivePrice = async () => {
      if (stopped || inFlight || document.visibilityState !== "visible") return;
      inFlight = true;
      activeController = new AbortController();
      try {
        const response = await apiRequest<Record<string, LivePriceEntry>>(
          `/api/data/prices?slim=1&symbols=${encodeURIComponent(normalizedSymbol)}`,
          {
            signal: activeController.signal,
            dedupe: false,
            timeoutMs: 3_000,
          },
        );
        const entry = response?.[normalizedSymbol];
        const nextPrice = decimalOrNull(entry?.price);
        if (!stopped && nextPrice && isPositiveDecimal(nextPrice)) {
          setQuickData((current) =>
            current
              ? {
                  ...current,
                  price: nextPrice,
                  priceChange24h:
                    entry?.change24h === null || entry?.change24h === undefined
                      ? current.priceChange24h
                      : Number(entry.change24h),
                }
              : current,
          );
        }
      } catch {
        // Son başarılı fiyat korunur; sonraki yarım saniyelik tur yeniden dener.
      } finally {
        inFlight = false;
      }
    };

    void loadLivePrice();
    const timer = window.setInterval(loadLivePrice, 500);
    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") void loadLivePrice();
    };
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      stopped = true;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisibilityChange);
      activeController?.abort();
    };
  }, [normalizedSymbol, quickData?.symbol]);

  const effectivePrice =
    orderType === "LIMIT" ? limitPrice : quickData?.price || "";
  const estimatedNotional = useMemo(() => {
    if (orderType === "MARKET" && orderSide === "BUY") {
      return normalizeDecimal(quoteAmount) || "0";
    }
    return multiplyDecimal(quantity || "0", effectivePrice || "0") || "0";
  }, [effectivePrice, orderSide, orderType, quantity, quoteAmount]);
  const estimatedQuantity = useMemo(() => {
    if (!quickData) return "0";
    if (orderType === "MARKET" && orderSide === "BUY") {
      return (
        divideAndQuantize(
          quoteAmount || "0",
          quickData.price,
          quickData.stepSize,
        ) || "0"
      );
    }
    return quantizeDown(quantity || "0", quickData.stepSize) || "0";
  }, [orderSide, orderType, quantity, quickData, quoteAmount]);

  function resetOrderValues(nextSide = orderSide) {
    setQuantity("");
    setQuoteAmount("");
    setError("");
    if (nextSide === "BUY" && orderType === "LIMIT" && quickData) {
      setLimitPrice(
        quantizeDown(quickData.price, quickData.tickSize) || quickData.price,
      );
    }
  }

  function selectSide(nextSide: SpotOrderSide) {
    if (submitting || unknownOutcome || nextSide === orderSide) return;
    setOrderSide(nextSide);
    resetOrderValues(nextSide);
  }

  function selectType(nextType: SpotOrderType) {
    if (submitting || unknownOutcome || nextType === orderType) return;
    setOrderType(nextType);
    setQuantity("");
    setQuoteAmount("");
    setError("");
    if (nextType === "LIMIT" && quickData) {
      setLimitPrice(
        quantizeDown(quickData.price, quickData.tickSize) || quickData.price,
      );
    }
  }

  function applyPercentage(percentage: (typeof PERCENT_OPTIONS)[number]) {
    if (!quickData || submitting || unknownOutcome) return;
    setError("");
    if (orderSide === "SELL") {
      const portion = multiplyByRatio(quickData.baseAvailable, percentage);
      setQuantity(
        portion ? quantizeDown(portion, quickData.stepSize) || "" : "",
      );
      return;
    }

    const quotePortion = multiplyByRatio(
      quickData.quoteAvailable,
      percentage,
    );
    if (!quotePortion) return;
    if (orderType === "MARKET") {
      setQuoteAmount(quantizeDown(quotePortion, QUOTE_STEP) || "");
      return;
    }
    const usablePrice = isPositiveDecimal(limitPrice)
      ? quantizeDown(limitPrice, quickData.tickSize)
      : quickData.price;
    if (!usablePrice || !isPositiveDecimal(usablePrice)) return;
    setQuantity(
      divideAndQuantize(
        quotePortion,
        usablePrice,
        quickData.stepSize,
      ) || "",
    );
  }

  function prepareOrder(): PreparedOrder | null {
    if (!quickData) {
      setError("İşlem bilgileri henüz hazır değil.");
      return null;
    }

    const price =
      orderType === "LIMIT"
        ? quantizeDown(limitPrice, quickData.tickSize)
        : quickData.price;
    if (!price || !isPositiveDecimal(price)) {
      setError("Geçerli bir fiyat girin.");
      return null;
    }

    let normalizedQuantity: string;
    let notional: string;
    const payload: OrderPayload = {
      account_id: accountId,
      symbol: quickData.symbol,
      side: orderSide,
      type: orderType,
    };

    if (orderType === "MARKET" && orderSide === "BUY") {
      const normalizedQuote = quantizeDown(quoteAmount, QUOTE_STEP);
      if (!normalizedQuote || !isPositiveDecimal(normalizedQuote)) {
        setError(`Geçerli bir ${quickData.quoteAsset} tutarı girin.`);
        return null;
      }
      normalizedQuantity =
        divideAndQuantize(
          normalizedQuote,
          quickData.price,
          quickData.stepSize,
        ) || "0";
      notional = normalizedQuote;
      payload.quote_order_qty = Number(normalizedQuote);
      setQuoteAmount(normalizedQuote);
    } else {
      normalizedQuantity =
        quantizeDown(quantity, quickData.stepSize) || "0";
      if (!isPositiveDecimal(normalizedQuantity)) {
        setError(`Geçerli bir ${quickData.baseAsset} miktarı girin.`);
        return null;
      }
      notional =
        multiplyDecimal(normalizedQuantity, price) || "0";
      payload.quantity = Number(normalizedQuantity);
      setQuantity(normalizedQuantity);
      if (orderType === "LIMIT") {
        payload.price = Number(price);
        setLimitPrice(price);
      }
    }

    if (compareDecimal(normalizedQuantity, quickData.minQty) === -1) {
      setError(
        `Minimum miktar ${formatAmount(quickData.minQty)} ${quickData.baseAsset}.`,
      );
      return null;
    }
    if (compareDecimal(notional, quickData.minNotional) === -1) {
      setError(
        `Minimum emir tutarı ${formatAmount(quickData.minNotional)} ${quickData.quoteAsset}.`,
      );
      return null;
    }
    if (
      orderSide === "BUY" &&
      compareDecimal(notional, quickData.quoteAvailable) === 1
    ) {
      setError(
        `Kullanılabilir ${quickData.quoteAsset} bakiyesi bu emir için yetersiz.`,
      );
      return null;
    }
    if (
      orderSide === "SELL" &&
      compareDecimal(normalizedQuantity, quickData.baseAvailable) === 1
    ) {
      setError(
        `Kullanılabilir ${quickData.baseAsset} bakiyesi bu emir için yetersiz.`,
      );
      return null;
    }

    return {
      payload,
      quantity: normalizedQuantity,
      notional,
      price,
    };
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitGuardRef.current || unknownOutcome) return;
    setError("");
    const prepared = prepareOrder();
    if (!prepared) return;

    const fingerprint = JSON.stringify(prepared.payload);
    if (activeOrderFingerprints.has(fingerprint)) {
      setError("Aynı emir zaten gönderiliyor.");
      return;
    }

    submitGuardRef.current = true;
    submittingRef.current = true;
    activeOrderFingerprints.add(fingerprint);
    setSubmitting(true);
    try {
      const response = await apiRequest<SpotOrderResult>("/api/spot/order", {
        method: "POST",
        body: fingerprint,
        timeoutMs: 20_000,
      });
      if (!response || response.success !== true) {
        throw new ApiError("Emir sonucu doğrulanamadı.", {
          kind: "unknown",
          details: response,
        });
      }
      try {
        void Promise.resolve(onSuccess(response)).catch(() => undefined);
      } finally {
        onClose();
      }
    } catch (submitError) {
      if (isUnknownMutationOutcome(submitError)) {
        setUnknownOutcome(true);
        setError("");
      } else {
        setError(apiErrorMessage(submitError));
      }
    } finally {
      activeOrderFingerprints.delete(fingerprint);
      submitGuardRef.current = false;
      submittingRef.current = false;
      setSubmitting(false);
    }
  }

  const isBuy = orderSide === "BUY";
  const inputDisabled = loading || !quickData || submitting || unknownOutcome;
  const amountToSpend = isBuy ? estimatedNotional : estimatedQuantity;
  const spendAsset = isBuy ? quickData?.quoteAsset : quickData?.baseAsset;
  const amountToReceive = isBuy ? estimatedQuantity : estimatedNotional;
  const receiveAsset = isBuy ? quickData?.baseAsset : quickData?.quoteAsset;
  const submitLabel = submitting
    ? "Emir gönderiliyor"
    : `${quickData?.baseAsset || normalizedSymbol} ${isBuy ? "Al" : "Sat"}`;

  return (
    <div
      className="fixed inset-x-0 bottom-0 top-[env(safe-area-inset-top)] z-50 flex items-end justify-center bg-black/80 pb-[env(safe-area-inset-bottom)] backdrop-blur-md sm:inset-0 sm:items-center sm:p-4"
      onMouseDown={(event) => {
        if (
          event.currentTarget === event.target &&
          !submittingRef.current
        ) {
          onClose();
        }
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        tabIndex={-1}
        className="max-h-full w-full overflow-y-auto overscroll-contain rounded-t-[1.75rem] border border-white/10 bg-[#17191f] text-neutral-100 shadow-[0_28px_100px_rgba(0,0,0,.65)] sm:max-h-[min(92dvh,860px)] sm:max-w-2xl sm:rounded-[1.75rem]"
      >
        <header className="sticky top-0 z-20 flex items-start justify-between gap-4 border-b border-white/8 bg-[#17191f]/95 px-4 py-3.5 backdrop-blur-xl sm:px-6 sm:py-4">
          <div className="flex min-w-0 items-center gap-3">
            <CoinLogo symbol={normalizedSymbol} size={46} eager />
            <div className="min-w-0">
            <p className="mb-1 text-[10px] font-black uppercase tracking-[0.18em] text-fuchsia-200">
              Binance Spot
            </p>
            <h2 id={titleId} className="text-lg font-black text-white sm:text-xl">
              {splitTradingSymbol(normalizedSymbol).label}
            </h2>
            <p id={descriptionId} className="mt-0.5 text-[11px] text-neutral-500 sm:text-xs">
              {isBuy ? "Alış emri oluştur" : "Satış emri oluştur"} · kullanılabilir bakiye korunur
            </p>
            </div>
          </div>
          <button
            ref={closeButtonRef}
            type="button"
            onClick={onClose}
            disabled={submitting}
            aria-label="Emir penceresini kapat"
            className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-neutral-700 bg-neutral-900 text-neutral-300 transition hover:border-neutral-500 hover:text-white focus:outline-none focus:ring-2 focus:ring-[#f0b90b] disabled:cursor-not-allowed disabled:opacity-40"
          >
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        </header>

        <form className="space-y-4 p-4 pb-5 sm:space-y-5 sm:p-6" onSubmit={handleSubmit}>
          {loading && (
            <div
              role="status"
              className="flex min-h-32 items-center justify-center gap-3 rounded-2xl border border-neutral-800 bg-neutral-900/60 text-sm text-neutral-300"
            >
              <LoaderCircle
                className="h-5 w-5 animate-spin text-[#f0b90b]"
                aria-hidden="true"
              />
              Canlı fiyat ve işlem kuralları alınıyor…
            </div>
          )}

          {!loading && loadError && (
            <div
              role="alert"
              className="rounded-2xl border border-red-400/25 bg-red-400/10 p-4"
            >
              <div className="flex gap-3">
                <AlertTriangle
                  className="mt-0.5 h-5 w-5 shrink-0 text-red-300"
                  aria-hidden="true"
                />
                <div>
                  <p className="font-bold text-red-100">
                    İşlem ekranı hazırlanamadı
                  </p>
                  <p className="mt-1 text-sm leading-6 text-red-200/80">
                    {loadError}
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setLoadAttempt((attempt) => attempt + 1)}
                className="mt-4 inline-flex min-h-10 items-center gap-2 rounded-xl border border-red-300/25 bg-red-300/10 px-4 text-sm font-bold text-red-100 transition hover:bg-red-300/15 focus:outline-none focus:ring-2 focus:ring-red-300"
              >
                <RefreshCw className="h-4 w-4" aria-hidden="true" />
                Yeniden yükle
              </button>
            </div>
          )}

          {quickData && !loading && (
            <>
              <section
                aria-label="Piyasa ve bakiye özeti"
                className="grid grid-cols-2 gap-2.5 rounded-2xl border border-fuchsia-300/10 bg-[radial-gradient(circle_at_top_left,rgba(217,70,239,.08),transparent_52%),rgba(9,10,14,.5)] p-3.5 sm:grid-cols-3 sm:p-4"
              >
                <div className="col-span-2 rounded-xl border border-white/7 bg-white/[0.025] p-3 sm:col-span-1">
                  <p className="text-[11px] font-bold uppercase tracking-wider text-neutral-500">
                    Canlı fiyat
                  </p>
                  <p className="mt-1 font-mono text-base font-bold text-white">
                    <LiveValue value={quickData.price}>
                      {formatAmount(quickData.price)} {quickData.quoteAsset}
                    </LiveValue>
                  </p>
                  <p
                    className={`mt-0.5 text-xs font-bold ${
                      quickData.priceChange24h >= 0
                        ? "text-[#0ecb81]"
                        : "text-[#f6465d]"
                    }`}
                  >
                    <LiveValue value={quickData.priceChange24h} toneBySign>
                      {quickData.priceChange24h >= 0 ? "+" : ""}
                      {quickData.priceChange24h.toLocaleString("tr-TR", {
                        maximumFractionDigits: 2,
                      })}
                      % / 24s
                    </LiveValue>
                  </p>
                </div>
                <div className="rounded-xl border border-white/7 bg-white/[0.025] p-3">
                  <p className="text-[11px] font-bold uppercase tracking-wider text-neutral-500">
                    {quickData.quoteAsset} bakiyesi
                  </p>
                  <p className="mt-1 break-all font-mono text-sm font-bold text-white">
                    {formatAmount(quickData.quoteAvailable)} {quickData.quoteAsset}
                  </p>
                </div>
                <div className="rounded-xl border border-white/7 bg-white/[0.025] p-3">
                  <p className="text-[11px] font-bold uppercase tracking-wider text-neutral-500">
                    {quickData.baseAsset} bakiyesi
                  </p>
                  <p className="mt-1 break-all font-mono text-sm font-bold text-white">
                    {formatAmount(quickData.baseAvailable)} {quickData.baseAsset}
                  </p>
                </div>
              </section>

              <fieldset>
                <legend className="sr-only">İşlem yönü</legend>
                <div className="grid grid-cols-2 rounded-xl bg-neutral-900 p-1">
                  {(["BUY", "SELL"] as const).map((value) => (
                    <button
                      key={value}
                      type="button"
                      aria-pressed={orderSide === value}
                      onClick={() => selectSide(value)}
                      disabled={submitting || unknownOutcome}
                      className={`min-h-11 rounded-lg text-sm font-black transition focus:outline-none focus:ring-2 focus:ring-inset focus:ring-white/80 disabled:cursor-not-allowed disabled:opacity-50 ${
                        orderSide === value
                          ? value === "BUY"
                            ? "bg-[#0ecb81] text-[#07150f]"
                            : "bg-[#f6465d] text-white"
                          : "text-neutral-400 hover:text-white"
                      }`}
                    >
                      {value === "BUY" ? "Al" : "Sat"}
                    </button>
                  ))}
                </div>
              </fieldset>

              <fieldset>
                <legend className="sr-only">Emir türü</legend>
                <div className="flex gap-2">
                  {(["MARKET", "LIMIT"] as const).map((value) => (
                    <button
                      key={value}
                      type="button"
                      aria-pressed={orderType === value}
                      onClick={() => selectType(value)}
                      disabled={submitting || unknownOutcome}
                      className={`min-h-10 flex-1 rounded-xl border px-4 text-sm font-bold transition focus:outline-none focus:ring-2 focus:ring-[#f0b90b] disabled:cursor-not-allowed disabled:opacity-50 ${
                        orderType === value
                          ? "border-[#f0b90b]/50 bg-[#f0b90b]/10 text-[#f0b90b]"
                          : "border-neutral-800 bg-neutral-900/60 text-neutral-400 hover:border-neutral-700 hover:text-white"
                      }`}
                    >
                      {value === "MARKET" ? "Piyasa" : "Limit"}
                    </button>
                  ))}
                </div>
              </fieldset>

              {orderType === "LIMIT" && (
                <div>
                  <label
                    htmlFor={`${priceHelpId}-input`}
                    className="mb-2 block text-sm font-bold text-neutral-200"
                  >
                    Limit fiyat
                  </label>
                  <div className="relative">
                    <input
                      id={`${priceHelpId}-input`}
                      value={limitPrice}
                      onChange={(event) =>
                        setLimitPrice(cleanDecimalInput(event.target.value))
                      }
                      onBlur={() => {
                        const normalized = quantizeDown(
                          limitPrice,
                          quickData.tickSize,
                        );
                        if (normalized) setLimitPrice(normalized);
                      }}
                      disabled={inputDisabled}
                      inputMode="decimal"
                      maxLength={64}
                      autoComplete="off"
                      spellCheck={false}
                      aria-describedby={priceHelpId}
                      className="h-12 w-full rounded-xl border border-neutral-700 bg-[#101116] px-4 pr-20 font-mono text-base font-bold text-white outline-none transition placeholder:text-neutral-600 focus:border-[#f0b90b] focus:ring-2 focus:ring-[#f0b90b]/20 disabled:cursor-not-allowed disabled:opacity-50"
                    />
                    <span className="pointer-events-none absolute inset-y-0 right-4 flex items-center text-xs font-bold text-neutral-500">
                      {quickData.quoteAsset}
                    </span>
                  </div>
                  <p id={priceHelpId} className="mt-1.5 text-xs text-neutral-500">
                    Fiyat adımı: {quickData.tickSize}
                  </p>
                </div>
              )}

              <div>
                <label
                  htmlFor={`${quantityHelpId}-input`}
                  className="mb-2 block text-sm font-bold text-neutral-200"
                >
                  {orderType === "MARKET" && isBuy
                    ? `Ödeyeceğin tutar (${quickData.quoteAsset})`
                    : isBuy
                      ? `Almak istediğin miktar (${quickData.baseAsset})`
                      : `Satmak istediğin miktar (${quickData.baseAsset})`}
                </label>
                <div className="relative">
                  <input
                    id={`${quantityHelpId}-input`}
                    value={
                      orderType === "MARKET" && isBuy
                        ? quoteAmount
                        : quantity
                    }
                    onChange={(event) => {
                      const value = cleanDecimalInput(event.target.value);
                      setError("");
                      if (orderType === "MARKET" && isBuy) {
                        setQuoteAmount(value);
                      } else {
                        setQuantity(value);
                      }
                    }}
                    onBlur={() => {
                      if (orderType === "MARKET" && isBuy) {
                        const normalized = quantizeDown(
                          quoteAmount,
                          QUOTE_STEP,
                        );
                        if (normalized) setQuoteAmount(normalized);
                      } else {
                        const normalized = quantizeDown(
                          quantity,
                          quickData.stepSize,
                        );
                        if (normalized) setQuantity(normalized);
                      }
                    }}
                    disabled={inputDisabled}
                    inputMode="decimal"
                    maxLength={64}
                    autoComplete="off"
                    spellCheck={false}
                    aria-invalid={Boolean(error)}
                    aria-describedby={`${quantityHelpId}${
                      error ? ` ${errorId}` : ""
                    }`}
                    className="h-12 w-full rounded-xl border border-neutral-700 bg-[#101116] px-4 pr-20 font-mono text-base font-bold text-white outline-none transition placeholder:text-neutral-600 focus:border-[#f0b90b] focus:ring-2 focus:ring-[#f0b90b]/20 disabled:cursor-not-allowed disabled:opacity-50"
                    placeholder="0"
                  />
                  <span className="pointer-events-none absolute inset-y-0 right-4 flex items-center text-xs font-bold text-neutral-500">
                    {orderType === "MARKET" && isBuy
                      ? quickData.quoteAsset
                      : quickData.baseAsset}
                  </span>
                </div>
                <p id={quantityHelpId} className="mt-1.5 text-xs text-neutral-500">
                  {orderType === "MARKET" && isBuy
                    ? `Tahmini miktar: ${formatAmount(estimatedQuantity)} ${quickData.baseAsset}`
                    : `Miktar adımı: ${quickData.stepSize} · Minimum: ${quickData.minQty}`}
                </p>
              </div>

              <div
                className="grid grid-cols-4 gap-2"
                aria-label="Kullanılabilir bakiyenin yüzdesi"
              >
                {PERCENT_OPTIONS.map((percentage) => (
                  <button
                    key={percentage}
                    type="button"
                    onClick={() => applyPercentage(percentage)}
                    disabled={inputDisabled}
                    className="min-h-10 rounded-xl border border-neutral-800 bg-neutral-900/70 text-xs font-black text-neutral-300 transition hover:border-[#f0b90b]/50 hover:text-[#f0b90b] focus:outline-none focus:ring-2 focus:ring-[#f0b90b] disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    %{percentage}
                  </button>
                ))}
              </div>

              <section aria-label="Emir özeti" className="overflow-hidden rounded-2xl border border-white/8 bg-[#101116]">
                <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-2 p-4">
                  <div className="min-w-0">
                    <p className="text-[10px] font-black uppercase tracking-wider text-neutral-600">
                      {isBuy ? "Ödeyeceğin" : "Satacağın"}
                    </p>
                    <p className="mt-1 break-all font-mono text-sm font-black text-white">
                      {formatAmount(amountToSpend)} {spendAsset}
                    </p>
                  </div>
                  <span className="grid h-8 w-8 place-items-center rounded-full border border-fuchsia-300/15 bg-fuchsia-300/[0.06] text-sm text-fuchsia-200">→</span>
                  <div className="min-w-0 text-right">
                    <p className="text-[10px] font-black uppercase tracking-wider text-neutral-600">
                      Tahmini alacağın
                    </p>
                    <p className="mt-1 break-all font-mono text-sm font-black text-emerald-300">
                      {formatAmount(amountToReceive)} {receiveAsset}
                    </p>
                  </div>
                </div>
                <dl className="grid grid-cols-2 gap-px border-t border-white/7 bg-white/7 text-xs">
                  <div className="bg-[#15161c] p-3">
                    <dt className="text-neutral-600">Emir türü</dt>
                    <dd className="mt-1 font-bold text-neutral-200">{orderType === "MARKET" ? "Piyasa · anlık" : "Limit · belirlediğin fiyat"}</dd>
                  </div>
                  <div className="bg-[#15161c] p-3 text-right">
                    <dt className="text-neutral-600">Minimum emir</dt>
                    <dd className="mt-1 font-mono font-bold text-neutral-200">{formatAmount(quickData.minNotional)} {quickData.quoteAsset}</dd>
                  </div>
                </dl>
              </section>
            </>
          )}

          {error && (
            <div
              id={errorId}
              role="alert"
              className="flex gap-3 rounded-2xl border border-red-400/25 bg-red-400/10 p-4 text-sm leading-6 text-red-100"
            >
              <AlertTriangle
                className="mt-0.5 h-5 w-5 shrink-0 text-red-300"
                aria-hidden="true"
              />
              <span>{error}</span>
            </div>
          )}

          {unknownOutcome && (
            <div
              role="alert"
              className="rounded-2xl border border-amber-300/35 bg-amber-300/10 p-4 text-amber-50"
            >
              <div className="flex gap-3">
                <AlertTriangle
                  className="mt-0.5 h-5 w-5 shrink-0 text-amber-300"
                  aria-hidden="true"
                />
                <div>
                  <p className="font-black">Emir sonucu belirsiz</p>
                  <p className="mt-1 text-sm leading-6 text-amber-100/80">
                    Sunucu emri almış olabilir ancak yanıt doğrulanamadı. Aynı
                    emri yeniden göndermeyin; açık emirleri ve işlem geçmişini
                    kontrol edin.
                  </p>
                </div>
              </div>
            </div>
          )}

          {quickData && !unknownOutcome && (
            <div className="flex gap-2 rounded-xl border border-sky-300/15 bg-sky-300/5 p-3 text-xs leading-5 text-sky-100/70">
              <Info
                className="mt-0.5 h-4 w-4 shrink-0 text-sky-300"
                aria-hidden="true"
              />
              Piyasa emirlerinde gerçekleşen fiyat ve miktar, hızlı piyasa
              hareketlerinde tahminden farklı olabilir. Botlarda kullanılan
              kilitli bakiyeniz burada gösterilmez.
            </div>
          )}

          <div className="sticky bottom-0 z-10 -mx-4 flex flex-col-reverse gap-2 border-t border-white/8 bg-[#17191f]/95 px-4 pb-[max(env(safe-area-inset-bottom),0.25rem)] pt-3 backdrop-blur-xl sm:static sm:mx-0 sm:flex-row sm:border-0 sm:bg-transparent sm:p-0 sm:pt-1 sm:backdrop-blur-none">
            <button
              type="button"
              onClick={onClose}
              disabled={submitting}
              className="min-h-12 flex-1 rounded-xl border border-neutral-700 bg-neutral-900 px-4 text-sm font-bold text-neutral-200 transition hover:border-neutral-500 hover:text-white focus:outline-none focus:ring-2 focus:ring-neutral-400 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {unknownOutcome ? "Kapat ve kontrol et" : "Vazgeç"}
            </button>
            {!unknownOutcome && (
              <button
                type="submit"
                disabled={inputDisabled}
                className={`min-h-12 flex-[1.4] rounded-xl px-5 text-sm font-black transition focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-offset-[#17191f] disabled:cursor-not-allowed disabled:opacity-45 ${
                  isBuy
                    ? "bg-[#0ecb81] text-[#061a11] hover:bg-[#13d88d] focus:ring-[#0ecb81]"
                    : "bg-[#f6465d] text-white hover:bg-[#ff5369] focus:ring-[#f6465d]"
                }`}
              >
                <span className="inline-flex items-center justify-center gap-2">
                  {submitting && (
                    <LoaderCircle
                      className="h-4 w-4 animate-spin"
                      aria-hidden="true"
                    />
                  )}
                  {submitLabel}
                </span>
              </button>
            )}
          </div>
        </form>
      </div>
    </div>
  );
}
