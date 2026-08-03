import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import {
  normalizeBots,
  normalizePrices,
  normalizeWallet,
} from "../src/core/state/dashboardNormalization.ts";
import type { WalletState } from "../src/types.ts";

const emptyWallet: WalletState = {
  total_usd: 0,
  free_usd: 0,
  locked_usd: 0,
  bot_locked_usd: 0,
  available_usd: 0,
  keys_configured: false,
  assets: [],
};

const wallet = normalizeWallet(
  {
    total_usd: "10000.50",
    available_usd: "8000",
    assets: [
      {
        asset: "eth",
        free: "0",
        locked: null,
        bot_locked: "0.25",
        total: "0.25",
      },
      {
        asset: "btc",
        free: "0.01",
        locked: "0",
        bot_locked: "0",
        price_usd: "80000",
      },
    ],
  },
  emptyWallet,
);

assert.equal(wallet.total_usd, 10000.5);
assert.equal(wallet.assets[0].asset, "ETH");
assert.equal(wallet.assets[0].total_usd, null);
assert.equal(wallet.assets[1].total_usd, 800);

const bots = normalizeBots([
  {
    bot_id: "7",
    symbol: "btcusdt",
    status: "running",
    budget_usd: "250",
    current_usd: null,
    pnl_usd: "3.5",
  },
]);
assert.equal(bots[0].id, 7);
assert.equal(bots[0].current_usd, 250);
assert.equal(bots[0].total_pnl_usd, 3.5);

const prices = normalizePrices(
  {
    btcusdt: { price: "80000.25", priceChangePercent: "-1.25" },
    invalid: {},
  },
  {},
  false,
);
assert.deepEqual(prices.BTCUSDT, { price: 80000.25, change24h: -1.25 });
assert.equal(prices.INVALID, undefined);

const providerSource = readFileSync(
  resolve(import.meta.dirname, "../src/core/state/DashboardDataContext.tsx"),
  "utf8",
);
const transportSource = readFileSync(
  resolve(import.meta.dirname, "../src/core/realtime/dashboardTransport.ts"),
  "utf8",
);
assert.match(
  providerSource,
  /useState<Bot\[\]>\(\(\) => readCachedBots\(accountId\)\)/,
);
assert.match(providerSource, /writeCachedBots\(accountId, nextBots\)/);
assert.match(transportSource, /const FIELDS = "prices,wallet,bots"/);

console.log("Dashboard data normalization contracts: OK");
