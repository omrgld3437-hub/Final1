import {
  Activity,
  ArrowLeft,
  ArrowRight,
  BarChart3,
  Bot,
  Check,
  ChevronDown,
  ChevronUp,
  CircleDollarSign,
  Gauge,
  LoaderCircle,
  Rocket,
  Sparkles,
  X,
} from "lucide-react";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from "react";
import CoinLogo, {
  splitTradingSymbol,
} from "../../components/coin/CoinLogo";
import ParamAssistantPanel, {
  type AssistantConfig,
  type AssistantResult,
} from "../assistant/ParamAssistantPanel";
import { apiFetch } from "../../lib/api";

export interface GridDraft {
  trigger_pct: number;
  qty_pct: number;
}

export interface NewBotForm {
  symbol: string;
  budget_usd: number;
  dynamic_mode: boolean;
  base_pct: number;
  quote_pct: number;
  upTrail: number;
  upGrids: GridDraft[];
  downTrail: number;
  downGrids: GridDraft[];
  maxBuyLevels: number;
  rebuyTrigger: number;
  rebuyTrail: number;
  resellTrigger: number;
  resellTrail: number;
}

interface BotCreateStudioProps {
  form: NewBotForm;
  step: number;
  availableUSDT: number;
  error: string;
  errorKey?: number;
  isCreating: boolean;
  disabled: boolean;
  assistantApplied: boolean;
  assistantResult?: AssistantResult | null;
  onClose: () => void;
  onChange: (patch: Partial<NewBotForm>) => void;
  onGridChange: (
    side: "up" | "down",
    index: number,
    patch: Partial<GridDraft>,
  ) => void;
  onGridCountChange: (side: "up" | "down", count: number) => void;
  onAssistantApply: (
    config: AssistantConfig,
    result: AssistantResult,
  ) => void;
  onPrevious: () => void;
  onNext: () => void;
  onSubmit: () => void;
}

const STEPS = [
  { id: 1, short: "Piyasa", title: "Piyasa ve sermaye", icon: CircleDollarSign },
  { id: 2, short: "Dağılım", title: "Başlangıç dağılımı", icon: BarChart3 },
  { id: 3, short: "Satış", title: "Yukarı yön planı", icon: ChevronUp },
  { id: 4, short: "Alış", title: "Aşağı yön planı", icon: ChevronDown },
  { id: 5, short: "Kâr döngüsü", title: "Kâr döngüsü ve kontrol", icon: Gauge },
];

const fieldClass =
  "h-12 w-full rounded-xl border border-white/10 bg-black/20 px-3.5 text-sm font-bold text-white outline-none transition placeholder:text-neutral-600 hover:border-white/15 focus:border-fuchsia-300/40 focus:ring-4 focus:ring-fuchsia-300/5";

interface CoinListResponse {
  coins?: unknown[];
  symbols?: unknown[];
}

const FALLBACK_COIN_PAIRS = [
  "BTCUSDT",
  "ETHUSDT",
  "BNBUSDT",
  "SOLUSDT",
  "XRPUSDT",
  "ADAUSDT",
  "DOGEUSDT",
  "AVAXUSDT",
  "LINKUSDT",
  "DOTUSDT",
];

function normalizePairSymbol(value: unknown): string {
  return String(value ?? "")
    .trim()
    .toUpperCase()
    .replace(/[^A-Z0-9]/g, "");
}

function coinListSymbol(value: unknown): string {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return normalizePairSymbol((value as Record<string, unknown>).symbol);
  }
  return normalizePairSymbol(value);
}

