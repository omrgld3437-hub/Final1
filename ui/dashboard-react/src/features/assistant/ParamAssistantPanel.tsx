import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  BrainCircuit,
  LoaderCircle,
  ShieldAlert,
  Sparkles,
} from "lucide-react";
import { apiFetch } from "../../lib/api";

export interface AssistantConfig {
  symbol?: string;
  budget_usd?: number;
  base_alloc_pct?: number;
  quote_alloc_pct?: number;
  up?: {
    grids?: Array<Record<string, number>>;
    trail_pct?: number;
    enabled?: boolean;
  };
  down?: {
    grids?: Array<Record<string, number>>;
    trail_pct?: number;
    enabled?: boolean;
  };
  profit?: {
    rebuy_trigger_pct?: number;
    rebuy_trail_pct?: number;
    resell_trigger_pct?: number;
    resell_trail_pct?: number;
    rebuy_enabled?: boolean;
    resell_enabled?: boolean;
  };
  max_buy_levels?: number;
  profile_display?: string;
  display_regime_label?: string;
  market_status_plain?: string;
  recommendation_only?: boolean;
  [key: string]: unknown;
}

export interface AssistantResult {
  ok?: boolean;
  job_id?: string;
  decision_id?: string;
  decision?: string;
  final_action?: string;
  final_action_label?: string;
  display_regime_label?: string;
  regime_tag?: string;
  market_status_plain?: string;
  selected_profile?: string;
  template_key?: string;
  param_score?: number;
  deployable?: boolean;
  can_apply_safe_overlay?: boolean;
  confidence?: number;
  confidence_display_pct?: number | string;
  risk_score?: number;
  risk_display_label?: string;
  explain?: string;
  warnings?: string[];
  blocking_reasons?: string[];
  rationale?: string[];
  data_quality?: Record<string, unknown>;
  data_quality_display?: string;
  safe_overlay?: Record<string, unknown>;
  management_mode?: string;
  mode?: string;
  legacy_parameter_application_disabled?: boolean;
  apply_policy?: string;
  apply_policy_label?: string;
  profile_key?: string;
  profile_headline?: string;
  profile_explanation?: string;
  automatic_apply_label?: string;
  ui_config?: AssistantConfig | null;
  recommendation_config?: AssistantConfig | null;
  v6_display?: Record<string, unknown>;
  [key: string]: unknown;
}

type LadderRow = { trigger: number; qty: number };

function asPctNumber(value: unknown): number | null {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return null;
  return numeric <= 1 && numeric !== 0 ? numeric * 100 : numeric;
}

function formatPct(value: unknown, digits = 2): string {
  const numeric = asPctNumber(value);
  if (numeric == null) return "—";
  const fixed =
    Number.isInteger(numeric) || Math.abs(numeric * 10 - Math.round(numeric * 10)) < 1e-9
      ? numeric.toFixed(numeric % 1 === 0 ? 0 : 1)
      : numeric.toFixed(digits);
  return `%${fixed.replace(/\.0+$/, "").replace(/(\.\d)0$/, "$1")}`;
}

function extractLadder(
  grids: Array<Record<string, number>> | undefined,
  side: "buy" | "sell",
): LadderRow[] {
  if (!grids?.length) return [];
  return grids
    .map((row) => {
      const trigger = Number(
        side === "buy"
          ? row.trigger_pct ?? row.buy_grid_pct ?? row.distance_pct
          : row.trigger_pct ?? row.sell_grid_pct ?? row.distance_pct,
      );
      const qty = Number(
        side === "buy"
          ? row.qty_pct ?? row.buy_qty_pct_of_quote ?? row.amount_pct
          : row.qty_pct ?? row.sell_qty_pct_of_base ?? row.amount_pct,
      );
      if (!Number.isFinite(trigger) || !Number.isFinite(qty)) return null;
      return { trigger: Math.abs(trigger), qty: Math.abs(qty) };
    })
    .filter((row): row is LadderRow => row != null);
}

