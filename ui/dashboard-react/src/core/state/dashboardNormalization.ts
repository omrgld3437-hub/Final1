import type { Bot, WalletAsset, WalletState } from "../../types";

type UnknownRecord = Record<string, unknown>;

function isRecord(value: unknown): value is UnknownRecord {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function finiteNumber(value: unknown, fallback: number): number {
  if (value === null || value === undefined || value === "") return fallback;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function finiteNumberOrNull(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function normalizeAsset(value: unknown): WalletAsset | null {
  if (!isRecord(value)) return null;
  const asset = String(value.asset ?? "").trim().toUpperCase();
  if (!asset) return null;

  const free = finiteNumber(value.free, 0);
  const locked = finiteNumber(value.locked, 0);
  const botLocked = finiteNumber(value.bot_locked, 0);
  const priceUsd = finiteNumberOrNull(value.price_usd);
  const explicitTotal = finiteNumberOrNull(value.total_usd ?? value.value_usd);
  const totalQuantity = finiteNumber(value.total, free + locked + botLocked);
  const calculatedTotal =
    explicitTotal ?? (priceUsd == null ? null : totalQuantity * priceUsd);

  return {
    ...value,
    asset,
    free,
    locked,
    bot_locked: botLocked,
    total: totalQuantity,
    price_usd: priceUsd,
    total_usd: calculatedTotal,
  };
}

export function normalizeWallet(
  value: unknown,
  current: WalletState,
): WalletState {
  if (!isRecord(value)) return current;
  const rawAssets = Array.isArray(value.assets) ? value.assets : null;
  const normalizedAssets = rawAssets
    ?.map(normalizeAsset)
    .filter((asset): asset is WalletAsset => asset !== null);

  return {
    ...current,
    ...value,
    total_usd: finiteNumber(value.total_usd, current.total_usd),
    free_usd: finiteNumber(value.free_usd, current.free_usd),
    locked_usd: finiteNumber(value.locked_usd, current.locked_usd),
    bot_locked_usd: finiteNumber(
      value.bot_locked_usd,
      current.bot_locked_usd,
    ),
    available_usd: finiteNumber(
      value.available_usd,
      current.available_usd,
    ),
    keys_configured:
      typeof value.keys_configured === "boolean"
        ? value.keys_configured
        : current.keys_configured,
    is_test_account:
      typeof value.is_test_account === "boolean"
        ? value.is_test_account
        : current.is_test_account,
    assets: normalizedAssets ?? current.assets,
  };
}

export function normalizeBots(value: unknown): Bot[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (!isRecord(item)) return [];
    const id = finiteNumber(item.bot_id ?? item.id, 0);
    const symbol = String(item.symbol ?? "").trim().toUpperCase();
    if (!id || !symbol) return [];
    return [
      {
        ...item,
        id,
        bot_id: finiteNumber(item.bot_id, id),
        symbol,
        status: String(item.status ?? item.display_status ?? "stopped"),
        display_status:
          item.display_status == null
            ? undefined
            : String(item.display_status),
        budget_usd: finiteNumber(
          item.budget_usd ?? item.initial_usd ?? item.initial_capital_usdt,
          0,
        ),
        initial_usd: finiteNumber(
          item.initial_usd ?? item.budget_usd ?? item.initial_capital_usdt,
          0,
        ),
        current_usd: finiteNumber(
          item.current_usd ?? item.equity_usd ?? item.budget_usd,
          0,
        ),
        total_pnl_usd: finiteNumber(
          item.total_pnl_usd ?? item.pnl_usd,
          0,
        ),
        total_pnl_pct: finiteNumber(
          item.total_pnl_pct ?? item.pnl_pct,
          0,
        ),
        total_cycles_completed: finiteNumber(
          item.total_cycles_completed ?? item.completed_cycles,
          0,
        ),
      } satisfies Bot,
    ];
  });
}

export function normalizePrices(
  value: unknown,
  current: Record<string, { price?: number; change24h?: number; volume24h?: number }>,
  partial: boolean,
): Record<string, { price?: number; change24h?: number; volume24h?: number }> {
  if (!isRecord(value)) return current;
  const normalized: Record<string, { price?: number; change24h?: number; volume24h?: number }> =
    partial ? { ...current } : {};

  for (const [rawSymbol, rawQuote] of Object.entries(value)) {
    const symbol = rawSymbol.trim().toUpperCase();
    if (!symbol) continue;
    const previous = current[symbol] ?? {};
    const quote = isRecord(rawQuote) ? rawQuote : { price: rawQuote };
    const price = finiteNumberOrNull(
      quote.price ?? quote.last_price ?? quote.lastPrice,
    );
    const change24h = finiteNumberOrNull(
      quote.change24h ??
        quote.change_24h ??
        quote.price_change_percent ??
        quote.priceChangePercent,
    );
    const volume24h = finiteNumberOrNull(
      quote.volume24h ?? quote.volume_24h ?? quote.volume,
    );
    if (price == null && change24h == null && volume24h == null && !previous.price) continue;
    normalized[symbol] = {
      ...(partial ? previous : {}),
      ...(price == null ? {} : { price }),
      ...(change24h == null ? {} : { change24h }),
      ...(volume24h == null ? {} : { volume24h }),
    };
  }

  return normalized;
}
