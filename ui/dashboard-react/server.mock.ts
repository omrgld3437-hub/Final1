/**
 * Local mock API for React dashboard dev (`npm run mock-server`).
 * Simulates wallet, trades, bots, prices, chat — no FastAPI required.
 */
import express from "express";

const app = express();
app.use(express.json());

const PORT = Number(process.env.MOCK_PORT || 8000);

// ── In-memory state ──────────────────────────────────────────────────────────

const walletState = {
  total_usd: 12450.8,
  free_usd: 8120.5,
  locked_usd: 330.0,
  bot_locked_usd: 4000.0,
  available_usd: 4120.5,
  keys_configured: true,
  is_test_account: true,
  assets: [
    { asset: "USDT", free: 4120.5, locked: 330, bot_locked: 4000, total_usd: 8450.5 },
    { asset: "BTC", free: 0.045, locked: 0, bot_locked: 0, total_usd: 0 },
    { asset: "ETH", free: 1.2, locked: 0, bot_locked: 0, total_usd: 0 },
    { asset: "SOL", free: 12.5, locked: 0, bot_locked: 0, total_usd: 0 },
  ],
};

const BASE_PRICES: Record<string, number> = {
  BTCUSDT: 67250,
  ETHUSDT: 3450,
  SOLUSDT: 145.2,
  BNBUSDT: 580,
  XRPUSDT: 0.52,
  ADAUSDT: 0.45,
  DOGEUSDT: 0.12,
  AVAXUSDT: 35.5,
  DOTUSDT: 7.2,
  LINKUSDT: 14.8,
};

const tradesList: Record<string, unknown>[] = [
  {
    order_id: 1001,
    trade_id: 1001,
    time: new Date(Date.now() - 3600000).toISOString(),
    symbol: "BTCUSDT",
    side: "BUY",
    type: "MARKET",
    executed_qty: 0.01,
    avg_price: 66800,
    quote_qty: 668,
    commission: 0.67,
    commission_asset: "BNB",
    commission_usd: 0.67,
    is_bot: false,
    fills_count: 1,
  },
];

const botsList: Record<string, unknown>[] = [
  {
    bot_id: 101,
    id: 101,
    symbol: "BTCUSDT",
    status: "running",
    display_status: "running",
    initial_allocation_done: true,
    budget_usd: 2000,
    initial_usd: 2000,
    current_usd: 2042.5,
    total_pnl_usd: 42.5,
    total_pnl_pct: 2.13,
    total_cycles_completed: 14,
    cycle_id: 15,
    last_trade_at: new Date().toISOString(),
    config: { symbol: "BTCUSDT", budget_usd: 2000 },
  },
  {
    bot_id: 102,
    id: 102,
    symbol: "ETHUSDT",
    status: "stopped",
    display_status: "stopped",
    initial_allocation_done: false,
    budget_usd: 2000,
    initial_usd: 2000,
    current_usd: 2000,
    total_pnl_usd: 0,
    total_pnl_pct: 0,
    total_cycles_completed: 0,
    cycle_id: 1,
    last_trade_at: new Date().toISOString(),
    config: { symbol: "ETHUSDT", budget_usd: 2000 },
  },
];

const accountSettings = {
  account_name: "Ömer Altın",
  server_public_ip: "185.112.14.92",
  user_phone: "5321234567",
  isolate_from_admin: false,
};

const chatHistory = {
  locked: false,
  ended: false,
  rating: null as number | null,
  messages: [
    {
      id: 1,
      sender_type: "admin",
      body: "ayserose destek hattına hoş geldiniz. Size nasıl yardımcı olabiliriz?",
      created_at: new Date(Date.now() - 600000).toISOString(),
    },
  ],
};

const coinList = Object.keys(BASE_PRICES).map((symbol) => ({
  symbol,
  lastPrice: String(BASE_PRICES[symbol]),
  priceChangePercent: String((Math.random() - 0.5) * 6),
  volume: String(Math.floor(Math.random() * 50000 + 10000)),
}));

// ── Price simulation (micro-volatility) ──────────────────────────────────────

function getSimulatedPrices(): Record<string, { price: number; change24h: number }> {
  const now = Date.now() / 1000;
  const out: Record<string, { price: number; change24h: number }> = {};
  for (const [pair, base] of Object.entries(BASE_PRICES)) {
    const wave =
      Math.sin(now * 0.8 + base * 0.001) * 0.0012 +
      Math.sin(now * 2.4 + base * 0.0003) * 0.0006;
    const price = base * (1 + wave);
    const change24h = Math.sin(now * 0.05 + base) * 3.5;
    out[pair] = { price: parseFloat(price.toFixed(4)), change24h: parseFloat(change24h.toFixed(2)) };
  }
  return out;
}

