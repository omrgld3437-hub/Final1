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
  [key: string]: unknown;
}

interface MarketRecommendation {
  scenario_code?: string;
  tone?: "positive" | "neutral" | "caution" | "danger" | "critical";
  title?: string;
  summary?: string;
  action?: string;
  allocation?: string;
  sell_grid?: string;
  buy_grid?: string;
  reasons?: string[];
  interpretation?: string;
  risk_control?: string;
  invalidation?: string;
  engine_plan?: {
    status?: string;
    allocation?: string;
    buy_ladder?: string;
    sell_ladder?: string;
    trailing?: string;
    profit_cycle?: string;
  };
  market_evidence?: string[];
  disclaimer?: string;
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
  recommendation?: MarketRecommendation;
  ui_config?: AssistantConfig | null;
  recommendation_config?: AssistantConfig | null;
  [key: string]: unknown;
}

function pct(value: unknown): string {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "—";
  const normalized = numeric <= 1 ? numeric * 100 : numeric;
  return `%${normalized.toFixed(0)}`;
}

function toneClasses(tone: MarketRecommendation["tone"]): string {
  if (tone === "critical") {
    return "border-red-400/25 bg-red-400/[0.07] text-red-100";
  }
  if (tone === "danger") {
    return "border-orange-300/20 bg-orange-300/[0.06] text-orange-100";
  }
  if (tone === "positive") {
    return "border-emerald-300/20 bg-emerald-300/[0.055] text-emerald-100";
  }
  if (tone === "caution") {
    return "border-amber-300/20 bg-amber-300/[0.055] text-amber-100";
  }
  return "border-sky-300/15 bg-sky-300/[0.045] text-sky-100";
}