export default function ParamAssistantPanel({
  symbol,
  budget,
  onApply,
}: {
  symbol: string;
  budget: number;
  onApply: (config: AssistantConfig, result: AssistantResult) => void;
}) {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<AssistantResult | null>(null);
  const [error, setError] = useState("");
  const [applied, setApplied] = useState(false);
  const scopeKey = useMemo(
    () => `${symbol.trim().toUpperCase()}::${Number(budget).toFixed(8)}`,
    [budget, symbol],
  );

  useEffect(() => {
    setResult(null);
    setError("");
    setApplied(false);
  }, [scopeKey]);

  const analyze = async () => {
    if (loading) return;
    if (!symbol.trim() || budget < 25) {
      setError("Analiz için geçerli bir parite ve en az 25 USDT bütçe gerekir.");
      return;
    }
    setLoading(true);
    setError("");
    setApplied(false);
    try {
      // Use V6 calculate (net_profile_library 4+4). Do not use /advice —
      // that path strips ui_config and returns narrative-only templates.
      const response = await apiFetch<AssistantResult>("/api/param-assistant/calculate", {
        method: "POST",
        body: JSON.stringify({
          symbol: symbol.trim().toUpperCase(),
          budget,
          analysis_level: "professional_auto",
          // Bilateral library plan for PA display/apply (not first-start buy-only).
          first_start_buy_only: false,
          dry_run: true,
        }),
        timeoutMs: 90_000,
      });
      if (!response?.ok) {
        throw new Error("Analiz sonucu doğrulanamadı.");
      }
      const config = response.ui_config || response.recommendation_config;
      if (!config) {
        throw new Error("Profil parametreleri üretilemedi.");
      }
      setResult(response);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Piyasa analizi tamamlanamadı.");
    } finally {
      setLoading(false);
    }
  };

  const config = result?.ui_config || result?.recommendation_config || null;
  const sellRows = extractLadder(config?.up?.grids, "sell");
  const buyRows = extractLadder(config?.down?.grids, "buy");
  const canApply = Boolean(sellRows.length || buyRows.length);
  const referenceOnly = Boolean(
    config?.recommendation_only ||
      result?.legacy_parameter_application_disabled ||
      (result?.deployable === false &&
        String(result?.apply_policy || "").toLowerCase().includes("no_trade")),
  );
  const headline = String(
    result?.profile_headline ||
      config?.profile_display ||
      config?.display_regime_label ||
      result?.display_regime_label ||
      result?.market_status_plain ||
      result?.selected_profile ||
      "—",
  );
  const whyText = String(result?.profile_explanation || result?.explain || "");
  const basePct = asPctNumber(config?.base_alloc_pct) ?? 0;
  const quotePct = asPctNumber(config?.quote_alloc_pct) ?? Math.max(0, 100 - basePct);
  const allocationTotal = basePct + quotePct;
  const sellTrail = asPctNumber(config?.up?.trail_pct);
  const buyTrail = asPctNumber(config?.down?.trail_pct);
  const profit = config?.profit;
  const sellQtyTotal = sellRows.reduce((sum, row) => sum + row.qty, 0);
  const buyQtyTotal = buyRows.reduce((sum, row) => sum + row.qty, 0);
  const baseAmount =
    Number.isFinite(budget) && budget > 0 ? (budget * basePct) / 100 : null;
  const quoteAmount =
    Number.isFinite(budget) && budget > 0 ? (budget * quotePct) / 100 : null;

  const handleApply = () => {
    if (!result || !config || !canApply) return;
    onApply(config, result);
    setApplied(true);
  };

  return (
    <section className="rounded-2xl border border-fuchsia-300/15 bg-gradient-to-br from-fuchsia-300/[0.07] to-amber-300/[0.03] p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="flex items-center gap-2 text-sm font-black text-white">
          <BrainCircuit className="h-4 w-4 text-fuchsia-200" />
          Parametre Asistanı
        </p>
        <button
          type="button"
          onClick={() => void analyze()}
          disabled={loading}
          aria-busy={loading}
          className="isolate inline-flex min-h-11 w-full shrink-0 items-center justify-center overflow-hidden whitespace-nowrap rounded-xl border border-fuchsia-200/20 bg-fuchsia-200/10 px-4 py-2.5 text-xs font-black leading-none text-fuchsia-100 transition hover:bg-fuchsia-200/15 disabled:cursor-not-allowed disabled:opacity-55 sm:w-44"
        >
          {loading ? (
            <span className="inline-flex items-center justify-center gap-2">
              <LoaderCircle className="h-4 w-4 shrink-0 animate-spin" />
              <span>Analiz ediliyor…</span>
            </span>
          ) : (
            <span className="inline-flex items-center justify-center gap-2">
              <Sparkles className="h-4 w-4 shrink-0" />
              <span>{result ? "Yeniden analiz et" : "Piyasayı analiz et"}</span>
            </span>
          )}
        </button>
      </div>

      {error && (
        <p
          role="alert"
          className="mt-3 flex gap-2 rounded-xl border border-red-400/20 bg-red-400/5 px-3 py-2.5 text-xs text-red-200"
        >
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          {error}
        </p>
      )}

      {result && config && (
        <div className="mt-4 space-y-3 border-t border-white/8 pt-4">
          <section className="rounded-2xl border border-white/10 bg-black/20 p-4">
            <p className="text-[10px] font-black uppercase tracking-wider text-fuchsia-100">
              Seçilen profil
            </p>
            <p className="mt-2 text-sm font-black leading-6 text-white">{headline}</p>
            <p className="mt-2 text-[11px] leading-5 text-neutral-400">
              {result.automatic_apply_label ||
                (result.deployable ? "Uygulanabilir" : "Referans / koşullu")}
              {" · Risk "}
              {result.risk_display_label || formatPct(result.risk_score)}
            </p>
            {whyText ? (
              <p className="mt-3 text-xs leading-6 text-neutral-300">{whyText}</p>
            ) : null}
          </section>

          <section className="rounded-2xl border border-white/8 bg-black/15 p-4">
            <div className="flex items-center justify-between text-xs">
              <span className="font-bold text-neutral-400">Dağılım haritası</span>
              <span
                className={`font-black ${
                  Math.abs(allocationTotal - 100) <= 0.5
                    ? "text-emerald-300"
                    : "text-red-300"
                }`}
              >
                Toplam {formatPct(allocationTotal, 1)}
              </span>
            </div>
            <div className="mt-3 flex h-4 overflow-hidden rounded-full bg-white/5">
              <div
                className="bg-gradient-to-r from-fuchsia-400 to-violet-400 transition-all"
                style={{ width: `${Math.min(100, Math.max(0, basePct))}%` }}
              />
              <div className="flex-1 bg-gradient-to-r from-sky-400 to-cyan-300" />
            </div>
            <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
              <div className="rounded-xl border border-fuchsia-300/10 bg-fuchsia-300/[0.035] px-3 py-2">
                <span className="block text-[10px] font-semibold text-neutral-500">
                  Base · {formatPct(basePct, 1)}
                </span>
                <strong className="mt-1 block text-xs font-black text-white">
                  {baseAmount != null
                    ? `${baseAmount.toLocaleString("tr-TR", {
                        maximumFractionDigits: 2,
                      })} USDT`
                    : "—"}
                </strong>
              </div>
              <div className="rounded-xl border border-sky-300/10 bg-sky-300/[0.035] px-3 py-2 text-right">
                <span className="block text-[10px] font-semibold text-neutral-500">
                  Quote · {formatPct(quotePct, 1)}
                </span>
                <strong className="mt-1 block text-xs font-black text-white">
                  {quoteAmount != null
                    ? `${quoteAmount.toLocaleString("tr-TR", {
                        maximumFractionDigits: 2,
                      })} USDT`
                    : "—"}
                </strong>
              </div>
            </div>
          </section>

          <LadderPreview
            title="Kademeli satış planı"
            description="Fiyat yükseldikçe tetiklenecek satış seviyeleri ve her seviyede satılacak coin payı."
            side="sell"
            rows={sellRows}
            trail={sellTrail}
            totalQty={sellQtyTotal}
          />

          <LadderPreview
            title="Kademeli alış planı"
            description="Fiyat düştükçe tetiklenecek alış seviyeleri ve her seviyede alınacak quote payı."
            side="buy"
            rows={buyRows}
            trail={buyTrail}
            totalQty={buyQtyTotal}
          />

          <section className="grid gap-2 rounded-2xl border border-white/8 bg-white/[0.025] p-4 sm:grid-cols-2">
            <MetricCard
              label="Kâr satışı tetiği"
              value={
                profit?.resell_enabled === false || profit?.resell_trigger_pct == null
                  ? "Kapalı"
                  : formatPct(profit.resell_trigger_pct)
              }
              hint={
                profit?.resell_enabled === false || profit?.resell_trail_pct == null
                  ? "Alınan coinlerin kâr satışı"
                  : `Trailing ${formatPct(profit.resell_trail_pct)}`
              }
            />
            <MetricCard
              label="Kâr satışı trailing"
              value={
                profit?.resell_enabled === false || profit?.resell_trail_pct == null
                  ? "—"
                  : formatPct(profit.resell_trail_pct)
              }
              hint="Tepeden geri çekilince satış"
            />
            <MetricCard
              label="Kâr alışı tetiği"
              value={
                profit?.rebuy_enabled === false || profit?.rebuy_trigger_pct == null
                  ? "Kapalı"
                  : formatPct(profit.rebuy_trigger_pct)
              }
              hint={
                profit?.rebuy_enabled === false || profit?.rebuy_trail_pct == null
                  ? "Satılan coinlerin kâr alışı"
                  : `Trailing ${formatPct(profit.rebuy_trail_pct)}`
              }
            />
            <MetricCard
              label="Kâr alışı trailing"
              value={
                profit?.rebuy_enabled === false || profit?.rebuy_trail_pct == null
                  ? "—"
                  : formatPct(profit.rebuy_trail_pct)
              }
              hint="Dipten toparlanınca alış"
            />
          </section>

          {referenceOnly ? (
            <p className="flex gap-2 rounded-xl border border-amber-300/20 bg-amber-300/5 px-3 py-2.5 text-[11px] text-amber-100">
              <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
              Bu profil referans / koşullu plandır. Değerler forma aktarılabilir; otomatik emir
              güvenliği deploy kapısıyla sınırlıdır.
            </p>
          ) : null}

          <button
            type="button"
            onClick={handleApply}
            disabled={!canApply}
            className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-xl border border-emerald-300/25 bg-emerald-300/15 px-4 py-2.5 text-xs font-black text-emerald-100 transition hover:bg-emerald-300/25 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Sparkles className="h-4 w-4" />
            {applied ? "Forma uygulandı" : "Forma uygula"}
          </button>
        </div>
      )}
    </section>
  );
}