// ── Shared wallet calculation (fixes snapshot vs wallet desync) ───────────────

function getCalculatedWallet() {
  const prices = getSimulatedPrices();
  let total_usd = 0;
  let free_usd = 0;
  let locked_usd = 0;

  const updatedAssets = walletState.assets.map((asset) => {
    const qty = asset.free + asset.locked + asset.bot_locked;
    if (asset.asset === "USDT") {
      const val = qty;
      total_usd += val;
      free_usd += asset.free;
      locked_usd += asset.locked;
      return { ...asset, total_usd: parseFloat(val.toFixed(2)) };
    }
    const pair = `${asset.asset}USDT`;
    const priceInfo = prices[pair];
    if (priceInfo) {
      const value = qty * priceInfo.price;
      total_usd += value;
      free_usd += asset.free * priceInfo.price;
      locked_usd += asset.locked * priceInfo.price;
      return { ...asset, total_usd: parseFloat(value.toFixed(2)) };
    }
    return asset;
  });

  return {
    ...walletState,
    total_usd: parseFloat(total_usd.toFixed(2)),
    free_usd: parseFloat(free_usd.toFixed(2)),
    locked_usd: parseFloat(locked_usd.toFixed(2)),
    assets: updatedAssets,
  };
}

// ── Bot micro-updates on each snapshot poll ──────────────────────────────────

function tickActiveBots() {
  for (const bot of botsList) {
    if (bot.status !== "running") continue;
    const jitter = (Math.random() - 0.5) * 0.001;
    const current = Number(bot.current_usd) || 0;
    const initial = Number(bot.initial_usd) || current;
    bot.current_usd = parseFloat((current * (1 + jitter)).toFixed(2));
    bot.total_pnl_usd = parseFloat((Number(bot.current_usd) - initial).toFixed(2));
    bot.total_pnl_pct = parseFloat(((Number(bot.total_pnl_usd) / initial) * 100).toFixed(2));
    if (Math.random() < 0.02) {
      bot.total_cycles_completed = Number(bot.total_cycles_completed || 0) + 1;
    }
    bot.last_trade_at = new Date().toISOString();
  }
}

// ── Trade execution helper ───────────────────────────────────────────────────

function baseAsset(symbol: string): string {
  return symbol.replace(/USDT$/, "");
}

function findAsset(asset: string) {
  return walletState.assets.find((a) => a.asset === asset);
}

function ensureAsset(asset: string) {
  let a = findAsset(asset);
  if (!a) {
    a = { asset, free: 0, locked: 0, bot_locked: 0, total_usd: 0 };
    walletState.assets.push(a);
  }
  return a;
}

function executeTrade(params: {
  symbol: string;
  side: string;
  type: string;
  price: number;
  quantity: number;
  total: number;
}) {
  const { symbol, side, type, price, quantity, total } = params;
  const base = baseAsset(symbol);
  const usdt = ensureAsset("USDT");
  const coin = ensureAsset(base);

  if (side === "BUY") {
    if (total > walletState.available_usd) {
      throw new Error("Insufficient available balance");
    }
    usdt.free -= total;
    walletState.free_usd -= total;
    walletState.available_usd -= total;
    coin.free += quantity;
  } else {
    if (quantity > coin.free) {
      throw new Error("Insufficient asset balance");
    }
    coin.free -= quantity;
    usdt.free += total;
    walletState.free_usd += total;
    walletState.available_usd += total;
  }

  const newTrade = {
    order_id: 2000 + tradesList.length + 1,
    trade_id: 2000 + tradesList.length + 1,
    time: new Date().toISOString(),
    symbol,
    side,
    type,
    executed_qty: quantity,
    avg_price: price,
    quote_qty: total,
    commission: parseFloat((total * 0.001).toFixed(4)),
    commission_asset: "BNB",
    commission_usd: parseFloat((total * 0.001).toFixed(2)),
    is_bot: false,
    fills_count: 1,
  };
  tradesList.unshift(newTrade);
  return { trade: newTrade, wallet: getCalculatedWallet() };
}

// ── Ticker (TRY + gold with live drift) ──────────────────────────────────────

