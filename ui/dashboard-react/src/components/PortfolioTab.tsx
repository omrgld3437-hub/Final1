import React, { useState, useEffect } from "react";
import { Coins, Percent, AlertCircle } from "lucide-react";
import { apiFetch } from "../lib/api";

export interface PortfolioItem {
  name: string;
  targetWeight: number; // 0 to 1
  currentValue: number; // USD
  quantity: number;
}

export default function PortfolioTab() {
  const [portfolioName, setPortfolioName] = useState("Kripto Portföyüm");
  const [itemCount, setItemCount] = useState(3);
  const [screen, setScreen] = useState(1);
  const [items, setItems] = useState<PortfolioItem[]>([]);
  const [results, setResults] = useState<any[]>([]);
  const [grandTotal, setGrandTotal] = useState(0);

  // Gold rate & exchange rates fields
  const [goldPriceTRY, setGoldPriceTRY] = useState(2450.40);
  const [usdtTry, setUsdtTry] = useState(32.42);

  // Edit fields for Screen 1 Setup
  const [setupFields, setSetupFields] = useState<any[]>([]);

  useEffect(() => {
    const fetchTicker = () => {
      apiFetch<Record<string, number>>("/api/ticker")
        .then((data) => {
          if (data?.GRAM_ALTIN_TRY) setGoldPriceTRY(data.GRAM_ALTIN_TRY);
          if (data?.USDTTRY) setUsdtTry(data.USDTTRY);
        })
        .catch(console.error);
    };

    fetchTicker();
    const interval = setInterval(fetchTicker, 2000);
    return () => clearInterval(interval);
  }, []);

  // Initialize Setup Fields on headcount input change
  useEffect(() => {
    const fields = [];
    for (let i = 0; i < itemCount; i++) {
      fields.push({
        name: i === 0 ? "Bitcoin" : i === 1 ? "Ethereum" : `Altcoin #${i + 1}`,
        initialValue: i === 0 ? 500 : i === 1 ? 300 : 200,
        quantity: i === 0 ? 0.007 : i === 1 ? 0.08 : 1,
      });
    }
    setSetupFields(fields);
  }, [itemCount]);

  const handleCreateSetup = () => {
    let totalInitial = setupFields.reduce((sum, f) => sum + f.initialValue, 0);
    if (totalInitial <= 0) {
      alert("Toplam değer 0'dan büyük olmalıdır.");
      return;
    }
    
    // Map setup fields values to targets
    const mappedItems = setupFields.map(field => ({
      name: field.name,
      targetWeight: field.initialValue / totalInitial,
      currentValue: field.initialValue,
      quantity: field.quantity
    }));

    setItems(mappedItems);
    setScreen(2);
    setResults([]);
  };

  const handleCalculateRebalance = () => {
    const total = items.reduce((sum, item) => sum + item.currentValue, 0);
    setGrandTotal(total);
    
    if (total <= 0) {
      alert("Toplam bakiye 0'dan büyük olmalıdır.");
      return;
    }

    const calculatedActions = items.map(item => {
      const targetValue = item.targetWeight * total;
      const deviation = item.currentValue - targetValue;
      return {
        name: item.name,
        targetWeight: item.targetWeight,
        currentValue: item.currentValue,
        quantity: item.quantity,
        deviation: deviation, // Positive is Sell, Negative is Buy
      };
    });

    setResults(calculatedActions);
  };

  const handleUpdateItemValue = (idx: number, field: "currentValue" | "quantity", value: number) => {
    setItems(prev => prev.map((item, i) => i === idx ? { ...item, [field]: value } : item));
  };

  const handleResetReference = () => {
    if (confirm("Mevcut portföy referans şablonunu ve hedef dağılım ağırlıklarını sıfırlamak istiyor musunuz?")) {
      setScreen(1);
      setItems([]);
      setResults([]);
    }
  };

  return (
    <div className="space-y-6 max-w-4xl mx-auto">
      <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-6 shadow-xl">
        <h2 className="text-xl font-bold text-white mb-2 flex items-center">
          <Coins className="w-5 h-5 text-[#f0b90b] mr-2" /> Akıllı Portföy Yönetimi &amp; Tekrar Ortalama (Rebalance)
        </h2>
        <p className="text-xs text-neutral-400 mb-6">Hedef bakiye dağılım oranlarınızı belirleyin ve anlık piyasadan sapmaları tek tıklamayla hesaplayın.</p>
        
        {screen === 1 ? (
          /* Screen 1: Set Reference Allocation */
          <div className="space-y-6">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-neutral-400">Portföy Sınıfı İsmi</label>
                <input
                  type="text"
                  value={portfolioName}
                  onChange={e => setPortfolioName(e.target.value)}
                  className="w-full bg-[#1e2026] text-white border border-neutral-800 rounded-lg p-2.5 text-sm"
                  placeholder="Kripto Portföyüm"
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-neutral-400">Kaç Başlık / Coin Olacak?</label>
                <div className="flex gap-2">
                  <input
                    type="number"
                    value={itemCount}
                    onChange={e => setItemCount(Math.max(1, parseInt(e.target.value) || 1))}
                    className="w-32 bg-[#1e2026] text-white border border-neutral-800 rounded-lg p-2.5 text-sm"
                    min="1"
                  />
                  <button
                    onClick={handleCreateSetup}
                    className="flex-1 px-4 py-2 bg-[#f0b90b] hover:bg-[#c9930a] text-neutral-900 font-bold rounded-lg text-sm transition"
                  >
                    Şablonu Oluştur
                  </button>
                </div>
              </div>
            </div>

            {setupFields.length > 0 && (
              <div className="space-y-3.5 border-t border-neutral-800 pt-4">
                <h4 className="text-sm font-bold text-white">Başlangıç Referans Değerleri &amp; Hedef Ağırlık Dağılımları</h4>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  {setupFields.map((field, idx) => (
                    <div key={idx} className="bg-neutral-800/40 p-4 border border-neutral-800/80 rounded-xl space-y-2">
                      <span className="text-xs text-[#f0b90b] font-bold block">Enstrüman #{idx + 1}</span>
                      <div className="space-y-1">
                        <label className="text-[10px] text-neutral-400 font-medium">Başlık Adı</label>
                        <input
                          type="text"
                          value={field.name}
                          onChange={e => {
                            const val = e.target.value;
                            setSetupFields(prev => prev.map((f, i) => i === idx ? { ...f, name: val } : f));
                          }}
                          className="w-full bg-[#1e2026] text-white border border-neutral-800 rounded-lg px-2.5 py-1.5 text-xs"
                        />
                      </div>
                      <div className="space-y-1">
                        <label className="text-[10px] text-neutral-400 font-medium">Büyüklük (USD)</label>
                        <input
                          type="number"
                          value={field.initialValue}
                          onChange={e => {
                            const val = parseFloat(e.target.value) || 0;
                            setSetupFields(prev => prev.map((f, i) => i === idx ? { ...f, initialValue: val } : f));
                          }}
                          className="w-full bg-[#1e2026] text-white border border-neutral-800 rounded-lg px-2.5 py-1.5 text-xs"
                        />
                      </div>
                      <div className="space-y-1">
                        <label className="text-[10px] text-neutral-400 font-medium">Miktar (Adet)</label>
                        <input
                          type="number"
                          value={field.quantity}
                          onChange={e => {
                            const val = parseFloat(e.target.value) || 0;
                            setSetupFields(prev => prev.map((f, i) => i === idx ? { ...f, quantity: val } : f));
                          }}
                          className="w-full bg-[#1e2026] text-white border border-neutral-800 rounded-lg px-2.5 py-1.5 text-xs"
                        />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        ) : (
          /* Screen 2: Real-time Rebalancer tracker and calculations */
          <div className="space-y-6">
            <div className="flex justify-between items-center border-b border-neutral-800 pb-3">
              <h3 className="font-bold text-white text-lg tracking-wide">{portfolioName}</h3>
              <span className="text-xs text-neutral-400">Referans Hedefleri Ağırlık Açılarına Göre Düzenle</span>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-sm text-left text-neutral-300">
                <thead className="bg-[#1e2026] text-xs uppercase text-neutral-400 border-b border-neutral-800">
                  <tr>
                    <th className="px-4 py-3">Enstrüman</th>
                    <th className="px-4 py-3 text-right">Hedef Oran %</th>
                    <th className="px-4 py-3 text-right">Güncel Değer (USD)</th>
                    <th className="px-4 py-3 text-right">Adet (Miktar)</th>
                    <th className="px-4 py-3 text-center">Sapma Durumu</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-neutral-800/60 font-mono">
                  {items.map((item, idx) => {
                    const result = results[idx];
                    let text = "Hesaplanmadı";
                    let colorClass = "text-neutral-500";
                    if (result) {
                      if (Math.abs(result.deviation) < 0.05) {
                        text = "Dengede";
                        colorClass = "text-[#0ecb81]";
                      } else if (result.deviation > 0) {
                        text = `SAT $${result.deviation.toFixed(2)}`;
                        colorClass = "text-[#f6465d]";
                      } else {
                        text = `AL $${Math.abs(result.deviation).toFixed(2)}`;
                        colorClass = "text-[#0ecb81]";
                      }
                    }

                    return (
                      <tr key={idx} className="hover:bg-neutral-800/40 transition">
                        <td className="px-4 py-3.5 font-sans font-bold text-white">{item.name}</td>
                        <td className="px-4 py-3.5 text-right text-neutral-300">{(item.targetWeight * 100).toFixed(2)}%</td>
                        <td className="px-4 py-3.5 text-right font-sans flex justify-end">
                          <input
                            type="number"
                            value={item.currentValue}
                            onChange={e => handleUpdateItemValue(idx, "currentValue", parseFloat(e.target.value) || 0)}
                            className="bg-[#1e2026] text-white border border-neutral-800 rounded-lg px-2.5 py-1.5 focus:border-[#f0b90b] text-right font-mono text-sm max-w-[140px]"
                          />
                        </td>
                        <td className="px-4 py-3.5 text-right">
                          <input
                            type="number"
                            value={item.quantity}
                            onChange={e => handleUpdateItemValue(idx, "quantity", parseFloat(e.target.value) || 0)}
                            className="bg-[#1e2026] text-white border border-neutral-800 rounded-lg px-2.5 py-1.5 focus:border-[#f0b90b] text-right font-mono text-sm max-w-[100px]"
                          />
                        </td>
                        <td className={`px-4 py-3.5 text-center font-sans font-bold text-sm ${colorClass}`}>
                          {text}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <div className="flex flex-wrap gap-3 border-t border-neutral-800 pt-4">
              <button
                onClick={handleCalculateRebalance}
                className="px-5 py-2.5 bg-[#f0b90b] hover:bg-[#c9930a] text-neutral-900 font-bold rounded-lg text-sm transition"
              >
                Ortalamayı Yeniden Hesapla
              </button>
              <button
                onClick={handleResetReference}
                className="px-5 py-2.5 bg-neutral-800 hover:bg-neutral-700 text-neutral-300 font-semibold rounded-lg text-sm transition"
              >
                Şablonu Sıfırla
              </button>
            </div>

            {/* Portfolio Summary Analytics */}
            {results.length > 0 && (
              <div className="bg-[#1e2026] border border-neutral-850 p-6 rounded-xl space-y-4">
                <h4 className="text-sm font-bold text-white uppercase tracking-wider flex items-center">
                  <Percent className="w-4 h-4 text-[#f0b90b] mr-1.5" /> Portföy Analitik Görünümü &amp; Altın Raporu
                </h4>
                
                <div className="grid grid-cols-1 md:grid-cols-3 gap-6 divide-y md:divide-y-0 md:divide-x divide-neutral-800 font-sans">
                  <div className="flex flex-col justify-center p-2">
                    <span className="text-xs text-neutral-400">Toplam Portföy Değeri</span>
                    <strong className="text-xl font-bold text-white mt-1">${grandTotal.toLocaleString(undefined, { minimumFractionDigits: 2 })}</strong>
                  </div>

                  <div className="flex flex-col justify-center p-2 md:pl-6">
                    <span className="text-xs text-neutral-400">Türk Lirası Karşılığı</span>
                    <strong className="text-xl font-bold text-neutral-200 mt-1">
                      ₺{(grandTotal * usdtTry).toLocaleString(undefined, { minimumFractionDigits: 2 })}
                    </strong>
                    <span className="text-[10px] text-neutral-500 mt-0.5">Simüle kur: ${usdtTry} TRY</span>
                  </div>

                  <div className="flex flex-col justify-center p-2 md:pl-6">
                    <span className="text-xs text-neutral-400">Gram Altın Karşılığı</span>
                    <strong className="text-xl font-bold text-[#f0b90b] mt-1">
                      {((grandTotal * usdtTry) / goldPriceTRY).toFixed(2)} gr
                    </strong>
                    <span className="text-[10px] text-neutral-500 mt-0.5">Gram altın fiyatı: ₺{goldPriceTRY.toFixed(1)}</span>
                  </div>
                </div>

                <div className="flex items-start gap-1.5 p-3 bg-neutral-900/60 rounded-lg text-xs text-neutral-400">
                  <AlertCircle className="w-4 h-4 text-[#f0b90b] shrink-0" />
                  <span>Tekrar ortalama (rebalance) stratejisi, fonlarınızın hedeflenen oranlara çekilmesini sağlar ve piyasa dalgalanmalarındaki aşırı risk sapmalarını en aza indirmek için tasarlanmıştır.</span>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
