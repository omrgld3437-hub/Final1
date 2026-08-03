import type { Bot } from "../../types";
import { ApiError, apiFetch } from "../../lib/api";

export interface BotEngineListItem {
  bot_id: number;
  bot_code?: string;
  account_id: number;
  symbol: string;
  status: string;
  display_status?: string;
  initial_allocation_done?: boolean;
  health_alert_level?: string | null;
  health_alerts?: unknown[];
  config?: Record<string, unknown>;
  last_tick_at?: string | null;
  created_at?: string | null;
}

interface BotEngineListResponse {
  bots: BotEngineListItem[];
  request_id?: string;
}

interface BotEngineCreateResponse {
  bot_id: number;
  bot_code?: string;
  account_id: number;
  symbol: string;
  status: string;
  request_id?: string;
}

interface BotEngineMutationResponse {
  ok: boolean;
  bot_id: number;
  account_id?: number;
  bot_status?: string;
  command_id?: string | number;
  worker_alive?: boolean;
  message?: string;
  request_id?: string;
}

function accountQuery(accountId: number): string {
  return `account_id=${encodeURIComponent(String(accountId))}`;
}

function requireMutationSuccess(
  response: BotEngineMutationResponse,
  fallbackMessage: string,
): BotEngineMutationResponse {
  if (!response || response.ok !== true || !Number.isInteger(response.bot_id)) {
    throw new ApiError(fallbackMessage, {
      kind: "unknown",
      details: response,
    });
  }
  return response;
}

export async function listEngineBots(
  accountId: number,
): Promise<BotEngineListItem[]> {
  const response = await apiFetch<BotEngineListResponse>(
    `/api/bots-engine?${accountQuery(accountId)}&fast=1`,
    { dedupe: false },
  );
  if (!response || !Array.isArray(response.bots)) {
    throw new Error("Bot listesi sunucudan beklenen biçimde alınamadı.");
  }
  return response.bots.filter(
    (bot) => Number.isInteger(bot?.bot_id) && typeof bot?.symbol === "string",
  );
}

export async function createEngineBot(
  accountId: number,
  config: Record<string, unknown>,
): Promise<BotEngineCreateResponse> {
  const response = await apiFetch<BotEngineCreateResponse>("/api/bots-engine", {
    method: "POST",
    body: JSON.stringify({
      account_id: accountId,
      config_json: config,
    }),
  });
  if (
    !response ||
    !Number.isInteger(response.bot_id) ||
    response.account_id !== accountId
  ) {
    throw new ApiError("Bot oluşturma sonucu doğrulanamadı.", {
      kind: "unknown",
      details: response,
    });
  }
  return response;
}

export async function startEngineBot(
  accountId: number,
  botId: number,
): Promise<BotEngineMutationResponse> {
  const response = await apiFetch<BotEngineMutationResponse>(
    `/api/bots-engine/${botId}/start?${accountQuery(accountId)}`,
    { method: "POST" },
  );
  return requireMutationSuccess(response, "Bot başlatma yanıtı doğrulanamadı.");
}

export async function stopEngineBot(
  accountId: number,
  botId: number,
): Promise<BotEngineMutationResponse> {
  const response = await apiFetch<BotEngineMutationResponse>(
    `/api/bots-engine/${botId}/stop?${accountQuery(accountId)}`,
    { method: "POST" },
  );
  return requireMutationSuccess(response, "Bot durdurma yanıtı doğrulanamadı.");
}

export async function deleteEngineBot(
  accountId: number,
  botId: number,
  convertBaseToQuote = false,
): Promise<BotEngineMutationResponse> {
  const response = await apiFetch<BotEngineMutationResponse>(
    `/api/bots-engine/${botId}/delete?${accountQuery(accountId)}`,
    {
      method: "POST",
      body: JSON.stringify({ convert_base_to_quote: convertBaseToQuote }),
      timeoutMs: 45_000,
    },
  );
  return requireMutationSuccess(response, "Bot silme yanıtı doğrulanamadı.");
}

function numericConfigValue(
  config: Record<string, unknown> | undefined,
  keys: string[],
): number {
  for (const key of keys) {
    const raw = config?.[key];
    if (raw === null || raw === undefined || raw === "") continue;
    const value = Number(raw);
    if (Number.isFinite(value)) return value;
  }
  return 0;
}

export function botIdentity(bot: Pick<Bot, "id" | "bot_id">): number {
  return Number(bot.bot_id ?? bot.id);
}

export function mergeEngineBots(
  serverBots: BotEngineListItem[],
  currentBots: Bot[],
): Bot[] {
  const currentById = new Map(
    currentBots.map((bot) => [botIdentity(bot), bot] as const),
  );

  return serverBots.map((serverBot) => {
    const current = currentById.get(serverBot.bot_id);
    const budget = numericConfigValue(serverBot.config, [
      "initial_capital_usdt",
      "budget_usd",
      "bot_budget_usdt",
      "bot_budget_quote",
    ]);

    return {
      ...(current ?? {
        current_usd: budget,
        total_pnl_usd: 0,
        total_pnl_pct: 0,
        total_cycles_completed: 0,
      }),
      id: serverBot.bot_id,
      bot_id: serverBot.bot_id,
      symbol: serverBot.symbol,
      status: serverBot.status || "stopped",
      display_status: serverBot.display_status || serverBot.status || "stopped",
      budget_usd: budget || current?.budget_usd || 0,
      initial_usd: budget || current?.initial_usd,
      config: serverBot.config || current?.config,
      initial_allocation_done: serverBot.initial_allocation_done,
      health_alert_level:
        serverBot.health_alert_level === undefined
          ? current?.health_alert_level
          : serverBot.health_alert_level,
      health_alerts:
        serverBot.health_alerts === undefined
          ? current?.health_alerts
          : serverBot.health_alerts,
      last_tick_at: serverBot.last_tick_at,
      created_at: serverBot.created_at,
    };
  });
}