function getTickerData() {
  const now = Date.now() / 1000;
  const usdtTry = 32.42 + Math.sin(now * 0.3) * 0.08;
  const gramGold = 2450.4 + Math.sin(now * 0.25) * 2.5;
  const prices = getSimulatedPrices();
  return {
    ts: new Date().toISOString(),
    USDTTRY: parseFloat(usdtTry.toFixed(4)),
    EURTRY: parseFloat((usdtTry * 1.08).toFixed(4)),
    GBPTRY: parseFloat((usdtTry * 1.27).toFixed(4)),
    BTCUSD: prices.BTCUSDT?.price ?? BASE_PRICES.BTCUSDT,
    ETHUSD: prices.ETHUSDT?.price ?? BASE_PRICES.ETHUSDT,
    GRAM_ALTIN_TRY: parseFloat(gramGold.toFixed(2)),
    ONS_ALTIN_USD: parseFloat((gramGold * 31.1034768 / usdtTry).toFixed(2)),
  };
}

// ── Routes ───────────────────────────────────────────────────────────────────

app.get("/api/dashboard/snapshot", (req, res) => {
  tickActiveBots();
  const prices = getSimulatedPrices();
  const currentWallet = getCalculatedWallet();
  const botsBalance = botsList.reduce((acc, b) => acc + Number(b.current_usd || 0), 0);

  res.json({
    ok: true,
    data: {
      server_ts: Date.now() / 1000,
      prices,
      wallet: currentWallet,
      bots: botsList,
      kpis: {
        account: {
          id: 9988,
          name: accountSettings.account_name,
          spot_balance_usd: currentWallet.total_usd,
          bots_balance_usd: botsBalance,
          daily_wallet_pnl_usd: 124.5,
          daily_wallet_pnl_pct: 0.82,
          daily_bot_pnl_usd: 42.1,
          daily_bot_pnl_pct: 1.15,
          total_bots: botsList.length,
          active_bots: botsList.filter((b) => b.status === "running").length,
        },
      },
    },
    meta: { server_ms: 1.2, payload_bytes: 0, stale: false },
  });
});

app.get("/api/binance/wallet", (_req, res) => {
  res.json(getCalculatedWallet());
});

app.get("/api/ticker", (_req, res) => {
  res.json(getTickerData());
});

app.get("/api/finance/trades", (_req, res) => {
  res.json({ trades: tradesList, total: tradesList.length });
});

app.post("/api/finance/trades/create", (req, res) => {
  const { symbol, side, type, price, quantity, total } = req.body || {};
  if (!symbol || !side || !quantity || !total) {
    return res.status(400).json({ error: "Missing trade values" });
  }
  try {
    const result = executeTrade({
      symbol,
      side: String(side).toUpperCase(),
      type: type || "MARKET",
      price: parseFloat(price),
      quantity: parseFloat(quantity),
      total: parseFloat(total),
    });
    return res.json({ success: true, ...result });
  } catch (e) {
    return res.status(400).json({ error: e instanceof Error ? e.message : "Trade failed" });
  }
});

app.post("/api/spot/order", (req, res) => {
  const { symbol, side, type, quantity, quote_order_qty, price } = req.body || {};
  const prices = getSimulatedPrices();
  const marketPrice = prices[symbol]?.price || BASE_PRICES[symbol] || 1;
  const orderType = String(type || "MARKET").toUpperCase();
  const orderSide = String(side || "BUY").toUpperCase();
  const limitPrice = orderType === "LIMIT" && price ? parseFloat(price) : marketPrice;
  const actualPrice = orderType === "LIMIT" ? limitPrice : marketPrice;

  let qty = quantity ? parseFloat(quantity) : 0;
  let total = 0;

  if (orderSide === "BUY" && quote_order_qty && orderType === "MARKET") {
    total = parseFloat(quote_order_qty);
    qty = total / actualPrice;
  } else if (qty > 0) {
    total = qty * actualPrice;
  } else {
    return res.status(400).json({ error: "Missing quantity or quote_order_qty" });
  }

  try {
    const result = executeTrade({
      symbol,
      side: orderSide,
      type: orderType,
      price: actualPrice,
      quantity: qty,
      total,
    });
    return res.json({
      success: true,
      order: { orderId: result.trade.order_id, symbol, side: orderSide, type: orderType },
      wallet: result.wallet,
      trade: result.trade,
    });
  } catch (e) {
    return res.status(400).json({
      error: "VALIDATION_ERROR",
      detail: e instanceof Error ? e.message : "Trade failed",
    });
  }
});

