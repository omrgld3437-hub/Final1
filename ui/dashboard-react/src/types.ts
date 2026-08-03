export interface WalletAsset {
  asset: string;
  free: number;
  locked: number;
  bot_locked: number;
  available?: number;
  available_usd?: number | null;
  bot_locked_usd?: number | null;
  total?: number;
  price_usd?: number | null;
  total_usd: number | null;
  [key: string]: unknown;
}

export interface WalletState {
  total_usd: number;
  free_usd: number;
  locked_usd: number;
  bot_locked_usd: number;
  available_usd: number;
  keys_configured?: boolean;
  is_test_account?: boolean;
  assets: WalletAsset[];
}

export interface Bot {
  id: number;
  bot_id?: number;
  symbol: string;
  status: string;
  display_status?: string;
  budget_usd: number;
  initial_usd?: number;
  current_usd: number;
  total_pnl_usd: number;
  total_pnl_pct: number;
  total_cycles_completed: number;
  cycle_id?: number;
  last_trade_at?: string;
  config?: Record<string, unknown>;
  initial_allocation_done?: boolean;
  health_alert_level?: string | null;
  health_alerts?: unknown[];
  last_tick_at?: string | null;
  created_at?: string | null;
}

export interface Trade {
  order_id: number;
  trade_id?: number;
  time: string;
  symbol: string;
  side: string;
  type?: string;
  executed_qty: number;
  qty?: number;
  avg_price: number;
  price?: number;
  quote_qty: number;
  commission: number;
  commission_asset: string;
  commission_usd: number;
  is_bot: boolean;
  fills_count?: number;
}

export interface LeaderboardItem {
  symbol: string;
  profit_pct: number;
  reference_price?: number;
  cycles_count?: number;
  running_since_iso?: string | null;
  dynamic_mode?: {
    enabled?: boolean;
    active?: boolean;
  } | null;
  params?: Record<string, unknown>;
}

export interface ChatMessage {
  id: number;
  sender_type: "user" | "admin";
  body: string;
  created_at: string;
  read_at?: string;
}

export interface ChatHistory {
  locked: boolean;
  ended: boolean;
  rating: number | null;
  messages: ChatMessage[];
}
