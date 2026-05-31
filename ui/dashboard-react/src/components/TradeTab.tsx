import React, { useState, useEffect } from "react";
import { Star, Search, CreditCard, ArrowUpRight, ArrowDownLeft } from "lucide-react";
import { useDashboard } from "../context/DashboardContext";
import { apiFetch } from "../lib/api";

interface TradeTabProps {
  prices: any;
  onOpenTradeModal: (symbol: string, side: "BUY" | "SELL") => void;
}

export default function TradeTab({ prices, onOpenTradeModal }: TradeTabProps) {
  const { accountId } = useDashboard();
  const [search, setSearch] = useState("");
  const [allCoins, setAllCoins] = useState<any[]>([]);
  const [filteredCoins, setFilteredCoins] = useState<any[]>([]);
  const [favorites, setFavorites] = useState<string[]>(["BTCUSDT", "ETHUSDT", "SOLUSDT"]);

  useEffect(() => {
    apiFetch<{ coins?: unknown[] }>("/api/data/coin-list")
      .then((data) => {
        if (data?.coins) {
          setAllCoins(data.coins);
          setFilteredCoins(data.coins);
        }
      })
      .catch(console.error);

    apiFetch<{ symbols?: string[] }>(`/api/accounts/${accountId}/spot-favorites`)
      .then((data) => {
        if (Array.isArray(data?.symbols)) setFavorites(data.symbols);
      })
      .catch(console.error);
  }, [accountId]);

  // Filter list when searching
  useEffect(() => {
    if (!search.trim()) {
      setFilteredCoins(allCoins);
    } else {
      const q = search.toUpperCase();
      setFilteredCoins(
        allCoins.filter(
          coin =>
            coin.symbol.includes(q) ||
            coin.symbol.replace("USDT", "").includes(q)
        )
      );
    }
  }, [search, allCoins]);

  const handleToggleFavorite = (e: React.MouseEvent, symbol: string) => {
    e.stopPropagation();
    if (favorites.includes(symbol)) {
      setFavorites(prev => prev.filter(f => f !== symbol));
    } else {
      setFavorites(prev => [...prev, symbol]);
    }
  };

  return (
    <div className="space-y-6 max-w-4xl mx-auto">
      {/* Favorite Quick Trading Cards */}
      <div className="space-y-3">
        <h4 className="text-sm font-bold text-neutral-400 uppercase tracking-widest flex items-center">
          <Star className="w-4 h-4 mr-1 text-[#f0b90b] fill-[#f0b90b]" /> Favori Çiftler
        </h4>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {favorites.map(favSymbol => {
            const coinPrice = prices[favSymbol]?.price || 0;
            const change = prices[favSymbol]?.change24h || 0;
            const isUp = change >= 0;
            
            return (
              <div 
                key={favSymbol} 
                onClick={() => onOpenTradeModal(favSymbol, "BUY")}
                className="bg-neutral-900 border border-neutral-800 hover:border-neutral-700 rounded-xl p-4 cursor-pointer transition relative overflow-hidden group shadow-md"
              >
                <div className="flex justify-between items-start">
                  <div>
                    <h5 className="font-bold text-white text-base">{favSymbol.replace("USDT", "/USDT")}</h5>
                    <div className="text-xl font-black mt-2 font-mono">
                      ${coinPrice.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 })}
                    </div>
                  </div>
                  <span className={`text-xs px-2 py-0.5 rounded font-bold flex items-center ${isUp ? 'bg-[#0ecb81]/15 text-[#0ecb81]' : 'bg-[#f6465d]/15 text-[#f6465d]'}`}>
                    {isUp ? <ArrowUpRight className="w-3 h-3 mr-0.5" /> : <ArrowDownLeft className="w-3 h-3 mr-0.5" />}
                    {isUp ? '+' : ''}{change.toFixed(2)}%
                  </span>
                </div>
                <div className="text-xs text-neutral-500 mt-4 group-hover:text-[#f0b90b] transition flex items-center">
                  <CreditCard className="w-3.5 h-3.5 mr-1" /> Hızlı Alım/Satım açmak için tıkla
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-6 shadow-xl space-y-4">
        {/* Search Bar */}
        <div className="relative">
          <Search className="absolute left-3 top-3.5 w-5 h-5 text-neutral-400" />
          <input
            type="text"
            placeholder="BTCUSDT, ETH, SOL... Ara"
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="w-full bg-[#1e2026] text-white border border-neutral-800 hover:border-neutral-700 focus:border-[#f0b90b] rounded-xl pl-11 pr-4 py-3 text-sm focus:outline-none focus:ring-1 focus:ring-[#f0b90b] transition"
          />
        </div>

        {/* Coins List Table */}
        <div className="overflow-x-auto">
          <table className="w-full text-sm text-left text-neutral-300">
            <thead className="bg-[#1e2026] text-xs uppercase text-neutral-400 border-b border-neutral-800">
              <tr>
                <th className="px-4 py-3 w-10">Favori</th>
                <th className="px-4 py-3">Sembol</th>
                <th className="px-4 py-3 text-right">Fiyat</th>
                <th className="px-4 py-3 text-right">24s Değişim</th>
                <th className="px-4 py-3 text-right">Hacim</th>
                <th className="px-4 py-3 text-center">İşlem Yap</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-800/60 font-mono">
              {filteredCoins.map(coin => {
                const livePrice = prices[coin.symbol]?.price || parseFloat(coin.lastPrice || coin.price || 0);
                const isFav = favorites.includes(coin.symbol);
                const change = prices[coin.symbol]?.change24h || parseFloat(coin.priceChangePercent);
                const isUp = change >= 0;
                
                return (
                  <tr 
                    key={coin.symbol} 
                    onClick={() => onOpenTradeModal(coin.symbol, "BUY")}
                    className="hover:bg-neutral-800/40 transition cursor-pointer"
                  >
                    <td className="px-4 py-3.5 text-center">
                      <button 
                        onClick={(e) => handleToggleFavorite(e, coin.symbol)}
                        className="text-neutral-500 hover:text-[#f0b90b] transition"
                      >
                        <Star className={`w-4 h-4 ${isFav ? 'text-[#f0b90b] fill-[#f0b90b]' : ''}`} />
                      </button>
                    </td>
                    <td className="px-4 py-3.5 font-bold text-white font-sans flex items-center gap-2">
                      {coin.symbol}
                    </td>
                    <td className="px-4 py-3.5 text-right font-bold text-neutral-200">
                      ${livePrice.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 })}
                    </td>
                    <td className={`px-4 py-3.5 text-right font-bold ${isUp ? 'text-[#0ecb81]' : 'text-[#f6465d]'}`}>
                      {isUp ? '+' : ''}{change.toFixed(2)}%
                    </td>
                    <td className="px-4 py-3.5 text-right text-neutral-400">
                      {(parseFloat(coin.volume || 0) * livePrice).toLocaleString(undefined, { maximumFractionDigits: 0 })} USDT
                    </td>
                    <td className="px-4 py-3.5 text-center font-sans">
                      <button 
                        onClick={(e) => {
                          e.stopPropagation();
                          onOpenTradeModal(coin.symbol, "BUY");
                        }}
                        className="px-3 py-1.5 bg-[#f0b90b] hover:bg-[#c9930a] text-neutral-900 text-xs font-bold rounded-lg transition"
                      >
                        Al / Sat
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
