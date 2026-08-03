import { apiFetch } from "../../lib/api";

export interface BotDetail {
  bot_id: number;
  bot_code?: string | null;
  account_id: number;
  symbol: string;
  status: string;
  display_status?: string;
  initial_allocation_done?: boolean;
  first_buy_pending?: boolean;
  config?: Record<string, unknown>;
  state?: Record<string, unknown> | null;
  grid_points?: Record<string, unknown>[];
  profit_points?: Record<string, unknown>[];
  reference_display?: number | null;
  grid_meta?: Record<string, unknown>;
  current_price?: number | null;
  price_stale?: boolean;
  price_age_s?: number | null;
  price_source?: string | null;
  current_usd?: number | null;
  base_value_usd?: number | null;
  quote_balance_usd?: number | null;
  daily_pnl_usd?: number | null;
  daily_pnl_pct?: number | null;
  price_24h_change_pct?: number | null;
  started_at?: string | null;
  parite_pct?: number | null;
  bot_pct?: number | null;
  stale?: boolean;
  equity_unavailable?: boolean;
  dynamic_mode?: Record<string, unknown> | null;
  dual_pnl?: Record<string, unknown> | null;
  session_alpha_performance?: Record<string, unknown> | null;
  bot_alpha_performance?: Record<string, unknown> | null;
  real_performance_pct?: number | null;
  rebalancing_details?: Record<string, unknown>[];
  request_id?: string;
  [key: string]: unknown;
}

export interface BotLiveSnapshot {
  status: string;
  pnl_pct?: number | null;
  equity?: number | null;
  last_price?: number | null;
  last_tick_at?: number | string | null;
  last_error_code?: string | null;
  price_source?: string | null;
  price_stale?: boolean;
  price_age_s?: number | null;
  initial_capital?: number | null;
  daily_pnl_usd?: number | null;
  daily_pnl_pct?: number | null;
  daily_ref_usd?: number | null;
  base_balance?: number | null;
  quote_balance?: number | null;
  cycle_id?: number | null;
  cycle_opened_at?: string | null;
  first_buy_pending?: boolean;
  initial_allocation_done?: boolean;
  stale?: boolean;
  equity_unavailable?: boolean;
  [key: string]: unknown;
}

export interface BotHealthAlert {
  code?: string;
  message?: string;
  level?: string;
  severity?: string;
  [key: string]: unknown;
}

export interface BotHealth {
  ok: boolean;
  bot_id: number;
  status: string;
  alerts: BotHealthAlert[];
  last_tick_at?: number | null;
  tick_age_s?: number | null;
  tick_interval_s?: number | null;
  last_error_code?: string | null;
  connectivity_failure?: {
    error_code?: string;
    message?: string;
    source?: string;
  } | null;
  connectivity_ok?: boolean;
  health_ack_at?: string | number | null;
  engine_log_dismiss_before_id?: number | null;
  request_id?: string;
  [key: string]: unknown;
}

export interface BotGridData {
  grid_points: Record<string, unknown>[];
  profit_points: Record<string, unknown>[];
  reference_display?: number | null;
  meta?: Record<string, unknown>;
  symbol: string;
  current_price?: number | null;
  state?: {
    base_balance?: number | null;
    quote_balance?: number | null;
    mode?: string | null;
    cycle_id?: number | null;
    sell_history?: unknown[];
    buy_history?: unknown[];
    [key: string]: unknown;
  };
  config?: Record<string, unknown>;
  request_id?: string;
  [key: string]: unknown;
}

export interface BotCycles {
  cycles: number[];
  dca_cycles: number[];
  trb_cycles: number[];
  request_id?: string;
}

export interface BotTrade {
  id?: number | string;
  ts?: string | number | null;
  side?: string | null;
  qty?: number | null;
  price?: number | null;
  fee?: number | null;
  fee_amount?: number | null;
  fee_raw?: number | null;
  fee_usdt?: number | null;
  fee_asset?: string | null;
  symbol?: string | null;
  cycle_id?: number | null;
  reason?: string | null;
  [key: string]: unknown;
}

export interface BotTrades {
  trades: BotTrade[];
  cycle_summary?: Record<string, unknown> | null;
  cycle_type?: string;
  request_id?: string;
}

export interface BotPerformance {
  bot_id: number;
  account_id: number;
  pnl_usd: number;
  pnl_pct: number;
  real_performance_pct?: number | null;
  price_stale?: boolean;
  price_age_s?: number | null;
  data_quality?: "live" | "stale_snapshot" | string;
  balance_change_pct?: number | null;
  price_change_pct?: number | null;
  period: string;
  period_label?: string;
  trades_count: number;
  cycles_count: number;
  current_cycle_id: number;
  fees_usd: number;
  realized: number;
  total_usd: number;
  initial_usd: number;
  balance_start_usd?: number;
  balance_end_usd?: number;
  daily_gain_usd?: number | null;
  daily_gain_pct?: number | null;
  monthly_gain_usd?: number | null;
  monthly_gain_pct?: number | null;
  estimated_annual_return_pct_12m?: number | null;
  reference_price?: number | null;
  current_price?: number | null;
  cycle_pnl_last?: number | null;
  cycle_id_last?: number | null;
  dual_perf?: Record<string, unknown> | null;
  session_alpha_performance?: Record<string, unknown> | null;
  bot_alpha_performance?: Record<string, unknown> | null;
  request_id?: string;
  [key: string]: unknown;
}