function money(value: number): string {
  return new Intl.NumberFormat("tr-TR", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(Number.isFinite(value) ? value : 0);
}

function clampGridCount(value: number): number {
  return Math.min(20, Math.max(1, Math.round(value || 1)));
}

export default function BotCreateStudio({
  form,
  step,
  availableUSDT,
  error,
  errorKey = 0,
  isCreating,
  disabled,
  assistantApplied,
  assistantResult,
  onClose,
  onChange,
  onGridChange,
  onGridCountChange,
  onAssistantApply,
  onPrevious,
  onNext,
  onSubmit,
}: BotCreateStudioProps) {
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const errorRef = useRef<HTMLDivElement>(null);
  const scrollAreaRef = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);
  const isCreatingRef = useRef(isCreating);
  const pair = splitTradingSymbol(form.symbol);
  const allocationTotal = form.base_pct + form.quote_pct;
  const activeStep = STEPS[step - 1] || STEPS[0];
  const displayError = (() => {
    const raw = String(error || "").trim();
    if (!raw) return "";
    const marker = "Bot sermayesi kullanılabilir bakiyeyi aşıyor.";
    if (raw.includes(marker)) {
      const availableMatch = raw.match(/Kullanılabilir:\s*\$[^.]+\./);
      return availableMatch
        ? `${marker} ${availableMatch[0]}`.replace(/\s+/g, " ").trim()
        : marker;
    }
    return raw;
  })();

  useEffect(() => {
    onCloseRef.current = onClose;
    isCreatingRef.current = isCreating;
  }, [isCreating, onClose]);

  useEffect(() => {
    if (!displayError) return;
    const node = errorRef.current;
    const area = scrollAreaRef.current;
    if (!node) return;
    const frame = window.requestAnimationFrame(() => {
      if (area) {
        const top = Math.max(0, node.offsetTop - 12);
        area.scrollTo({ top, behavior: "smooth" });
      }
      node.scrollIntoView({ behavior: "smooth", block: "center" });
      try {
        node.focus({ preventScroll: true });
      } catch {
        node.focus();
      }
    });
    return () => window.cancelAnimationFrame(frame);
  }, [displayError, step, errorKey]);

  useEffect(() => {
    const originalOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeButtonRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !isCreatingRef.current) {
        onCloseRef.current();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = originalOverflow;
      window.removeEventListener("keydown", onKeyDown);
    };
  }, []);

  return (
    <div
      className="fixed inset-x-0 bottom-0 top-[env(safe-area-inset-top)] z-50 grid place-items-center bg-[#07070a]/88 p-2 backdrop-blur-md sm:inset-0 sm:p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="bot-studio-title"
    >
      <section className="relative flex h-full w-full max-w-6xl flex-col overflow-hidden rounded-[1.75rem] border border-fuchsia-300/15 bg-[#15161c] shadow-[0_40px_140px_rgba(0,0,0,.65)] sm:h-[min(860px,calc(100dvh-2rem))]">
        <header className="relative shrink-0 overflow-hidden border-b border-white/8 px-4 py-4 sm:px-6 sm:py-5">
          <div className="pointer-events-none absolute -right-24 -top-28 h-72 w-72 rounded-full bg-fuchsia-400/10 blur-3xl" />
          <div className="relative flex items-center justify-between gap-4">
            <div className="flex min-w-0 items-center gap-3">
              <span className="grid h-11 w-11 shrink-0 place-items-center rounded-2xl border border-fuchsia-200/15 bg-fuchsia-200/8 text-fuchsia-100">
                <Bot className="h-5 w-5" />
              </span>
              <div className="min-w-0">
                <h2
                  id="bot-studio-title"
                  className="truncate text-lg font-black tracking-tight text-white sm:text-xl"
                >
                  Bot stüdyosu
                </h2>
              </div>
            </div>
            <button
              ref={closeButtonRef}
              type="button"
              onClick={onClose}
              disabled={isCreating}
              aria-label="Bot oluşturucuyu kapat"
              className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-white/8 bg-white/[0.035] text-neutral-400 transition hover:bg-white/[0.07] hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          <nav className="relative mt-4 grid grid-cols-5 gap-1.5" aria-label="Bot oluşturma adımları">
            {STEPS.map((item) => {
              const Icon = item.icon;
              const complete = item.id < step;
              const current = item.id === step;
              return (
                <div
                  key={item.id}
                  aria-current={current ? "step" : undefined}
                  className={`rounded-xl border px-2 py-2 transition sm:px-3 ${
                    current
                      ? "border-fuchsia-300/30 bg-fuchsia-300/10 text-fuchsia-100"
                      : complete
                        ? "border-emerald-300/15 bg-emerald-300/5 text-emerald-200"
                        : "border-white/6 bg-white/[0.02] text-neutral-600"
                  }`}
                >
                  <div className="flex items-center gap-2">
                    {complete ? (
                      <Check className="h-3.5 w-3.5 shrink-0" />
                    ) : (
                      <Icon className="h-3.5 w-3.5 shrink-0" />
                    )}
                    <span className="hidden truncate text-[11px] font-black sm:block">
                      {item.short}
                    </span>
                    <span className="text-[10px] font-black sm:hidden">{item.id}</span>
                  </div>
                  <div
                    className={`mt-2 h-0.5 rounded-full ${
                      current || complete ? "bg-current" : "bg-white/6"
                    }`}
                  />
                </div>
              );
            })}
          </nav>
        </header>

        <div ref={scrollAreaRef} className="min-h-0 flex-1 overflow-y-auto">
          <div className="p-4 sm:p-6">
            <main className="min-w-0">
              <div className="mb-5">
                <p className="text-[10px] font-black uppercase tracking-[0.18em] text-neutral-500">
                  Adım {step} / {STEPS.length}
                </p>
                <h3 className="mt-1 text-2xl font-black tracking-[-0.025em] text-white">
                  {activeStep.title}
                </h3>
              </div>

              {displayError && (
                <div
                  ref={errorRef}
                  role="alert"
                  tabIndex={-1}
                  className="mb-5 scroll-mt-4 rounded-2xl border border-red-400/25 bg-red-400/[0.1] px-4 py-3 text-sm font-semibold leading-6 text-red-100 outline-none"
                >
                  {displayError}
                </div>
              )}

              {assistantApplied && step > 1 && (
                <section className="mb-5 rounded-2xl border border-fuchsia-300/15 bg-fuchsia-300/[0.055] p-4">
                  <p className="flex items-center gap-2 text-xs font-black text-fuchsia-100">
                    <Sparkles className="h-4 w-4" />
                    Parametre Asistanı bu forma uygulandı
                  </p>
                  <p className="mt-1 text-[11px] leading-5 text-neutral-500">
                    {assistantResult?.display_regime_label ||
                      assistantResult?.market_status_plain ||
                      "Piyasa rejimi değerlendirildi"}
                    {" · "}
                    Aşağıdaki tüm grid ve trailing değerleri düzenlenebilir.
                  </p>
                </section>
              )}

              {step === 1 && (
                <div className="space-y-5">
                  <section className="grid gap-4 rounded-2xl border border-white/8 bg-white/[0.025] p-4 sm:grid-cols-2 sm:p-5">
                    <Field
                      label="İşlem çifti"
                    >
                      <CoinPairAutocomplete
                        value={form.symbol}
                        onChange={(symbol) => onChange({ symbol })}
                      />
                    </Field>
                    <Field
                      label="Bot sermayesi"
                      hint={`Kullanılabilir: ${money(availableUSDT)}`}
                    >
                      <div className="relative">
                        <NumericInput
                          value={form.budget_usd}
                          onChange={(value) => onChange({ budget_usd: value })}
                          inputMode="decimal"
                          placeholder="0"
                          className={`${fieldClass} bot-number-input pr-16`}
                        />
                        <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[10px] font-black text-neutral-500">
                          USDT
                        </span>
                      </div>
                    </Field>
                  </section>
                  <DynamicModeControl
                    enabled={form.dynamic_mode}
                    onChange={(enabled) =>
                      onChange({ dynamic_mode: enabled })
                    }
                  />
                  <ParamAssistantPanel
                    symbol={form.symbol}
                    budget={form.budget_usd}
                    onApply={onAssistantApply}
                  />
                </div>
              )}

              {step === 2 && (
                <section className="space-y-5 rounded-2xl border border-white/8 bg-white/[0.025] p-4 sm:p-5">
                  <div className="grid gap-4 sm:grid-cols-2">
                    <Field
                      label={`${pair.base} başlangıç payı`}
                      hint="İlk coin yatırımı için ayrılan bölüm"
                    >
                      <PercentInput
                        value={form.base_pct}
                        onChange={(value) =>
                          onChange({
                            base_pct: value,
                            quote_pct: Math.max(0, 100 - value),
                          })
                        }
                      />
                    </Field>
                    <Field
                      label={`${pair.quote} base dağılımı`}
                      hint="Düşüşlerde alış için korunan bölüm"
                    >
                      <PercentInput
                        value={form.quote_pct}
                        onChange={(value) =>
                          onChange({
                            quote_pct: value,
                            base_pct: Math.max(0, 100 - value),
                          })
                        }
                      />
                    </Field>
                  </div>
                  <div className="rounded-2xl border border-white/8 bg-black/15 p-4">
                    <div className="flex items-center justify-between text-xs">
                      <span className="font-bold text-neutral-400">Dağılım haritası</span>
                      <span
                        className={`font-black ${
                          Math.abs(allocationTotal - 100) <= 0.5
                            ? "text-emerald-300"
                            : "text-red-300"
                        }`}
                      >
                        Toplam %{allocationTotal.toFixed(1)}
                      </span>
                    </div>
                    <div className="mt-3 flex h-4 overflow-hidden rounded-full bg-white/5">
                      <div
                        className="bg-gradient-to-r from-fuchsia-400 to-violet-400 transition-all"
                        style={{ width: `${Math.min(100, Math.max(0, form.base_pct))}%` }}
                      />
                      <div className="flex-1 bg-gradient-to-r from-sky-400 to-cyan-300" />
                    </div>
                    <div className="mt-3 flex gap-2 text-xs">
                      <AllocationAmount
                        label={pair.base}
                        value={money(form.budget_usd * form.base_pct / 100)}
                        percent={form.base_pct}
                        tone="violet"
                      />
                      <AllocationAmount
                        label={pair.quote}
                        value={money(form.budget_usd * form.quote_pct / 100)}
                        percent={form.quote_pct}
                        tone="sky"
                        alignRight
                      />
                    </div>
                  </div>
                </section>
              )}

              {step === 3 && (
                <GridEditor
                  side="up"
                  title="Kademeli satış planı"
                  description="Fiyat yükseldikçe tetiklenecek satış grid seviyelerini ve her seviyede satılacak coin payını belirle."
                  grids={form.upGrids}
                  trail={form.upTrail}
                  onTrailChange={(value) => onChange({ upTrail: value })}
                  onCountChange={(count) => onGridCountChange("up", count)}
                  onGridChange={(index, patch) => onGridChange("up", index, patch)}
                />
              )}

              {step === 4 && (
                <div className="space-y-4">
                  <GridEditor
                    side="down"
                    title="Kademeli alış planı"
                    description="Fiyat düştükçe tetiklenecek alış grid seviyelerini ve her seviyede alınacak coin payını belirle."
                    grids={form.downGrids}
                    trail={form.downTrail}
                    onTrailChange={(value) => onChange({ downTrail: value })}
                    onCountChange={(count) => onGridCountChange("down", count)}
                    onGridChange={(index, patch) => onGridChange("down", index, patch)}
                  />
                </div>
              )}

              {step === 5 && (
                <div className="space-y-4">
                  <section className="grid gap-4 rounded-2xl border border-white/8 bg-white/[0.025] p-4 sm:grid-cols-2 sm:p-5">
                    <Field
                      label="Kâr alışı tetiği"
                      hint="Gridlerin satış ortalamasının yüzde kaç altına düştüğünde kâr alışı tetiklensin?"
                    >
                      <PercentInput
                        value={form.rebuyTrigger}
                        onChange={(value) => onChange({ rebuyTrigger: value })}
                      />
                    </Field>
                    <Field
                      label="Kâr alışı trailing"
                      hint="Kâr alışı tetiklendikten sonra dipten yüzde kaç yükselince alış tamamlansın?"
                    >
                      <PercentInput
                        value={form.rebuyTrail}
                        onChange={(value) => onChange({ rebuyTrail: value })}
                      />
                    </Field>
                    <Field
                      label="Kâr satışı tetiği"
                      hint="Gridlerin alış ortalamasının yüzde kaç üstüne çıktığında kâr satışı tetiklensin?"
                    >
                      <PercentInput
                        value={form.resellTrigger}
                        onChange={(value) => onChange({ resellTrigger: value })}
                      />
                    </Field>
                    <Field
                      label="Kâr satışı trailing"
                      hint="Kâr satışı tetiklendikten sonra tepeden yüzde kaç düşünce satış tamamlansın?"
                    >
                      <PercentInput
                        value={form.resellTrail}
                        onChange={(value) => onChange({ resellTrail: value })}
                      />
                    </Field>
                  </section>
                </div>
              )}
            </main>

          </div>
        </div>

        <footer className="flex shrink-0 items-center justify-between gap-3 border-t border-white/8 bg-[#15161c]/95 px-4 pb-[max(.75rem,env(safe-area-inset-bottom))] pt-3 backdrop-blur sm:px-6 sm:py-3">
          <button
            type="button"
            onClick={step === 1 ? onClose : onPrevious}
            disabled={isCreating}
            className="inline-flex h-11 items-center gap-2 rounded-xl border border-white/10 px-4 text-xs font-black text-neutral-300 transition hover:bg-white/5 hover:text-white disabled:opacity-40"
          >
            <ArrowLeft className="h-4 w-4" />
            {step === 1 ? "Vazgeç" : "Geri"}
          </button>
          <span className="hidden text-[11px] font-bold text-neutral-600 sm:block">
            {activeStep.title}
          </span>
          {step < STEPS.length ? (
            <button
              type="button"
              onClick={onNext}
              className="inline-flex h-11 items-center gap-2 rounded-xl bg-gradient-to-r from-fuchsia-300 to-violet-300 px-5 text-xs font-black text-neutral-950 transition hover:brightness-110"
            >
              Devam et
              <ArrowRight className="h-4 w-4" />
            </button>
          ) : (
            <button
              type="button"
              onClick={onSubmit}
              disabled={disabled || isCreating}
              className="inline-flex h-11 items-center gap-2 rounded-xl bg-gradient-to-r from-emerald-300 to-cyan-300 px-5 text-xs font-black text-neutral-950 transition hover:brightness-110 disabled:cursor-not-allowed disabled:grayscale disabled:opacity-50"
            >
              <Rocket className="h-4 w-4" />
              {isCreating ? "Bot hazırlanıyor…" : "Botu oluştur ve başlat"}
            </button>
          )}
        </footer>
      </section>
    </div>
  );
}

