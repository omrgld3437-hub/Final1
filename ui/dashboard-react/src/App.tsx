import React, { useState, useEffect, useCallback } from "react";
import { Bot, WalletState } from "./types";
import HomeTab from "./components/HomeTab";
import TradeTab from "./components/TradeTab";
import BotsTab from "./components/BotsTab";
import PortfolioTab from "./components/PortfolioTab";
import ContactTab from "./components/ContactTab";
import SettingsTab from "./components/SettingsTab";
import { useDashboard } from "./context/DashboardContext";
import { apiFetch } from "./lib/api";
import {
  LogOut,
  Coins,
  Search,
  Sliders,
  MessageSquare,
  Settings as SettingsIcon,
  Cpu,
} from "lucide-react";

const EMPTY_WALLET: WalletState = {
  total_usd: 0,
  free_usd: 0,
  locked_usd: 0,
  bot_locked_usd: 0,
  available_usd: 0,
  keys_configured: false,
  assets: [],
};

export default function App() {
  const { accountId, accountCode, displayName, logout } = useDashboard();
  const [activeTab, setActiveTab] = useState<
    "binance" | "trade" | "bots" | "finance" | "contact" | "settings"
  >("binance");
  const [bots, setBots] = useState<Bot[]>([]);
  const [wallet, setWallet] = useState<WalletState>(EMPTY_WALLET);
  const [prices, setPrices] = useState<Record<string, { price?: number }>>({});

  const [showTradeModal, setShowTradeModal] = useState(false);
  const [tradeSymbol, setTradeSymbol] = useState("BTCUSDT");
  const [tradeSide, setTradeSide] = useState<"BUY" | "SELL">("BUY");
  const [tradeType, setTradeType] = useState<"MARKET" | "LIMIT">("MARKET");
  const [tradeLimitPrice, setTradeLimitPrice] = useState("");
  const [tradeQuantity, setTradeQuantity] = useState("");
  const [tradeTotal, setTradeTotal] = useState("");
  const [tradeError, setTradeError] = useState("");
  const [tradeSubmitting, setTradeSubmitting] = useState(false);

  const applySnapshot = useCallback((body: { data?: unknown } | Record<string, unknown>) => {
    const data = (body as { data?: Record<string, unknown> }).data ?? (body as Record<string, unknown>);
    if (!data || typeof data !== "object") return;
    if (data.prices && typeof data.prices === "object") {
      setPrices(data.prices as Record<string, { price?: number }>);
    }
    if (data.wallet && typeof data.wallet === "object") {
      setWallet({ ...EMPTY_WALLET, ...(data.wallet as WalletState) });
    }
    if (Array.isArray(data.bots)) {
      setBots(data.bots as Bot[]);
    }
  }, []);

  useEffect(() => {
    if (!accountId) return;
    const fetchStatus = () => {
      apiFetch<{ data?: unknown }>(
        `/api/dashboard/snapshot?account_id=${accountId}&fields=prices,wallet,bots,kpis`
      )
        .then(applySnapshot)
        .catch(console.error);
    };
    fetchStatus();
    const interval = setInterval(fetchStatus, 1000);
    return () => clearInterval(interval);
  }, [accountId, applySnapshot]);

  const getTradePrice = useCallback(() => {
    if (tradeType === "LIMIT") {
      const lp = parseFloat(tradeLimitPrice);
      if (lp > 0) return lp;
    }
    return prices[tradeSymbol]?.price || 1;
  }, [tradeType, tradeLimitPrice, prices, tradeSymbol]);

  useEffect(() => {
    if (tradeType !== "LIMIT" || !showTradeModal) return;
    const q = parseFloat(tradeQuantity);
    if (!q || q <= 0) return;
    const p = getTradePrice();
    setTradeTotal((q * p).toFixed(2));
  }, [tradeLimitPrice, tradeType, showTradeModal, tradeQuantity, getTradePrice]);

  const handleApplyLeaderboard = () => {
    setActiveTab("bots");
  };

  const handleOpenTradeModal = (symbol: string, side: "BUY" | "SELL" = "BUY") => {
    setTradeSymbol(symbol);
    setTradeSide(side);
    setTradeType("MARKET");
    setTradeLimitPrice("");
    setTradeQuantity("");
    setTradeTotal("");
    setTradeError("");
    setShowTradeModal(true);
  };

  const handleExecuteTrade = async () => {
    const qty = parseFloat(tradeQuantity);
    const total = parseFloat(tradeTotal);
    const actualPrice = getTradePrice();
    const limitPrice = tradeType === "LIMIT" ? parseFloat(tradeLimitPrice) : undefined;

    if (tradeType === "MARKET" && tradeSide === "BUY") {
      if (!total || total <= 0) {
        setTradeError("Lütfen geçerli bir tutar giriniz.");
        return;
      }
      if (total > wallet.available_usd) {
        setTradeError("Yetersiz bakiye.");
        return;
      }
    } else if (!qty || qty <= 0) {
      setTradeError("Lütfen geçerli bir miktar giriniz.");
      return;
    }

    if (tradeType === "LIMIT" && (!limitPrice || limitPrice <= 0)) {
      setTradeError("Limit fiyat giriniz.");
      return;
    }

    if (tradeType === "LIMIT" && tradeSide === "BUY") {
      const computedTotal = qty * actualPrice;
      if (computedTotal > wallet.available_usd) {
        setTradeError("Yetersiz bakiye. Limit fiyatına göre tutar kullanılabilir bakiyenizi aşıyor.");
        return;
      }
    }

    setTradeSubmitting(true);
    setTradeError("");
    try {
      const data = await apiFetch<{ success?: boolean; wallet?: WalletState }>("/api/spot/order", {
        method: "POST",
        body: JSON.stringify({
          account_id: accountId,
          symbol: tradeSymbol,
          side: tradeSide,
          type: tradeType,
          quantity:
            tradeType === "LIMIT" || tradeSide === "SELL"
              ? qty
              : null,
          quote_order_qty:
            tradeType === "MARKET" && tradeSide === "BUY" ? total : null,
          price: tradeType === "LIMIT" ? limitPrice : null,
        }),
      });
      if (data?.wallet) {
        setWallet({ ...EMPTY_WALLET, ...data.wallet });
      }
      setShowTradeModal(false);
    } catch (e) {
      setTradeError(e instanceof Error ? e.message : "Emir gönderilemedi.");
    } finally {
      setTradeSubmitting(false);
    }
  };

  const idLabel = accountCode || String(accountId);

  return (
    <div className="min-h-screen bg-[#14151a] text-neutral-200 font-sans selection:bg-[#f0b90b] selection:text-neutral-900">
      <div className="bg-[#1e2026] border-b border-neutral-800/80 sticky top-0 z-30 shadow-md">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex justify-between items-center">
          <div className="flex items-center space-x-3">
            <div className="w-9 h-9 rounded-lg bg-[#f0b90b] flex items-center justify-center font-bold text-neutral-900 text-lg shadow-md">
              TT
            </div>
            <div>
              <span className="font-extrabold text-white text-base tracking-wide flex items-center gap-1.5">
                <span className="ar-ayse">ayse</span><span className="ar-rose">rose</span>{" "}
                <span className="text-[10px] text-[#f0b90b] bg-[#f0b90b]/10 border border-[#f0b90b]/25 px-1.5 py-0.5 rounded uppercase font-bold tracking-widest hidden sm:inline">
                  Bot
                </span>
              </span>
              <p className="text-[10px] text-neutral-400">Ömer Altın Kuruluşu</p>
            </div>
          </div>

          <div className="flex items-center space-x-4">
            <div className="flex items-center space-x-2 text-right">
              <span className="text-sm font-bold text-white block">{displayName}</span>
              <span className="text-[10px] text-neutral-400 block font-mono">ID: {idLabel}</span>
            </div>
            <button
              onClick={logout}
              className="w-8 h-8 rounded-lg bg-neutral-800 hover:bg-neutral-700/80 border border-neutral-700/60 text-neutral-300 flex items-center justify-center hover:text-white transition"
              title="Çıkış Yap"
            >
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>

      <div className="border-b border-neutral-800 bg-[#16181d]">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-start sm:justify-center overflow-x-auto space-x-2 py-3 scrollbar-none">
            {(
              [
                ["binance", Coins, "Anasayfa"],
                ["trade", Search, "Hızlı İşlem (Trade)"],
                ["bots", Cpu, "Botlar"],
                ["finance", Sliders, "Portföy"],
                ["contact", MessageSquare, "İletişim Panel"],
                ["settings", SettingsIcon, "Ayarlar"],
              ] as const
            ).map(([tab, Icon, label]) => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`flex items-center space-x-2 px-4 py-2.5 rounded-lg text-sm font-semibold tracking-wide transition whitespace-nowrap ${
                  activeTab === tab
                    ? "bg-[#f0b90b] text-neutral-950 font-bold shadow-md"
                    : "text-neutral-400 hover:text-white hover:bg-neutral-800/40"
                }`}
              >
                <Icon className="w-4 h-4" />
                <span>{label}</span>
              </button>
            ))}
          </div>
        </div>
      </div>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {activeTab === "binance" && (
          <HomeTab
            bots={bots}
            wallet={wallet}
            prices={prices}
            setBots={setBots}
            onOpenTradeModal={handleOpenTradeModal}
            onApplyLeaderboard={handleApplyLeaderboard}
            isTestAccount={!!wallet.is_test_account}
          />
        )}
        {activeTab === "trade" && (
          <TradeTab prices={prices} onOpenTradeModal={handleOpenTradeModal} />
        )}
        {activeTab === "bots" && (
          <BotsTab bots={bots} setBots={setBots} availableUSDT={wallet.available_usd} />
        )}
        {activeTab === "finance" && <PortfolioTab />}
        {activeTab === "contact" && <ContactTab />}
        {activeTab === "settings" && <SettingsTab onLogout={logout} />}
      </main>

      {showTradeModal && (
        <div className="fixed inset-0 bg-black/85 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-neutral-900 border border-neutral-800 rounded-2xl max-w-md w-full p-6 space-y-4 shadow-2xl relative">
            <button
              onClick={() => setShowTradeModal(false)}
              className="absolute right-4 top-4 text-neutral-400 hover:text-white font-bold"
            >
              ✕
            </button>
            <h3 className="text-lg font-bold text-white mb-2">
              Spot Alım / Satım: {tradeSymbol.replace("USDT", "")}
            </h3>
            {tradeError && (
              <p className="text-sm text-[#f6465d] bg-[#f6465d]/10 border border-[#f6465d]/30 rounded-lg px-3 py-2">
                {tradeError}
              </p>
            )}
            <div className="flex gap-2 bg-[#1e2026] p-1 rounded-xl border border-neutral-800">
              {(["BUY", "SELL"] as const).map((side) => (
                <button
                  key={side}
                  onClick={() => setTradeSide(side)}
                  className={`flex-1 py-2 rounded-lg text-xs font-bold transition ${
                    tradeSide === side
                      ? side === "BUY"
                        ? "bg-[#0ecb81] text-neutral-950"
                        : "bg-[#f6465d] text-neutral-950"
                      : "text-neutral-400"
                  }`}
                >
                  {side === "BUY" ? "Alış (Buy)" : "Satış (Sell)"}
                </button>
              ))}
            </div>
            <div className="space-y-4 text-sm text-neutral-300">
              <div className="grid grid-cols-2 gap-4">
                {(["MARKET", "LIMIT"] as const).map((type) => (
                  <button
                    key={type}
                    onClick={() => setTradeType(type)}
                    className={`py-2 rounded-lg text-xs font-bold border transition ${
                      tradeType === type
                        ? "border-[#f0b90b] text-[#f0b90b] bg-[#f0b90b]/5"
                        : "border-neutral-800 text-neutral-400"
                    }`}
                  >
                    {type === "MARKET" ? "Market" : "Limit"}
                  </button>
                ))}
              </div>
              {tradeType === "LIMIT" && (
                <div className="space-y-1">
                  <label className="text-xs text-neutral-400 font-semibold">Tetik Fiyatı (USDT)</label>
                  <input
                    type="number"
                    value={tradeLimitPrice}
                    onChange={(e) => setTradeLimitPrice(e.target.value)}
                    className="w-full bg-[#1e2026] text-white border border-neutral-800 rounded-lg p-2.5 text-sm"
                    placeholder={String(prices[tradeSymbol]?.price || "")}
                  />
                </div>
              )}
              <div className="space-y-1">
                <label className="text-xs text-neutral-400 font-semibold">Miktar</label>
                <input
                  type="number"
                  value={tradeQuantity}
                  onChange={(e) => {
                    const q = parseFloat(e.target.value) || 0;
                    const p = getTradePrice();
                    setTradeQuantity(e.target.value);
                    setTradeTotal((q * p).toFixed(2));
                  }}
                  className="w-full bg-[#1e2026] text-white border border-neutral-800 rounded-lg p-2.5 text-sm"
                  placeholder="0.00"
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs text-neutral-400 font-semibold">Toplam Tutar (USDT)</label>
                <input
                  type="number"
                  value={tradeTotal}
                  onChange={(e) => {
                    const totalVal = parseFloat(e.target.value) || 0;
                    const p = getTradePrice();
                    setTradeTotal(e.target.value);
                    setTradeQuantity((totalVal / p).toFixed(5));
                  }}
                  className="w-full bg-[#1e2026] text-white border border-neutral-800 rounded-lg p-2.5 text-sm"
                  placeholder="0.00"
                />
              </div>
            </div>
            <button
              onClick={handleExecuteTrade}
              disabled={tradeSubmitting}
              className={`w-full py-3 rounded-xl font-bold transition text-sm text-neutral-950 disabled:opacity-60 ${
                tradeSide === "BUY" ? "bg-[#0ecb81] hover:bg-[#0ca86a]" : "bg-[#f6465d] hover:bg-[#d63a4e]"
              }`}
            >
              {tradeSubmitting ? "Gönderiliyor…" : `Onayla & ${tradeSide === "BUY" ? "Al" : "Sat"}`}
            </button>
          </div>
        </div>
      )}

      <footer className="bg-[#14151a] border-t border-neutral-900 py-12 text-center text-xs text-neutral-500">
        <div className="max-w-7xl mx-auto px-4 space-y-4">
          <p className="font-semibold text-neutral-400">
            <span className="ar-ayse">ayse</span><span className="ar-rose">rose</span> Ömer Altın Kuruluşudur. Tüm Hakları Saklıdır © 2026
          </p>
        </div>
      </footer>
    </div>
  );
}
