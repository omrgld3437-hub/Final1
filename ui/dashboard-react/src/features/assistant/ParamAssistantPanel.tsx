import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  BrainCircuit,
  CircleDollarSign,
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

function pct(value: unknown): string {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "—";
  const normalized = numeric <= 1 ? numeric * 100 : numeric;
  return `%${normalized.toFixed(normalized % 1 === 0 ? 0 : 2)}`;
}

function formatLadder(
  grids: Array<Record<string, number>> | undefined,
  side: "buy" | "sell",
): string {
  if (!grids?.length) return "—";
  return grids
    .map((row) => {
      const dist = Number(
        side === "buy"
          ? row.buy_grid_pct ?? row.trigger_pct ?? row.distance_pct
          : row.sell_grid_pct ?? row.trigger_pct ?? row.distance_pct,
      );
      const amt = Number(
        side === "buy"
          ? row.buy_qty_pct_of_quote ?? row.qty_pct ?? row.amount_pct
          : row.sell_qty_pct_of_base ?? row.qty_pct ?? row.amount_pct,
      );
      if (!Number.isFinite(dist) || !Number.isFinite(amt)) return null;
      const sign = side === "buy" ? "−" : "+";
      return `${sign}%${Math.abs(dist)} → %${amt}`;
    })
    .filter(Boolean)
    .join("; ");
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
  const canApply = Boolean(config?.up?.grids?.length || config?.down?.grids?.length);
  const referenceOnly = Boolean(
    config?.recommendation_only ||
      result?.legacy_parameter_application_disabled ||
      (result?.deployable === false &&
        String(result?.apply_policy || "").toLowerCase().includes("no_trade")),
  );
  const headline =
    String(
      result?.profile_headline ||
        config?.profile_display ||
        config?.display_regime_label ||
        result?.display_regime_label ||
        result?.market_status_plain ||
        result?.selected_profile ||
        "—",
    );
  const whyText = String(
    result?.profile_explanation || result?.explain || "",
  );
  const basePct = Number(config?.base_alloc_pct);
  const quotePct = Number(config?.quote_alloc_pct);
  const sellLadder = formatLadder(config?.up?.grids, "sell");
  const buyLadder = formatLadder(config?.down?.grids, "buy");
  const sellTrail = config?.up?.trail_pct;
  const buyTrail = config?.down?.trail_pct;
  const profit = config?.profit;

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
          <span className="rounded-full border border-fuchsia-200/20 bg-fuchsia-200/10 px-2 py-1 text-[10px] font-black text-fuchsia-100">
            V6 · 4+4
          </span>
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
        <p role="alert" className="mt-3 flex gap-2 rounded-xl border border-red-400/20 bg-red-400/5 px-3 py-2.5 text-xs text-red-200">
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
              {result.profile_key || result.selected_profile || result.template_key || "—"}
              {" · "}
              {result.automatic_apply_label ||
                (result.deployable ? "Uygulanabilir" : "Referans / koşullu")}
              {" · Risk "}
              {result.risk_display_label || pct(result.risk_score)}
            </p>
          </section>

          <div className="grid gap-2 lg:grid-cols-3">
            <AdviceTile
              icon={CircleDollarSign}
              title="Base / Quote"
              text={
                Number.isFinite(basePct) && Number.isFinite(quotePct)
                  ? `%${basePct} base / %${quotePct} quote`
                  : "—"
              }
              tone="allocation"
            />
            <AdviceTile
              icon={ArrowUp}
              title={`Satış gridleri (4) · trail ${pct(sellTrail)}`}
              text={sellLadder}
              tone="sell"
            />
            <AdviceTile
              icon={ArrowDown}
              title={`Alış gridleri (4) · trail ${pct(buyTrail)}`}
              text={buyLadder}
              tone="buy"
            />
          </div>

          <section className="rounded-xl border border-fuchsia-300/12 bg-fuchsia-300/[0.03] p-4">
            <p className="text-[10px] font-black uppercase tracking-wider text-fuchsia-100">
              Kâr döngüsü
            </p>
            <p className="mt-2 text-[11px] leading-5 text-neutral-300">
              Alınan coinlerin kâr satışı:{" "}
              {profit?.resell_enabled === false || profit?.resell_trigger_pct == null
                ? "Kapalı"
                : `+${pct(profit.resell_trigger_pct)} · trailing ${pct(profit.resell_trail_pct)}`}
            </p>
            <p className="mt-1 text-[11px] leading-5 text-neutral-300">
              Satılan coinlerin kâr alışı:{" "}
              {profit?.rebuy_enabled === false || profit?.rebuy_trigger_pct == null
                ? "Kapalı"
                : `−${pct(profit.rebuy_trigger_pct)} · trailing ${pct(profit.rebuy_trail_pct)}`}
            </p>
          </section>

          {whyText ? (
            <section className="rounded-xl border border-white/8 bg-white/[0.025] p-4">
              <p className="text-[10px] font-black uppercase tracking-wider text-neutral-500">
                Neden bu profil?
              </p>
              <p className="mt-2 text-xs leading-6 text-neutral-300">{whyText}</p>
            </section>
          ) : null}

          {referenceOnly ? (
            <p className="flex gap-2 rounded-xl border border-amber-300/20 bg-amber-300/5 px-3 py-2.5 text-[11px] text-amber-100">
              <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
              Bu profil referans / koşullu plandır. Değerler forma aktarılabilir; otomatik emir güvenliği
              deploy kapısıyla sınırlıdır.
            </p>
          ) : null}

          <div className="flex flex-col gap-2 sm:flex-row">
            <button
              type="button"
              onClick={handleApply}
              disabled={!canApply}
              className="inline-flex min-h-11 flex-1 items-center justify-center gap-2 rounded-xl border border-emerald-300/25 bg-emerald-300/15 px-4 py-2.5 text-xs font-black text-emerald-100 transition hover:bg-emerald-300/25 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Sparkles className="h-4 w-4" />
              {applied ? "Forma uygulandı" : "Forma uygula"}
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

function AdviceTile({
  icon: Icon,
  title,
  text,
  tone,
}: {
  icon: typeof ArrowUp;
  title: string;
  text?: string;
  tone: "allocation" | "sell" | "buy";
}) {
  const color =
    tone === "sell"
      ? "border-emerald-300/12 bg-emerald-300/[0.035] text-emerald-200"
      : tone === "buy"
        ? "border-sky-300/12 bg-sky-300/[0.035] text-sky-200"
        : "border-fuchsia-300/12 bg-fuchsia-300/[0.035] text-fuchsia-100";
  return (
    <section className={`rounded-xl border p-3 ${color}`}>
      <p className="flex items-center gap-2 text-[10px] font-black uppercase tracking-wider">
        <Icon className="h-3.5 w-3.5" />
        {title}
      </p>
      <p className="mt-2 text-[11px] leading-5 text-neutral-300">{text || "—"}</p>
    </section>
  );
}