app.post("/api/bots/create", (req, res) => {
  let config: Record<string, unknown> = {};
  try {
    config =
      typeof req.body?.config_json === "string"
        ? JSON.parse(req.body.config_json)
        : req.body?.config_json || req.body || {};
  } catch {
    return res.status(400).json({ error: "Invalid config_json" });
  }

  const budget = Number(config.budget_usd) || 1000;
  if (budget > walletState.available_usd) {
    return res.status(400).json({ error: "Insufficient available balance" });
  }

  walletState.available_usd -= budget;
  walletState.free_usd -= budget;
  walletState.bot_locked_usd += budget;

  const usdt = ensureAsset("USDT");
  usdt.free -= budget;
  usdt.bot_locked += budget;

  const newBot = {
    bot_id: 100 + botsList.length + 1,
    id: 100 + botsList.length + 1,
    symbol: (config.symbol as string) || "BTCUSDT",
    status: "stopped",
    display_status: "stopped",
    initial_allocation_done: false,
    budget_usd: budget,
    initial_usd: budget,
    current_usd: budget,
    total_pnl_usd: 0,
    total_pnl_pct: 0,
    total_cycles_completed: 0,
    cycle_id: 1,
    last_trade_at: new Date().toISOString(),
    config,
  };

  botsList.push(newBot);
  res.json({ success: true, bot_id: newBot.bot_id });
});

app.get("/api/bots-engine", (_req, res) => {
  res.json({ bots: botsList });
});

app.post("/api/bots-engine/:id/:action", (req, res) => {
  const bot = botsList.find((b) => b.id === Number(req.params.id));
  if (!bot) return res.status(404).json({ error: "Bot not found" });
  if (req.params.action === "start") {
    bot.status = "running";
    bot.display_status = "running";
  } else {
    bot.status = "stopped";
    bot.display_status = "stopped";
  }
  res.json({ success: true });
});

app.get("/api/data/coin-list", (_req, res) => {
  res.json({ coins: coinList });
});

app.get("/api/accounts/:id/spot-favorites", (_req, res) => {
  res.json({ symbols: ["BTCUSDT", "ETHUSDT", "SOLUSDT"] });
});

app.get("/api/accounts/:id/settings", (_req, res) => {
  res.json({ ...accountSettings, success: true });
});

app.patch("/api/accounts/:id/settings", (req, res) => {
  Object.assign(accountSettings, req.body || {});
  res.json({ success: true });
});

app.get("/api/leaderboard/global/top", (_req, res) => {
  const prices = getSimulatedPrices();
  res.json({
    items: [
      {
        symbol: "BTCUSDT",
        profit_pct: 4.2,
        reference_price: prices.BTCUSDT?.price ?? BASE_PRICES.BTCUSDT,
        params: { symbol: "BTCUSDT", budget_usd: 2000, upCount: 2, downCount: 2 },
      },
      {
        symbol: "ETHUSDT",
        profit_pct: 3.1,
        reference_price: prices.ETHUSDT?.price ?? BASE_PRICES.ETHUSDT,
        params: { symbol: "ETHUSDT", budget_usd: 1500, upCount: 3, downCount: 2 },
      },
      {
        symbol: "SOLUSDT",
        profit_pct: 2.8,
        reference_price: prices.SOLUSDT?.price ?? BASE_PRICES.SOLUSDT,
        params: { symbol: "SOLUSDT", budget_usd: 1000, upCount: 2, downCount: 3 },
      },
    ],
  });
});

app.get("/api/auth/chat", (_req, res) => {
  res.json(chatHistory);
});

app.post("/api/auth/chat/send", (req, res) => {
  const { message } = req.body || {};
  if (!message) return res.status(400).json({ error: "Message is required" });

  chatHistory.messages.push({
    id: chatHistory.messages.length + 1,
    sender_type: "user",
    body: message,
    created_at: new Date().toISOString(),
    read_at: new Date().toISOString(),
  });

  let reply = "Sorunuz destek kuyruğuna iletildi. Detaylar inceleniyor.";
  const lower = String(message).toLowerCase();
  if (lower.includes("bakiye") || lower.includes("cüzdan")) {
    reply =
      "Cüzdan bakiyeleriniz anlık okunmaktadır. Gecikme varsa lütfen Ayarlar altından API anahtarınızı güncelleyin.";
  } else if (lower.includes("bot") || lower.includes("hata")) {
    reply =
      "Botlarımız Binance spot pazarında DCA kademelerini otomatik izler. Donma varsa limit emirlerini Binance üzerinden denetleyin.";
  }

  chatHistory.messages.push({
    id: chatHistory.messages.length + 1,
    sender_type: "admin",
    body: reply,
    created_at: new Date().toISOString(),
  });

  res.json(chatHistory);
});

app.post("/api/auth/chat/end", (req, res) => {
  chatHistory.ended = true;
  chatHistory.rating = req.body?.rating ?? null;
  res.json(chatHistory);
});

app.post("/api/auth/chat-reopen", (_req, res) => {
  chatHistory.ended = false;
  chatHistory.rating = null;
  res.json(chatHistory);
});

app.listen(PORT, () => {
  console.log(`Mock dashboard API listening on http://127.0.0.1:${PORT}`);
});