function formatAssistantConfidence(value: unknown): string {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "—";
  return `%${(numeric <= 1 ? numeric * 100 : numeric).toFixed(0)}`;
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="block min-w-0">
      <span className="text-xs font-black text-neutral-200">{label}</span>
      {hint && <span className="mt-1 block text-[11px] leading-5 text-neutral-500">{hint}</span>}
      <span className="mt-2 block">{children}</span>
    </label>
  );
}

function CoinPairAutocomplete({
  value,
  onChange,
}: {
  value: string;
  onChange: (symbol: string) => void;
}) {
  const [symbols, setSymbols] = useState<string[]>(FALLBACK_COIN_PAIRS);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const blurTimerRef = useRef<number | null>(null);
  const listboxId = "bot-create-symbol-options";

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadError(false);
    apiFetch<CoinListResponse>("/api/data/coin-list?scope=all")
      .then((response) => {
        if (cancelled) return;
        const candidates = [
          ...(Array.isArray(response.coins) ? response.coins : []),
          ...(Array.isArray(response.symbols) ? response.symbols : []),
          ...FALLBACK_COIN_PAIRS,
        ];
        const normalized = [
          ...new Set(
            candidates
              .map(coinListSymbol)
              .filter((symbol) => symbol.length > 4 && symbol.endsWith("USDT")),
          ),
        ];
        setSymbols(normalized);
      })
      .catch(() => {
        if (!cancelled) {
          setSymbols(FALLBACK_COIN_PAIRS);
          setLoadError(true);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
      if (blurTimerRef.current !== null) {
        window.clearTimeout(blurTimerRef.current);
      }
    };
  }, []);

  const suggestions = useMemo(() => {
    const query = normalizePairSymbol(value);
    const ranked = symbols
      .map((symbol) => {
        const pair = splitTradingSymbol(symbol);
        const match =
          !query ||
          symbol.includes(query) ||
          pair.base.includes(query) ||
          pair.quote.includes(query);
        if (!match) return null;
        const rank =
          symbol === query
            ? 0
            : pair.base === query
              ? 1
              : pair.base.startsWith(query)
                ? 2
                : symbol.startsWith(query)
                  ? 3
                  : 4;
        return { symbol, pair, rank };
      })
      .filter(
        (
          candidate,
        ): candidate is {
          symbol: string;
          pair: ReturnType<typeof splitTradingSymbol>;
          rank: number;
        } => candidate !== null,
      )
      .sort(
        (left, right) =>
          left.rank - right.rank ||
          left.pair.base.localeCompare(right.pair.base),
      );
    return ranked.slice(0, 10);
  }, [symbols, value]);

  useEffect(() => {
    setActiveIndex(0);
  }, [value]);

  const closeLater = () => {
    if (blurTimerRef.current !== null) {
      window.clearTimeout(blurTimerRef.current);
    }
    blurTimerRef.current = window.setTimeout(() => {
      setOpen(false);
      blurTimerRef.current = null;
    }, 140);
  };

  const keepOpen = () => {
    if (blurTimerRef.current !== null) {
      window.clearTimeout(blurTimerRef.current);
      blurTimerRef.current = null;
    }
    setOpen(true);
  };

  const selectSymbol = (symbol: string) => {
    onChange(symbol);
    setOpen(false);
  };

  const onKeyDown = (event: ReactKeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setOpen(true);
      setActiveIndex((current) =>
        Math.min(suggestions.length - 1, current + 1),
      );
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setOpen(true);
      setActiveIndex((current) => Math.max(0, current - 1));
      return;
    }
    if (event.key === "Enter" && open && suggestions[activeIndex]) {
      event.preventDefault();
      selectSymbol(suggestions[activeIndex].symbol);
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      setOpen(false);
    }
  };

  return (
    <div className="relative">
      <span className="pointer-events-none absolute left-3 top-1/2 z-10 -translate-y-1/2">
        <CoinLogo symbol={value} size={28} eager />
      </span>
      <input
        value={value}
        onChange={(event) => {
          onChange(normalizePairSymbol(event.target.value));
          keepOpen();
        }}
        onFocus={keepOpen}
        onBlur={closeLater}
        onKeyDown={onKeyDown}
        maxLength={24}
        autoComplete="off"
        spellCheck={false}
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={open}
        aria-controls={listboxId}
        aria-activedescendant={
          open && suggestions[activeIndex]
            ? `${listboxId}-${suggestions[activeIndex].symbol}`
            : undefined
        }
        className={`${fieldClass} pl-12 pr-11`}
        placeholder="Örn. BTC, SOL veya ETHUSDT"
      />
      <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-neutral-500">
        {loading ? (
          <LoaderCircle className="h-4 w-4 animate-spin" />
        ) : (
          <ChevronDown
            className={`h-4 w-4 transition ${open ? "rotate-180" : ""}`}
          />
        )}
      </span>

      {open && (
        <div
          id={listboxId}
          role="listbox"
          className="absolute inset-x-0 top-[calc(100%+.5rem)] z-40 max-h-72 overflow-y-auto rounded-2xl border border-fuchsia-300/15 bg-[#17181e] p-1.5 shadow-[0_24px_70px_rgba(0,0,0,.6)]"
        >
          <div className="flex items-center justify-between gap-3 px-3 py-2">
            <p className="text-[9px] font-black uppercase tracking-wider text-fuchsia-200">
              {value ? `"${value}" için uygun çiftler` : "Popüler spot çiftleri"}
            </p>
            <span className="text-[9px] font-bold text-neutral-600">
              {suggestions.length} sonuç
            </span>
          </div>
          {suggestions.length ? (
            suggestions.map(({ symbol, pair }, index) => {
              const active = index === activeIndex;
              const selected = symbol === value;
              return (
                <div
                  id={`${listboxId}-${symbol}`}
                  key={symbol}
                  role="option"
                  aria-selected={selected}
                  onMouseEnter={() => setActiveIndex(index)}
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => selectSymbol(symbol)}
                  className={`flex cursor-pointer items-center justify-between gap-3 rounded-xl px-3 py-2.5 transition ${
                    active
                      ? "bg-fuchsia-300/[0.08] text-white"
                      : "text-neutral-300 hover:bg-white/[0.035]"
                  }`}
                >
                  <span className="flex min-w-0 items-center gap-3">
                    <CoinLogo symbol={symbol} size={34} />
                    <span className="min-w-0">
                      <strong className="block truncate text-xs font-black">
                        {pair.base}
                      </strong>
                      <span className="mt-0.5 block text-[9px] font-bold text-neutral-600">
                        {symbol}
                      </span>
                    </span>
                  </span>
                  <span className="flex shrink-0 items-center gap-2">
                    <span className="rounded-full bg-white/5 px-2 py-1 text-[9px] font-black text-neutral-500">
                      / {pair.quote}
                    </span>
                    {selected && (
                      <Check className="h-4 w-4 text-emerald-300" />
                    )}
                  </span>
                </div>
              );
            })
          ) : (
            <div className="rounded-xl border border-dashed border-white/8 px-3 py-5 text-center">
              <p className="text-xs font-black text-neutral-300">
                Eşleşen işlem çifti bulunamadı
              </p>
              <p className="mt-1 text-[10px] leading-5 text-neutral-600">
                Coin adını ya da işlem çiftini farklı yazarak deneyin.
              </p>
            </div>
          )}
          {loadError && (
            <p className="px-3 py-2 text-[9px] leading-4 text-amber-200/70">
              Canlı coin listesine ulaşılamadı; temel çiftler gösteriliyor.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function DynamicModeControl({
  enabled,
  onChange,
}: {
  enabled: boolean;
  onChange: (enabled: boolean) => void;
}) {
  return (
    <section
      className={`overflow-hidden rounded-2xl border transition ${
        enabled
          ? "border-emerald-300/18 bg-gradient-to-br from-emerald-300/[0.07] via-fuchsia-300/[0.035] to-transparent"
          : "border-white/8 bg-white/[0.025]"
      }`}
    >
      <div className="flex flex-col gap-4 p-4 sm:flex-row sm:items-center sm:justify-between sm:p-5">
        <div className="min-w-0">
          <p className="flex items-center gap-2 text-sm font-black text-white">
            <Gauge
              className={`h-4 w-4 ${
                enabled ? "text-emerald-200" : "text-neutral-500"
              }`}
            />
            Dinamik Mod
          </p>
          <p className="mt-2 max-w-2xl text-xs leading-5 text-neutral-400">
            {enabled
              ? "Dinamik mod açık."
              : "Bot her turda girdiğiniz sabit parametreleri kullanır."}
          </p>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={enabled}
          aria-label="Dinamik modu aç veya kapat"
          onClick={() => onChange(!enabled)}
          className={`relative h-9 w-16 shrink-0 rounded-full border transition ${
            enabled
              ? "border-emerald-200/30 bg-emerald-300/20 shadow-[0_0_24px_rgba(110,231,183,.1)]"
              : "border-white/10 bg-black/25"
          }`}
        >
          <span
            className={`absolute top-1 grid h-7 w-7 place-items-center rounded-full transition ${
              enabled
                ? "left-8 bg-emerald-200 text-emerald-950"
                : "left-1 bg-neutral-600 text-neutral-300"
            }`}
          >
            <span className="h-2 w-2 rounded-full bg-current" />
          </span>
        </button>
      </div>

    </section>
  );
}

function PercentInput({
  value,
  onChange,
}: {
  value: number;
  onChange: (value: number) => void;
}) {
  return (
    <div className="relative">
      <NumericInput
        value={value}
        onChange={onChange}
        inputMode="decimal"
        placeholder="0"
        className={`${fieldClass} bot-number-input pr-12`}
      />
      <span className="pointer-events-none absolute right-4 top-1/2 -translate-y-1/2 text-xs font-black text-neutral-500">
        %
      </span>
    </div>
  );
}

function NumericInput({
  value,
  onChange,
  inputMode = "decimal",
  placeholder = "0",
  className,
}: {
  value: number;
  onChange: (value: number) => void;
  inputMode?: "decimal" | "numeric";
  placeholder?: string;
  className: string;
}) {
  const displayValue = (number: number) =>
    Number.isFinite(number) && number !== 0 ? String(number) : "";
  const [draft, setDraft] = useState(() => displayValue(value));
  const focusedRef = useRef(false);

  useEffect(() => {
    if (!focusedRef.current) setDraft(displayValue(value));
  }, [value]);

  const parseDraft = (raw: string): number | null => {
    const normalized = raw.replace(",", ".");
    if (!normalized || normalized === ".") return null;
    const numeric = Number(normalized);
    return Number.isFinite(numeric) ? numeric : null;
  };

  return (
    <input
      type="text"
      inputMode={inputMode}
      pattern={inputMode === "numeric" ? "[0-9]*" : "[0-9]*[.,]?[0-9]*"}
      value={draft}
      placeholder={placeholder}
      autoComplete="off"
      onFocus={(event) => {
        focusedRef.current = true;
        event.currentTarget.setSelectionRange(
          event.currentTarget.value.length,
          event.currentTarget.value.length,
        );
      }}
      onChange={(event) => {
        const entered = event.target.value;
        const raw =
          inputMode === "decimal" && entered === "0" ? "0," : entered;
        const valid =
          inputMode === "numeric"
            ? /^\d*$/.test(raw)
            : /^\d*(?:[.,]\d*)?$/.test(raw);
        if (!valid) return;
        setDraft(raw);
        const numeric = parseDraft(raw);
        if (numeric !== null) onChange(numeric);
      }}
      onBlur={() => {
        focusedRef.current = false;
        const numeric = parseDraft(draft);
        if (numeric === null) {
          setDraft(displayValue(value));
          return;
        }
        onChange(numeric);
        setDraft(displayValue(numeric));
      }}
      className={className}
    />
  );
}

function GridEditor({
  side,
  title,
  description,
  grids,
  trail,
  onTrailChange,
  onCountChange,
  onGridChange,
}: {
  side: "up" | "down";
  title: string;
  description: string;
  grids: GridDraft[];
  trail: number;
  onTrailChange: (value: number) => void;
  onCountChange: (count: number) => void;
  onGridChange: (index: number, patch: Partial<GridDraft>) => void;
}) {
  const positive = side === "up";
  const totalQty = grids.reduce((sum, grid) => sum + Number(grid.qty_pct || 0), 0);
  return (
    <section className="overflow-hidden rounded-2xl border border-white/8 bg-white/[0.025]">
      <header className="border-b border-white/8 p-4 sm:p-5">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className={`text-sm font-black ${positive ? "text-emerald-200" : "text-sky-200"}`}>
              {title}
            </p>
            <p className="mt-1 max-w-xl text-xs leading-5 text-neutral-500">{description}</p>
          </div>
          <div className="grid grid-cols-2 gap-2 sm:w-64">
            <Field label="Grid adeti">
              <NumericInput
                value={grids.length}
                onChange={(value) => onCountChange(clampGridCount(value))}
                inputMode="numeric"
                placeholder="1"
                className={`${fieldClass} bot-number-input`}
              />
            </Field>
            <Field label="Trailing">
              <PercentInput value={trail} onChange={onTrailChange} />
            </Field>
          </div>
        </div>
        <div
          className={`mt-4 hidden grid-cols-4 gap-1 rounded-xl border p-2 sm:grid ${
            positive
              ? "border-emerald-300/10 bg-emerald-300/[0.025]"
              : "border-sky-300/10 bg-sky-300/[0.025]"
          }`}
        >
          {[
            "Referans fiyat",
            positive ? "Yükseliş tetiği" : "Düşüş tetiği",
            positive ? "Tepe trailing" : "Dip trailing",
            positive ? "Kademeli satış" : "Kademeli alış",
          ].map((label, index) => (
            <div key={label} className="min-w-0 text-center">
              <span
                className={`mx-auto grid h-6 w-6 place-items-center rounded-full text-[9px] font-black ${
                  positive
                    ? "bg-emerald-300/10 text-emerald-200"
                    : "bg-sky-300/10 text-sky-200"
                }`}
              >
                {index + 1}
              </span>
              <p className="mt-1.5 truncate text-[8px] font-black uppercase tracking-wider text-neutral-600">
                {label}
              </p>
            </div>
          ))}
        </div>
      </header>
      <div className="p-4 sm:p-5">
        <div className="mb-3 grid grid-cols-[44px_1fr_1fr] gap-2 px-1 text-[10px] font-black uppercase tracking-wider text-neutral-600">
          <span>Seviye</span>
          <span>Tetik mesafesi</span>
          <span>Kullanılacak pay</span>
        </div>
        <div className="space-y-2">
          {grids.map((grid, index) => (
            <div
              key={`${side}-${index}`}
              className="grid grid-cols-[44px_1fr_1fr] items-center gap-2 rounded-xl border border-white/7 bg-black/15 p-2"
            >
              <span
                className={`grid h-9 w-9 place-items-center rounded-lg text-xs font-black ${
                  positive
                    ? "bg-emerald-300/8 text-emerald-200"
                    : "bg-sky-300/8 text-sky-200"
                }`}
              >
                {index + 1}
              </span>
              <PercentInput
                value={grid.trigger_pct}
                onChange={(value) => onGridChange(index, { trigger_pct: value })}
              />
              <PercentInput
                value={grid.qty_pct}
                onChange={(value) => onGridChange(index, { qty_pct: value })}
              />
            </div>
          ))}
        </div>
        <div className="mt-3 flex items-center justify-between rounded-xl border border-white/7 bg-white/[0.02] px-3 py-2 text-xs">
          <span className="font-bold text-neutral-500">Kademe payları toplamı</span>
          <span
            className={`font-black ${
              Math.abs(totalQty - 100) <= 0.5 ? "text-emerald-300" : "text-red-300"
            }`}
          >
            %{totalQty.toFixed(1)}
          </span>
        </div>
      </div>
    </section>
  );
}

function AllocationAmount({
  label,
  value,
  percent,
  tone,
  alignRight = false,
}: {
  label: string;
  value: string;
  percent: number;
  tone: "violet" | "sky";
  alignRight?: boolean;
}) {
  return (
    <div
      className={`min-w-0 rounded-xl border px-3 py-2 ${alignRight ? "text-right" : "text-left"} ${tone === "violet" ? "border-fuchsia-300/10 bg-fuchsia-300/[0.035]" : "border-sky-300/10 bg-sky-300/[0.035]"}`}
      style={{ flexGrow: Math.max(15, percent), flexBasis: 0 }}
    >
      <span className="block truncate text-[10px] font-semibold text-neutral-500">{label} · %{percent}</span>
      <strong className="mt-1 block truncate text-xs font-black text-white">{value}</strong>
    </div>
  );
}

