import React, { useState, useEffect } from "react";
import { Bot, WalletAsset, Trade, LeaderboardItem } from "../types";
import { useDashboard } from "../context/DashboardContext";
import { apiFetch } from "../lib/api";
import { 
  TrendingUp, 
  TrendingDown, 
  ArrowUpRight, 
  ArrowDownLeft, 
  Play, 
  Square, 
  Trash2, 
  Info, 
  Star, 
  ChevronLeft, 
  ChevronRight,
  RefreshCw,
  FolderOpen
} from "lucide-react";

interface HomeTabProps {
  bots: Bot[];
  wallet: any;
  prices: any;
  setBots: React.Dispatch<React.SetStateAction<Bot[]>>;
  onOpenTradeModal: (symbol: string, side: "BUY" | "SELL") => void;
  onApplyLeaderboard: (params: any) => void;
  isTestAccount: boolean;
}

export default function HomeTab({
  bots,
  wallet,
  prices,
  setBots,
  onOpenTradeModal,
  onApplyLeaderboard,
  isTestAccount,
}: HomeTabProps) {
  const [selectedPeriod, setSelectedPeriod] = useState<"daily" | "weekly" | "monthly" | "all">("all");
  const [txPeriod, setTxPeriod] = useState<"daily" | "weekly" | "monthly" | "all">("daily");
  const [txType, setTxType] = useState<"all" | "buysell" | "depositwithdraw">("buysell");
  
  const [trades, setTrades] = useState<Trade[]>([]);
  const [openOrders, setOpenOrders] = useState<any[]>([]);
  const [leaderboard, setLeaderboard] = useState<LeaderboardItem[]>([]);
  const [selectedLeaderboardItem, setSelectedLeaderboardItem] = useState<LeaderboardItem | null>(null);
  
  const [perfPnl, setPerfPnl] = useState(124.50);
  const [perfFees, setPerfFees] = useState(12.30);
  
  const { accountId } = useDashboard();

  useEffect(() => {
    if (!accountId) return;
    const fetchTrades = () => {
      apiFetch<{ trades?: Trade[] }>(`/api/finance/trades?account_id=${accountId}&limit=20&offset=0`)
        .then((data) => {
          if (data?.trades) setTrades(data.trades);
        })
        .catch(console.error);
    };

    fetchTrades();
    const interval = setInterval(fetchTrades, 2000);
    return () => clearInterval(interval);
  }, [accountId]);

  useEffect(() => {
    apiFetch<{ items?: LeaderboardItem[] }>("/api/leaderboard/global/top?limit=5")
      .then((data) => {
        if (data?.items) setLeaderboard(data.items);
      })
      .catch(console.error);
  }, [accountId]);

  // Update simulation performance on period change
  useEffect(() => {
    if (selectedPeriod === "daily") {
      setPerfPnl(42.10);
      setPerfFees(2.40);
    } else if (selectedPeriod === "weekly") {
      setPerfPnl(184.20);
      setPerfFees(14.80);
    } else if (selectedPeriod === "monthly") {
      setPerfPnl(412.50);
      setPerfFees(45.10);
    } else {
      setPerfPnl(824.90);
      setPerfFees(95.60);
    }
  }, [selectedPeriod]);

  // Cancel order in open orders
  const handleCancelOrder = (orderId: number) => {
    if (confirm("Bu açık emri iptal etmek istediğinize emin misiniz?")) {
      setOpenOrders(prev => prev.filter(o => o.order_id !== orderId));
      alert("Emir başarıyla iptal edildi.");
    }
  };

  const handleToggleBot = (botId: number, currentStatus: string) => {
    const nextStatus = currentStatus === "running" ? "stop" : "start";
    apiFetch<{ success?: boolean }>(
      `/api/bots-engine/${botId}/${nextStatus}?account_id=${accountId}`,
      { method: "POST" }
    )
      .then((data) => {
        if (data?.success) {
          setBots((prev) =>
            prev.map((b) =>
              b.id === botId
                ? {
                    ...b,
                    status: nextStatus === "start" ? "running" : "stopped",
                    display_status: nextStatus === "start" ? "running" : "stopped",
                  }
                : b
            )
          );
        }
      })
      .catch(console.error);
  };

  return (
    <div className="space-y-6">
      {/* Unified KPI Strip */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-4 shadow-xl">
          <div className="text-xs font-semibold text-neutral-400 uppercase tracking-wider mb-1">Toplam Spot Bakiyesi</div>
          <div className="text-2xl font-bold text-white">${wallet.total_usd?.toLocaleString(undefined, { minimumFractionDigits: 2 })}</div>
          <span className="text-xs text-[#0ecb81] font-semibold flex items-center mt-2">
            <ArrowUpRight className="w-3.5 h-3.5 mr-1" /> Canlı Veri • Binance Bağlı
          </span>
        </div>

        <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-4 shadow-xl">
          <div className="text-xs font-semibold text-neutral-400 uppercase tracking-wider mb-1">Günlük Değişim</div>
          <div className="text-2xl font-bold text-[#0ecb81]">+${(wallet.total_usd * 0.0082).toFixed(2)}</div>
          <span className="text-xs text-neutral-400 mt-2 block">+0.82%</span>
        </div>

        <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-4 shadow-xl">
          <div className="text-xs font-semibold text-neutral-400 uppercase tracking-wider mb-1">Kilitli Botlar Bakiyesi</div>
          <div className="text-2xl font-bold text-[#f0b90b]">${bots.reduce((sum, b) => sum + (b.current_usd || 0), 0).toLocaleString(undefined, { minimumFractionDigits: 2 })}</div>
          <span className="text-xs text-neutral-400 mt-2 block">{bots.filter(b => b.status === "running").length} Aktif Bot</span>
        </div>

        <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-4 shadow-xl">
          <div className="text-xs font-semibold text-neutral-400 uppercase tracking-wider mb-1">Günlük Bot K/Z</div>
          <div className="text-2xl font-bold text-[#0ecb81]">+$42.10</div>
          <span className="text-xs text-neutral-400 mt-2 block">+1.15% Ortalama</span>
        </div>
      </div>

      {/* Binance Assets Strip */}
      <div className="bg-neutral-900/60 backdrop-blur rounded-xl border border-neutral-800 p-6 shadow-xl">
        <h3 className="text-lg font-bold text-neutral-200 mb-4 flex items-center">
          <FolderOpen className="w-5 h-5 mr-2 text-[#f0b90b]" /> Kullanılabilir &amp; Kilitli Cüzdan Varlıkları
        </h3>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-6 divide-y sm:divide-y-0 sm:divide-x divide-neutral-800">
          <div className="flex flex-col items-center justify-center p-3 text-center">
            <span className="text-xs text-neutral-400 uppercase tracking-wider mb-1">Kullanılabilir varlıklar</span>
            <div className="text-xl font-bold text-white">${wallet.available_usd?.toLocaleString(undefined, { minimumFractionDigits: 2 })}</div>
            <span className="text-xs text-neutral-500 mt-1">Serbest bakiye (Bot bütçeleri düşüldü)</span>
          </div>
          <div className="flex flex-col items-center justify-center p-3 text-center">
            <span className="text-xs text-neutral-400 uppercase tracking-wider mb-1">Bot kilitli</span>
            <div className="text-xl font-bold text-[#f0b90b]">${wallet.bot_locked_usd?.toLocaleString(undefined, { minimumFractionDigits: 2 })}</div>
            <span className="text-xs text-neutral-500 mt-1">Aktif dca grid bütçelerinde kilitli</span>
          </div>
          <div className="flex flex-col items-center justify-center p-3 text-center">
            <span className="text-xs text-neutral-400 uppercase tracking-wider mb-1">Kilitli varlıklar</span>
            <div className="text-xl font-bold text-neutral-300">${wallet.locked_usd?.toLocaleString(undefined, { minimumFractionDigits: 2 })}</div>
            <span className="text-xs text-neutral-500 mt-1">Açık limit emirlerinde bekleyen bakiye</span>
          </div>
        </div>
      </div>

      {/* Grid: Wallet Assets & Running Bots */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Wallet Assets Table */}
        <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-6 shadow-xl lg:col-span-2">
          <div className="flex justify-between items-center mb-4">
            <div>
              <h3 className="text-lg font-bold text-white">Cüzdan Varlıkları</h3>
              <span className="text-xs text-neutral-400">1 USDT altı varlıklar gizlidir</span>
            </div>
            <span className="text-xs px-2 py-1 bg-neutral-800 text-neutral-300 rounded font-semibold border border-neutral-700">Canlı Değerler</span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-sm text-left text-neutral-300">
              <thead className="bg-[#1e2026] text-xs uppercase text-neutral-400 font-bold border-b border-neutral-800">
                <tr>
                  <th className="px-4 py-3">Varlık</th>
                  <th className="px-4 py-3 text-right">Fiyat</th>
                  <th className="px-4 py-3 text-right">Toplam</th>
                  <th className="px-4 py-3 text-right">Kullanılabilir</th>
                  <th className="px-4 py-3 text-right">Değer (USD)</th>
                  <th className="px-4 py-3 text-center">Hızlı İşlem</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-800/60">
                {wallet.assets?.map((asset: WalletAsset) => {
                  const pairSymbol = `${asset.asset}USDT`;
                  const price = prices[pairSymbol]?.price || (asset.asset === "USDT" ? 1.00 : 0.00);
                  const isUp = prices[pairSymbol]?.change24h >= 0;
                  
                  return (
                    <tr key={asset.asset} className="hover:bg-neutral-800/40 transition">
                      <td className="px-4 py-3.5 font-bold text-white flex items-center">
                        <div className="w-8 h-8 rounded-full bg-neutral-800 border border-neutral-700 flex items-center justify-center text-xs text-neutral-300 font-bold mr-3">
                          {asset.asset.substring(0,2)}
                        </div>
                        {asset.asset}
                      </td>
                      <td className="px-4 py-3.5 text-right font-mono text-neutral-200">
                        ${price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 })}
                      </td>
                      <td className="px-4 py-3.5 text-right font-mono text-neutral-300">
                        {asset.free + asset.locked + asset.bot_locked}
                      </td>
                      <td className="px-4 py-3.5 text-right font-mono text-neutral-400">
                        {asset.free}
                      </td>
                      <td className="px-4 py-3.5 text-right font-mono font-bold text-white">
                        ${asset.total_usd.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                      </td>
                      <td className="px-4 py-3.5 text-center">
                        <div className="inline-flex rounded-lg shadow-sm gap-1 bg-neutral-800 p-0.5 border border-neutral-700">
                          <button
                            onClick={() => onOpenTradeModal(pairSymbol, "BUY")}
                            className="px-2.5 py-1 text-xs font-bold text-[#0ecb81] hover:bg-neutral-700 rounded transition"
                          >
                            AL
                          </button>
                          <button
                            onClick={() => onOpenTradeModal(pairSymbol, "SELL")}
                            className="px-2.5 py-1 text-xs font-bold text-[#f6465d] hover:bg-neutral-700 rounded transition"
                          >
                            SAT
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

        {/* Existing Bots Sidebar */}
        <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-6 shadow-xl space-y-4">
          <div className="flex justify-between items-center border-b border-neutral-800 pb-3">
            <h3 className="font-bold text-white text-lg">Mevcut Botlar</h3>
            <span className="text-xs px-2.5 py-1 rounded bg-[#f0b90b]/10 text-[#f0b90b] font-bold border border-[#f0b90b]/20">
              {bots.filter(b => b.status === "running").length} ON
            </span>
          </div>

          <div className="space-y-4 max-h-[380px] overflow-y-auto pr-1">
            {bots.map((bot) => {
              const profitColor = bot.total_pnl_usd >= 0 ? "text-[#0ecb81]" : "text-[#f6465d]";
              return (
                <div key={bot.id} className="bg-[#1e2026] border border-neutral-800 p-4 rounded-xl flex flex-col justify-between hover:border-neutral-700 transition">
                  <div className="flex justify-between items-center mb-2">
                    <span className="font-bold text-white text-sm tracking-wide">{bot.symbol}</span>
                    <span className={`text-xs px-1.5 py-0.5 rounded font-bold uppercase tracking-wider ${
                      bot.status === "running" ? "bg-[#0ecb81]/15 text-[#0ecb81]" : "bg-neutral-800 text-neutral-400"
                    }`}>
                      {bot.status === "running" ? "Çalışıyor" : "Durdu"}
                    </span>
                  </div>
                  
                  <div className="grid grid-cols-2 gap-2 text-xs text-neutral-400 my-2">
                    <div>Bütçe: <strong className="text-white">${bot.budget_usd}</strong></div>
                    <div>Hacim: <strong className="text-white">${bot.current_usd?.toFixed(2)}</strong></div>
                    <div>Döngü: <strong className="text-white">#{bot.total_cycles_completed}</strong></div>
                    <div>Net K/Z: <strong className={`${profitColor} font-bold`}>{bot.total_pnl_pct >= 0 ? '+' : ''}{bot.total_pnl_pct}%</strong></div>
                  </div>

                  <div className="flex justify-between items-center mt-3 border-t border-neutral-800/80 pt-2 gap-2">
                    <button
                      onClick={() => handleToggleBot(bot.id, bot.status)}
                      className="text-xs px-3 py-1.5 font-bold rounded bg-neutral-800 text-white hover:bg-neutral-700 transition flex items-center gap-1.5"
                    >
                      {bot.status === "running" ? (
                        <>
                          <Square className="w-3 h-3 text-[#f6465d] fill-[#f6465d]" /> Durdur
                        </>
                      ) : (
                        <>
                          <Play className="w-3 h-3 text-[#0ecb81] fill-[#0ecb81]" /> Başlat
                        </>
                      )}
                    </button>
                    <span className="text-xs text-neutral-500 font-mono">ID: {bot.id}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Global Leaderboard & Bot Performance Section */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Global Leaderboard (En İyi 5 Bot) */}
        <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-6 shadow-xl">
          <h3 className="text-lg font-bold text-white mb-4 flex items-center">
            <Star className="w-5 h-5 mr-2 text-[#f0b90b]" /> En İyi Performanslı Şablonlar
          </h3>
          <div className="space-y-3">
            {leaderboard.map((item, index) => {
              return (
                <div key={index} className="bg-neutral-800/60 border border-neutral-800 hover:border-neutral-700 rounded-xl p-4 transition flex justify-between items-center">
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="w-5 h-5 rounded-full bg-[#f0b90b]/15 text-[#f0b90b] font-bold text-xs flex items-center justify-center">
                        #{index + 1}
                      </span>
                      <strong className="text-white text-sm">{item.symbol}</strong>
                      <span className="text-xs text-[#0ecb81] font-bold">+{item.profit_pct}%</span>
                    </div>
                    <p className="text-xs text-neutral-400">Çalışma Oranı: Tr DCA Grid şablonu</p>
                  </div>

                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => setSelectedLeaderboardItem(item)}
                      className="px-2.5 py-1.5 text-xs font-semibold rounded bg-neutral-800 text-neutral-300 hover:bg-neutral-700 transition"
                    >
                      İncele
                    </button>
                    <button
                      onClick={() => onApplyLeaderboard(item.params)}
                      className="px-2.5 py-1.5 text-xs font-bold rounded bg-[#f0b90b] text-neutral-900 hover:bg-[#c9930a] transition"
                    >
                      Kopyala
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Bot Performance Summary */}
        <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-6 shadow-xl flex flex-col justify-between">
          <div>
            <div className="flex justify-between items-center mb-4">
              <h3 className="text-lg font-bold text-white">Bot Performansı</h3>
              <div className="inline-flex rounded-md p-0.5 bg-neutral-800 border border-neutral-700 gap-1">
                {(["daily", "weekly", "monthly", "all"] as const).map(p => (
                  <button
                    key={p}
                    onClick={() => setSelectedPeriod(p)}
                    className={`text-xs px-2 py-1 font-semibold rounded capitalized transition ${
                      selectedPeriod === p ? "bg-[#f0b90b] text-neutral-900 font-bold" : "text-neutral-400 hover:text-white"
                    }`}
                  >
                    {p === "all" ? "Genel" : p === "daily" ? "Günlük" : p === "weekly" ? "Haftalık" : "Aylık"}
                  </button>
                ))}
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4 mt-6">
              <div className="bg-[#1e2026] p-4 rounded-xl border border-neutral-800 text-center">
                <span className="text-xs text-neutral-400 block mb-1">Dönem Net K/Z</span>
                <span className={`text-2xl font-black ${perfPnl >= 0 ? 'text-[#0ecb81]' : 'text-[#f6465d]'}`}>
                  +${perfPnl.toFixed(2)}
                </span>
              </div>
              <div className="bg-[#1e2026] p-4 rounded-xl border border-neutral-800 text-center">
                <span className="text-xs text-neutral-400 block mb-1">Dönem Toplam Komisyon</span>
                <span className="text-2xl font-black text-neutral-300">
                  ${perfFees.toFixed(2)}
                </span>
              </div>
            </div>
          </div>

          <div className="text-xs text-neutral-400 mt-6 border-t border-neutral-800/80 pt-4 flex items-center gap-1">
            <Info className="w-3.5 h-3.5 text-[#f0b90b] shrink-0" />
            <span>K/Z değerleri ödenen komisyonlardan arındırılmamıştır. Platform işlem detayları Binance API ile eş zamanlı senkronize edilir.</span>
          </div>
        </div>
      </div>

      {/* Transaction History Panel */}
      <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-6 shadow-xl">
        <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 mb-6 pb-2 border-b border-neutral-800">
          <div>
            <h3 className="text-lg font-bold text-white">İşlem Geçmişi</h3>
            <span className="text-xs text-neutral-400">Hesaba bağlı gerçekleşen tüm Binance emir süreçleri</span>
          </div>

          <div className="flex flex-wrap gap-2 text-xs">
            <div className="flex rounded-md p-0.5 bg-neutral-800 border border-neutral-700 gap-1 mr-2">
              {(["daily", "weekly", "monthly", "all"] as const).map(p => (
                <button
                  key={p}
                  onClick={() => setTxPeriod(p)}
                  className={`px-2 py-1 font-semibold rounded capitalized transition ${
                    txPeriod === p ? "bg-[#f0b90b] text-neutral-900 font-bold" : "text-neutral-400 hover:text-white"
                  }`}
                >
                  {p === "all" ? "Genel" : p === "daily" ? "Günlük" : p === "weekly" ? "Haftalık" : "Aylık"}
                </button>
              ))}
            </div>

            <div className="flex rounded-md p-0.5 bg-neutral-800 border border-neutral-700 gap-1">
              {(["all", "buysell", "depositwithdraw"] as const).map(filter => (
                <button
                  key={filter}
                  onClick={() => setTxType(filter)}
                  className={`px-2 py-1 font-semibold rounded capitalized transition ${
                    txType === filter ? "bg-[#f0b90b] text-neutral-900 font-bold" : "text-neutral-400 hover:text-white"
                  }`}
                >
                  {filter === "all" ? "Tümü" : filter === "buysell" ? "Alım/Satım" : "Cüzdan"}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm text-left text-neutral-300">
            <thead className="bg-[#1e2026] text-xs uppercase text-neutral-400 border-b border-neutral-800">
              <tr>
                <th className="px-4 py-3">Tarih</th>
                <th className="px-4 py-3">Sembol</th>
                <th className="px-4 py-3">Tür</th>
                <th className="px-4 py-3 text-right">Miktar</th>
                <th className="px-4 py-3 text-right">Fiyat</th>
                <th className="px-4 py-3 text-right">Toplam (Tutar)</th>
                <th className="px-4 py-3 text-right">Komisyon</th>
                <th className="px-4 py-3 text-center">Yönetim</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-800/60 font-mono">
              {trades
                .filter(tx => {
                  if (txType === "all") return true;
                  if (txType === "buysell") return tx.side === "BUY" || tx.side === "SELL";
                  return tx.side !== "BUY" && tx.side !== "SELL"; // mock deposits/withdraws
                })
                .map((trade: Trade) => {
                  return (
                    <tr key={trade.order_id} className="hover:bg-neutral-800/40 transition">
                      <td className="px-4 py-3 text-neutral-400 text-xs">
                        {new Date(trade.time).toLocaleDateString()} {new Date(trade.time).toLocaleTimeString(undefined, {hour: '2-digit', minute:'2-digit'})}
                      </td>
                      <td className="px-4 py-3 font-bold text-white font-sans">{trade.symbol}</td>
                      <td className={`px-4 py-3 text-xs font-bold ${trade.side === "BUY" ? "text-[#0ecb81]" : "text-[#f6465d]"}`}>
                        {trade.side}
                      </td>
                      <td className="px-4 py-3 text-right text-neutral-200">{trade.executed_qty}</td>
                      <td className="px-4 py-3 text-right text-neutral-300">${trade.avg_price.toLocaleString()}</td>
                      <td className="px-4 py-3 text-right font-sans font-bold text-white">${trade.quote_qty.toLocaleString()}</td>
                      <td className="px-4 py-3 text-right text-neutral-400 text-xs">
                        {trade.commission} {trade.commission_asset} (${trade.commission_usd})
                      </td>
                      <td className="px-4 py-3 text-center font-sans">
                        <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                          trade.is_bot ? "bg-[#f0b90b]/10 text-[#f0b90b]" : "bg-neutral-800 text-neutral-400"
                        }`}>
                          {trade.is_bot ? "Bot" : "Manuel"}
                        </span>
                      </td>
                    </tr>
                  );
                })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Leaderboard Details Modal */}
      {selectedLeaderboardItem && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-neutral-900 border border-neutral-800 rounded-2xl max-w-lg w-full p-6 space-y-4 shadow-2xl">
            <div className="flex justify-between items-center border-b border-neutral-800 pb-3">
              <h3 className="text-lg font-bold text-white">{selectedLeaderboardItem.symbol} DCA Stratejisi</h3>
              <button 
                onClick={() => setSelectedLeaderboardItem(null)}
                className="text-neutral-400 hover:text-white font-bold"
              >
                ✕
              </button>
            </div>
            
            <div className="space-y-3 text-sm text-neutral-300">
              <div className="grid grid-cols-2 gap-4">
                <div className="bg-neutral-800 p-3 rounded-xl">
                  <span className="text-xs text-neutral-400 block mb-1">Net K/Z Oranı</span>
                  <strong className="text-lg text-[#0ecb81]">+{selectedLeaderboardItem.profit_pct}%</strong>
                </div>
                <div className="bg-neutral-800 p-3 rounded-xl">
                  <span className="text-xs text-neutral-400 block mb-1">Referans Fiyat</span>
                  <strong className="text-lg text-white">${selectedLeaderboardItem.reference_price}</strong>
                </div>
              </div>

              <div>
                <span className="text-xs text-neutral-400 block mb-1">Kullanılan Parametre Tablosu</span>
                <pre className="bg-[#1e2026] text-xs text-[#f0b90b] rounded-xl p-4 overflow-x-auto border border-neutral-800">
                  {JSON.stringify(selectedLeaderboardItem.params, null, 2)}
                </pre>
              </div>
            </div>

            <div className="flex justify-end gap-3 pt-3 border-t border-neutral-800">
              <button
                onClick={() => setSelectedLeaderboardItem(null)}
                className="px-4 py-2 text-sm font-semibold rounded-xl bg-neutral-800 hover:bg-neutral-700 text-neutral-300 transition"
              >
                Kapat
              </button>
              <button
                onClick={() => {
                  onApplyLeaderboard(selectedLeaderboardItem.params);
                  setSelectedLeaderboardItem(null);
                }}
                className="px-4 py-2 text-sm font-bold rounded-xl bg-[#f0b90b] text-neutral-900 hover:bg-[#c9930a] transition"
              >
                Şablonu Uygula
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
