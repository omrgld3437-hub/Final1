export type AdminTab =
  | "overview"
  | "accounts"
  | "registrations"
  | "chats"
  | "server"
  | "popups"
  | "errors";

export interface AdminAccount {
  account_id: number;
  account_code: string | null;
  name: string;
  exchange: string;
  created_at: string | null;
  active_bots: number;
  total_bots: number;
  bots_balance_usd: number;
  spot_balance_usd: number;
  wallet_equity_usd?: number;
  spot_balance_status: string;
  binance_connected: boolean;
  binance_connection_label: string;
  total_usd: number;
  daily_pnl_usd: number;
  daily_pnl_pct: number;
  daily_wallet_pnl_usd: number | null;
  daily_wallet_pnl_pct: number | null;
  user_id: number | null;
  user_username: string | null;
  user_name: string | null;
  user_surname: string | null;
  user_phone: string | null;
  user_is_online: boolean;
  user_is_suspended: boolean | null;
  user_last_activity_at: string | null;
  user_last_login_at: string | null;
  user_last_logout_at: string | null;
  is_test_account: boolean;
  admin_isolated: boolean;
}

export interface AccountTotals {
  total_accounts: number;
  total_active_bots: number;
  total_bots_balance_usd: number;
  total_spot_balance_usd: number;
  total_wallet_equity_usd?: number;
  total_usd: number;
  last_update_ts: string | null;
}

export interface AccountsResponse {
  accounts: AdminAccount[];
  totals: AccountTotals;
  lite: boolean;
}

export interface CreateAccountPayload {
  name: string;
  phone: string;
  exchange: "BINANCE";
}

export interface CreateAccountResponse extends AdminAccount {
  username: string;
  generated_password: string;
}

export interface PasswordMutationResponse extends AdminMutationResponse {
  generated_password?: string;
}

export interface PendingRegistration {
  id: number;
  name: string;
  surname: string;
  phone: string;
  ip_address: string;
  created_at: string | null;
}

export interface PendingRegistrationsResponse {
  pending: PendingRegistration[];
  count: number;
}

export interface RegistrationMutationResponse {
  success: boolean;
  message: string;
  username?: string;
  temp_password?: string | null;
}

export interface AdminChat {
  user_id: number;
  name: string;
  surname: string;
  phone: string;
  account_id: number;
  account_code: string;
  thread_id: number | null;
  locked: boolean;
  ended: boolean;
  rating: number | null;
  avg_rating: number | null;
  last_message_at: string | null;
  unread_count: number;
  online: boolean;
}

export interface AdminChatsResponse {
  chats: AdminChat[];
}

export interface AdminChatMessage {
  id: number;
  sender_type: "admin" | "user";
  body: string;
  created_at: string | null;
  read_at: string | null;
}

export interface AdminChatMessagesResponse {
  thread_id: number | null;
  locked: boolean;
  ended: boolean;
  rating: number | null;
  messages: AdminChatMessage[];
  count: number;
}

export interface ServerStats {
  uptime_seconds: number;
  uptime_formatted: string;
  request_count: number;
  lockdown: boolean;
  memory_mb: number | null;
  memory_total_mb: number | null;
  cpu_percent: number | null;
  network_mbps_down: number | null;
  network_mbps_up: number | null;
  network_link_mbps: number | null;
  server_ip: string | null;
  server_cwd: string | null;
  psutil_available: boolean;
}

export interface AdminPopup {
  id: number;
  target: "first_login" | "normal_user";
  title_key: "info" | "warning" | "success" | "maintenance" | "announcement";
  message: string;
  valid_until: string;
  created_at: string;
  is_active: boolean;
  max_shows_per_user: number;
}

export interface PopupsResponse {
  popups: AdminPopup[];
}

export interface CreatePopupPayload {
  target: AdminPopup["target"];
  title_key: AdminPopup["title_key"];
  message: string;
  valid_until: string;
  max_shows_per_user: number;
}

export interface ErrorLog {
  id: number;
  source: string;
  message: string;
  detail: string | null;
  path: string | null;
  context: unknown;
  user_label: string | null;
  account_label: string | null;
  is_admin: boolean;
  created_at: string | null;
  occurrence_count: number;
  client_ip: string | null;
  user_agent: string | null;
  request_id: string | null;
}

export interface ErrorLogsResponse {
  errors: ErrorLog[];
}

export interface ErrorLogCountResponse {
  count: number;
  latest_id: number | null;
}

export interface AdminMutationResponse {
  success?: boolean;
  message?: string;
  deleted?: number;
  lockdown?: boolean;
  account_id?: number;
  message_id?: number;
  created_at?: string | null;
}

export interface ResourceState<T> {
  data: T | null;
  loading: boolean;
  error: string;
  updatedAt: Date | null;
}