export interface BotPerformancePoint {
  ts: number;
  bot_pct?: number | null;
  basket_pct?: number | null;
}

export interface BotPerformanceChart {
  range: string;
  bucket: string;
  series: BotPerformancePoint[];
  meta: {
    baseline_equity?: number | null;
    baseline_bot0?: number | null;
    baseline_parite0?: number | null;
    points: number;
  };
}

function botUrl(
  botId: number,
  accountId: number,
  suffix = "",
  extra: Record<string, string | number> = {},
): string {
  const params = new URLSearchParams({ account_id: String(accountId) });
  Object.entries(extra).forEach(([key, value]) => params.set(key, String(value)));
  return `/api/bots-engine/${botId}${suffix}?${params.toString()}`;
}

function get<T>(url: string, signal?: AbortSignal): Promise<T> {
  return apiFetch<T>(url, { dedupe: false, signal });
}

export function getBotDetail(
  botId: number,
  accountId: number,
  signal?: AbortSignal,
): Promise<BotDetail> {
  return get(botUrl(botId, accountId), signal);
}

export function getBotLive(
  botId: number,
  accountId: number,
  signal?: AbortSignal,
): Promise<BotLiveSnapshot> {
  return get(botUrl(botId, accountId, "/live"), signal);
}

export function getBotHealth(
  botId: number,
  accountId: number,
  signal?: AbortSignal,
): Promise<BotHealth> {
  return get<BotHealth>(botUrl(botId, accountId, "/health"), signal).then(
    (response) => ({
      ...response,
      alerts: Array.isArray(response?.alerts) ? response.alerts : [],
    }),
  );
}

export function getBotGrid(
  botId: number,
  accountId: number,
  signal?: AbortSignal,
): Promise<BotGridData> {
  return get<BotGridData>(
    botUrl(botId, accountId, "/grid-points"),
    signal,
  ).then((response) => ({
    ...response,
    grid_points: Array.isArray(response?.grid_points)
      ? response.grid_points
      : [],
    profit_points: Array.isArray(response?.profit_points)
      ? response.profit_points
      : [],
  }));
}

export function getBotCycles(
  botId: number,
  accountId: number,
  signal?: AbortSignal,
): Promise<BotCycles> {
  return get<BotCycles>(botUrl(botId, accountId, "/cycles"), signal).then(
    (response) => ({
      ...response,
      cycles: Array.isArray(response?.cycles) ? response.cycles : [],
      dca_cycles: Array.isArray(response?.dca_cycles)
        ? response.dca_cycles
        : [],
      trb_cycles: Array.isArray(response?.trb_cycles)
        ? response.trb_cycles
        : [],
    }),
  );
}

export function getBotTrades(
  botId: number,
  accountId: number,
  cycleId?: number,
  cycleType?: "dca" | "trb",
  signal?: AbortSignal,
): Promise<BotTrades> {
  return get<BotTrades>(
    botUrl(botId, accountId, "/trades", {
      limit: 100,
      ...(cycleId === undefined ? {} : { cycle_id: cycleId }),
      ...(cycleType ? { cycle_type: cycleType } : {}),
    }),
    signal,
  ).then((response) => ({
    ...response,
    trades: Array.isArray(response?.trades) ? response.trades : [],
  }));
}

export function getBotPerformance(
  botId: number,
  accountId: number,
  period: "all" | "day" | "week" | "month" = "all",
  signal?: AbortSignal,
): Promise<BotPerformance> {
  return get(
    botUrl(botId, accountId, "/performance", { period }),
    signal,
  );
}

export function getBotPerformanceChart(
  botId: number,
  accountId: number,
  range: "1h" | "4h" | "1d" | "7d" | "30d" = "7d",
  bucket: "1m" | "5m" | "1h" | "4h" | "1d" = "1h",
  signal?: AbortSignal,
): Promise<BotPerformanceChart> {
  return get<BotPerformanceChart>(
    botUrl(botId, accountId, "/perf-chart-data", {
      range,
      bucket,
    }),
    signal,
  ).then((response) => ({
    ...response,
    range: response?.range || range,
    bucket: response?.bucket || bucket,
    series: Array.isArray(response?.series) ? response.series : [],
    meta: {
      ...(response?.meta || {}),
      points: Number.isFinite(Number(response?.meta?.points))
        ? Number(response.meta.points)
        : Array.isArray(response?.series)
          ? response.series.length
          : 0,
    },
  }));
}