function LadderPreview({
  title,
  description,
  side,
  rows,
  trail,
  totalQty,
}: {
  title: string;
  description: string;
  side: "buy" | "sell";
  rows: LadderRow[];
  trail: number | null;
  totalQty: number;
}) {
  const positive = side === "sell";
  return (
    <section className="overflow-hidden rounded-2xl border border-white/8 bg-white/[0.025]">
      <header className="border-b border-white/8 p-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p
              className={`text-sm font-black ${
                positive ? "text-emerald-200" : "text-sky-200"
              }`}
            >
              {title}
            </p>
            <p className="mt-1 max-w-xl text-xs leading-5 text-neutral-500">{description}</p>
          </div>
          <div className="rounded-xl border border-white/8 bg-black/15 px-3 py-2 text-right">
            <p className="text-[10px] font-black uppercase tracking-wider text-neutral-600">
              Trailing
            </p>
            <p className="mt-1 text-xs font-black text-white">
              {trail == null ? "—" : formatPct(trail)}
            </p>
          </div>
        </div>
      </header>
      <div className="p-4">
        {rows.length ? (
          <>
            <div className="mb-3 grid grid-cols-[44px_1fr_1fr] gap-2 px-1 text-[10px] font-black uppercase tracking-wider text-neutral-600">
              <span>Seviye</span>
              <span>Tetik mesafesi</span>
              <span>Kullanılacak pay</span>
            </div>
            <div className="space-y-2">
              {rows.map((row, index) => (
                <div
                  key={`${side}-${index}-${row.trigger}-${row.qty}`}
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
                  <p className="rounded-xl border border-white/8 bg-black/20 px-3 py-2.5 text-xs font-black text-white">
                    {positive ? "+" : "−"}
                    {formatPct(row.trigger).replace("%", "")}%
                  </p>
                  <p className="rounded-xl border border-white/8 bg-black/20 px-3 py-2.5 text-xs font-black text-white">
                    {formatPct(row.qty)}
                  </p>
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
                {formatPct(totalQty, 1)}
              </span>
            </div>
          </>
        ) : (
          <p className="text-xs text-neutral-500">Bu yönde aktif grid yok.</p>
        )}
      </div>
    </section>
  );
}

function MetricCard({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint: string;
}) {
  return (
    <div className="rounded-xl border border-white/7 bg-black/15 p-3">
      <p className="text-[9px] font-black uppercase tracking-wider text-neutral-600">{label}</p>
      <p className="mt-1.5 text-sm font-black text-white">{value}</p>
      <p className="mt-1 text-[10px] leading-4 text-neutral-500">{hint}</p>
    </div>
  );
}