export default function ParamAssistantPanel({
  symbol,
  budget,
}: {
  symbol: string;
  budget: number;
  onApply: (config: AssistantConfig, result: AssistantResult) => void;
}) {
  const assistantAvailable = false;
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<AssistantResult | null>(null);
  const [error, setError] = useState("");
  const scopeKey = useMemo(
    () => `${symbol.trim().toUpperCase()}::${Number(budget).toFixed(8)}`,
    [budget, symbol],
  );

  useEffect(() => {
    setResult(null);
    setError("");
  }, [scopeKey]);

  const analyze = async () => {
    if (!assistantAvailable) return;
    if (loading) return;
    if (!symbol.trim() || budget < 25) {
      setError("Analiz için geçerli bir parite ve en az 25 USDT bütçe gerekir.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const response = await apiFetch<AssistantResult>("/api/param-assistant/advice", {
        method: "POST",
        body: JSON.stringify({
          symbol: symbol.trim().toUpperCase(),
          budget,
          analysis_level: "professional_auto",
          first_start_buy_only: true,
          dry_run: true,
        }),
        timeoutMs: 90_000,
      });
      if (!response?.ok || !response.recommendation) {
        throw new Error("Analiz sonucu doğrulanamadı.");
      }
      setResult(response);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Piyasa analizi tamamlanamadı.");
    } finally {
      setLoading(false);
    }
  };

  const recommendation = result?.recommendation;
  const enginePlan = recommendation?.engine_plan;

  return (
    <section className="rounded-2xl border border-fuchsia-300/15 bg-gradient-to-br from-fuchsia-300/[0.07] to-amber-300/[0.03] p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="flex items-center gap-2 text-sm font-black text-white">
          <BrainCircuit className="h-4 w-4 text-fuchsia-200" />
          Parametre Asistanı
          <span className="rounded-full border border-amber-200/20 bg-amber-200/10 px-2 py-1 text-[10px] font-black text-amber-100">
            Çok yakında
          </span>
        </p>
        <button
          type="button"
          onClick={() => void analyze()}
          disabled={!assistantAvailable || loading}
          aria-disabled={!assistantAvailable}
          aria-busy={loading}
          className="isolate inline-flex min-h-11 w-full shrink-0 items-center justify-center overflow-hidden whitespace-nowrap rounded-xl border border-fuchsia-200/20 bg-fuchsia-200/10 px-4 py-2.5 text-xs font-black leading-none text-fuchsia-100 transition hover:bg-fuchsia-200/15 disabled:cursor-not-allowed disabled:opacity-55 sm:w-44"
        >
          {!assistantAvailable ? (
            <span className="inline-flex items-center justify-center gap-2">
              <Sparkles className="h-4 w-4 shrink-0" />
              <span>Çok yakında</span>
            </span>
          ) : loading ? (
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

      {result && recommendation && (
        <div className="mt-4 space-y-3 border-t border-white/8 pt-4">
          <div className="grid grid-cols-2 gap-2">
            <InfoTile
              label="Piyasa"
              value={result.market_status_plain || recommendation.title || "—"}
              className="col-span-2 sm:col-span-1"
            />
            <InfoTile
              label="Risk"
              value={result.risk_display_label || pct(result.risk_score)}
            />
          </div>

          <section className={`rounded-2xl border p-4 ${toneClasses(recommendation.tone)}`}>
            <div className="flex items-start gap-3">
              <ShieldAlert className="mt-0.5 h-5 w-5 shrink-0" />
              <div>
                <p className="text-xs font-black tracking-wide">
                  {recommendation.title}
                </p>
                <p className="mt-2 text-xs leading-5 text-current/85">
                  {recommendation.summary}
                </p>
                <p className="mt-3 rounded-xl bg-black/15 px-3 py-2.5 text-xs font-bold leading-5">
                  {recommendation.action}
                </p>
              </div>
            </div>
          </section>

          <section className="rounded-xl border border-white/8 bg-white/[0.025] p-4">
            <p className="text-[10px] font-black uppercase tracking-wider text-fuchsia-100">
              Bu kararı nasıl okumalı?
            </p>
            <p className="mt-2 text-xs leading-6 text-neutral-300">
              {recommendation.interpretation}
            </p>
          </section>

          <div>
            <p className="mb-2 text-[10px] font-black uppercase tracking-wider text-neutral-500">
              Motorun bu coin için hesapladığı somut plan
            </p>
            <div className="grid gap-2 lg:grid-cols-3">
              <AdviceTile
                icon={CircleDollarSign}
                title="Coin / nakit oranı"
                text={recommendation.allocation || enginePlan?.allocation}
                tone="allocation"
              />
              <AdviceTile
                icon={ArrowUp}
                title="Satış gridleri"
                text={enginePlan?.sell_ladder || recommendation.sell_grid}
                tone="sell"
              />
              <AdviceTile
                icon={ArrowDown}
                title="Alım gridleri"
                text={enginePlan?.buy_ladder || recommendation.buy_grid}
                tone="buy"
              />
            </div>
          </div>

          {(enginePlan?.trailing || enginePlan?.profit_cycle) && (
            <section className="rounded-xl border border-fuchsia-300/12 bg-fuchsia-300/[0.03] p-4">
              <p className="text-[10px] font-black uppercase tracking-wider text-fuchsia-100">
                Trailing ve kâr döngüsü
              </p>
              <p className="mt-2 text-[11px] leading-5 text-neutral-300">
                {enginePlan.status}
              </p>
              <p className="mt-1 text-[11px] leading-5 text-neutral-300">
                {enginePlan.trailing}
              </p>
              <p className="mt-1 text-[11px] leading-5 text-neutral-300">
                {enginePlan.profit_cycle}
              </p>
            </section>
          )}

          {recommendation.market_evidence?.length ? (
            <section className="rounded-xl border border-white/7 bg-black/15 p-4">
              <p className="text-[10px] font-black uppercase tracking-wider text-neutral-500">
                Motor neden bu sonuca ulaştı?
              </p>
              <ul className="mt-2 space-y-1.5 text-[11px] leading-5 text-neutral-300">
                {recommendation.market_evidence.map((evidence, index) => (
                  <li key={`${evidence}-${index}`}>• {evidence}</li>
                ))}
              </ul>
            </section>
          ) : null}

          <div className="grid gap-2 lg:grid-cols-3">
            <AdviceTile
              icon={ShieldAlert}
              title="Risk sınırı"
              text={recommendation.risk_control}
              tone="allocation"
            />
            <AdviceTile
              icon={Sparkles}
              title="Ne zaman yeniden analiz?"
              text={recommendation.invalidation}
              tone="sell"
            />
            <AdviceTile
              icon={BrainCircuit}
              title="Ana karar"
              text={recommendation.action}
              tone="buy"
            />
          </div>

          <p className="text-[10px] leading-5 text-neutral-500">
            {recommendation.disclaimer}
          </p>
        </div>
      )}
    </section>
  );
}

function InfoTile({
  label,
  value,
  className = "",
}: {
  label: string;
  value: string;
  className?: string;
}) {
  return (
    <div className={`rounded-xl border border-white/8 bg-black/15 p-3 ${className}`}>
      <span className="block text-[10px] font-bold uppercase tracking-wider text-neutral-500">
        {label}
      </span>
      <strong className="mt-1 block text-xs leading-5 text-white">{value}</strong>
    </div>
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
