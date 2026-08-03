import React, { useEffect, useMemo, useRef, useState } from "react";
import { AlertCircle, Coins, Percent } from "lucide-react";
import { useDashboard } from "../context/DashboardContext";
import { apiFetch } from "../lib/api";
import LiveValue from "./live/LiveValue";

const DEFAULT_PORTFOLIO_NAME = "Kripto Portföyüm";
const DEFAULT_ITEM_COUNT = 3;
const STORAGE_VERSION = 1;

export interface PortfolioItem {
  name: string;
  targetWeight: number;
  currentValue: number;
  quantity: number;
}

interface SetupField {
  name: string;
  initialValue: number;
  quantity: number;
}

interface RebalanceResult extends PortfolioItem {
  deviation: number;
}

interface StoredPortfolio {
  version: number;
  portfolioName: string;
  items: PortfolioItem[];
  lastTotal: number;
  currentTotal: number;
  createdAt: string;
  updatedAt: string;
}

function createSetupFields(count: number, previous: SetupField[] = []): SetupField[] {
  return Array.from({ length: count }, (_, index) => {
    const existing = previous[index];
    return existing || { name: "", initialValue: 0, quantity: 0 };
  });
}

function finiteNonNegative(value: unknown): number | null {
  const numberValue = Number(value);
  return Number.isFinite(numberValue) && numberValue >= 0 ? numberValue : null;
}

function normalizeStoredPortfolio(value: unknown): StoredPortfolio | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Partial<StoredPortfolio>;
  if (!Array.isArray(raw.items) || raw.items.length === 0) return null;

  const items: PortfolioItem[] = [];
  for (const rawItem of raw.items) {
    if (!rawItem || typeof rawItem !== "object") return null;
    const item = rawItem as Partial<PortfolioItem>;
    const currentValue = finiteNonNegative(item.currentValue);
    const quantity = finiteNonNegative(item.quantity);
    const targetWeight = Number(item.targetWeight);
    if (
      !String(item.name || "").trim() ||
      currentValue == null ||
      quantity == null ||
      !Number.isFinite(targetWeight) ||
      targetWeight < 0
    ) {
      return null;
    }
    items.push({
      name: String(item.name).trim(),
      currentValue,
      quantity,
      targetWeight,
    });
  }

  const weightTotal = items.reduce((sum, item) => sum + item.targetWeight, 0);
  if (weightTotal <= 0) return null;
  const normalizedItems = items.map((item) => ({
    ...item,
    targetWeight: item.targetWeight / weightTotal,
  }));
  const currentTotal = normalizedItems.reduce((sum, item) => sum + item.currentValue, 0);
  const storedLastTotal = finiteNonNegative(raw.lastTotal);

  return {
    version: STORAGE_VERSION,
    portfolioName: String(raw.portfolioName || DEFAULT_PORTFOLIO_NAME).trim() || DEFAULT_PORTFOLIO_NAME,
    items: normalizedItems,
    lastTotal: storedLastTotal != null && storedLastTotal > 0 ? storedLastTotal : currentTotal,
    currentTotal,
    createdAt: String(raw.createdAt || new Date().toISOString()),
    updatedAt: String(raw.updatedAt || raw.createdAt || new Date().toISOString()),
  };
}

export default function PortfolioTab() {
  const { accountId } = useDashboard();
  const storageKey = useMemo(() => `dcaPortfolio_account_${accountId}_v${STORAGE_VERSION}`, [accountId]);
  const createdAtRef = useRef(new Date().toISOString());

  const [portfolioName, setPortfolioName] = useState(DEFAULT_PORTFOLIO_NAME);
  const [itemCount, setItemCount] = useState(DEFAULT_ITEM_COUNT);
  const [screen, setScreen] = useState<1 | 2>(1);
  const [items, setItems] = useState<PortfolioItem[]>([]);
  const [results, setResults] = useState<RebalanceResult[]>([]);
  const [grandTotal, setGrandTotal] = useState(0);
  const [referenceTotal, setReferenceTotal] = useState(0);
  const [setupFields, setSetupFields] = useState<SetupField[]>(() =>
    createSetupFields(DEFAULT_ITEM_COUNT)
  );
  const [goldPriceTRY, setGoldPriceTRY] = useState<number | null>(null);
  const [usdtTry, setUsdtTry] = useState<number | null>(null);
  const [tickerUpdatedAt, setTickerUpdatedAt] = useState<Date | null>(null);
  const [tickerError, setTickerError] = useState("");
  const [storageError, setStorageError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    try {
      const raw = localStorage.getItem(storageKey);
      if (!raw) {
        createdAtRef.current = new Date().toISOString();
        setPortfolioName(DEFAULT_PORTFOLIO_NAME);
        setItemCount(DEFAULT_ITEM_COUNT);
        setSetupFields(createSetupFields(DEFAULT_ITEM_COUNT));
        setItems([]);
        setResults([]);
        setGrandTotal(0);
        setReferenceTotal(0);
        setScreen(1);
        setStorageError("");
        return;
      }

      const stored = normalizeStoredPortfolio(JSON.parse(raw));
      if (!stored) throw new Error("Kayıtlı portföy biçimi geçersiz.");
      createdAtRef.current = stored.createdAt;
      setPortfolioName(stored.portfolioName);
      setItemCount(stored.items.length);
      setItems(stored.items);
      setResults([]);
      setGrandTotal(stored.currentTotal);
      setReferenceTotal(stored.lastTotal);
      setScreen(2);
      setStorageError("");
    } catch (loadError) {
      console.error(loadError);
      createdAtRef.current = new Date().toISOString();
      setItems([]);
      setResults([]);
      setGrandTotal(0);
      setReferenceTotal(0);
      setScreen(1);
      setStorageError("Kayıtlı portföy okunamadı. Yeni bir referans oluşturabilirsiniz.");
    }
  }, [storageKey]);

  useEffect(() => {
    setSetupFields((previous) => createSetupFields(itemCount, previous));
  }, [itemCount]);

  useEffect(() => {
    let cancelled = false;

    const fetchTicker = async () => {
      try {
        const data = await apiFetch<Record<string, number | string>>("/api/ticker");
        if (cancelled) return;
        const nextGold = Number(data?.GRAM_ALTIN_TRY);
        const nextUsdtTry = Number(data?.USDTTRY);
        if (Number.isFinite(nextGold) && nextGold > 0) setGoldPriceTRY(nextGold);
        if (Number.isFinite(nextUsdtTry) && nextUsdtTry > 0) setUsdtTry(nextUsdtTry);
        setTickerUpdatedAt(new Date());
        setTickerError("");
      } catch (requestError) {
        if (cancelled) return;
        console.error(requestError);
        setTickerError("Kur bilgisi şu anda güncellenemiyor.");
      }
    };

    const refreshWhenVisible = () => {
      if (document.visibilityState === "visible") void fetchTicker();
    };

    void fetchTicker();
    const interval = window.setInterval(refreshWhenVisible, 60000);
    window.addEventListener("focus", refreshWhenVisible);
    document.addEventListener("visibilitychange", refreshWhenVisible);

    return () => {
      cancelled = true;
      window.clearInterval(interval);
      window.removeEventListener("focus", refreshWhenVisible);
      document.removeEventListener("visibilitychange", refreshWhenVisible);
    };
  }, []);

  const persistPortfolio = (
    nextItems: PortfolioItem[],
    nextName: string,
    nextReferenceTotal: number,
    nextCurrentTotal: number
  ): boolean => {
    const now = new Date().toISOString();
    const payload: StoredPortfolio = {
      version: STORAGE_VERSION,
      portfolioName: nextName.trim() || DEFAULT_PORTFOLIO_NAME,
      items: nextItems,
      lastTotal: nextReferenceTotal,
      currentTotal: nextCurrentTotal,
      createdAt: createdAtRef.current,
      updatedAt: now,
    };
    try {
      localStorage.setItem(storageKey, JSON.stringify(payload));
      setStorageError("");
      return true;
    } catch (saveError) {
      console.error(saveError);
      setStorageError("Portföy bu cihazda kaydedilemedi. Tarayıcı depolama iznini kontrol edin.");
      return false;
    }
  };

  const handleCreateSetup = () => {
    setNotice("");
    const normalizedFields = setupFields.map((field) => ({
      name: field.name.trim(),
      initialValue: finiteNonNegative(field.initialValue),
      quantity: finiteNonNegative(field.quantity),
    }));
    const invalidIndex = normalizedFields.findIndex(
      (field) => !field.name || field.initialValue == null || field.quantity == null
    );
    if (invalidIndex >= 0) {
      setStorageError(`${invalidIndex + 1}. enstrümanın adını ve geçerli değerlerini girin.`);
      return;
    }

    const totalInitial = normalizedFields.reduce(
      (sum, field) => sum + (field.initialValue || 0),
      0
    );
    if (totalInitial <= 0) {
      setStorageError("Toplam başlangıç değeri 0'dan büyük olmalıdır.");
      return;
    }

    const mappedItems: PortfolioItem[] = normalizedFields.map((field) => ({
      name: field.name,
      targetWeight: (field.initialValue || 0) / totalInitial,
      currentValue: field.initialValue || 0,
      quantity: field.quantity || 0,
    }));
    const nextName = portfolioName.trim() || DEFAULT_PORTFOLIO_NAME;
    createdAtRef.current = new Date().toISOString();
    persistPortfolio(mappedItems, nextName, totalInitial, totalInitial);
    setPortfolioName(nextName);
    setItems(mappedItems);
    setGrandTotal(totalInitial);
    setReferenceTotal(totalInitial);
    setResults([]);
    setScreen(2);
    setNotice("Portföy referansı bu hesaba özel olarak kaydedildi.");
  };

  const handleCalculateRebalance = () => {
    setNotice("");
    const total = items.reduce((sum, item) => sum + item.currentValue, 0);
    if (total <= 0) {
      setStorageError("Toplam bakiye 0'dan büyük olmalıdır.");
      return;
    }

    const calculatedActions = items.map((item) => {
      const targetValue = item.targetWeight * total;
      return {
        ...item,
        deviation: item.currentValue - targetValue,
      };
    });
    setGrandTotal(total);
    setResults(calculatedActions);
    persistPortfolio(items, portfolioName, referenceTotal || total, total);
  };

  const handleUpdateItemValue = (
    index: number,
    field: "currentValue" | "quantity",
    value: number
  ) => {
    const safeValue = Number.isFinite(value) && value >= 0 ? value : 0;
    setItems((current) =>
      current.map((item, itemIndex) =>
        itemIndex === index ? { ...item, [field]: safeValue } : item
      )
    );
    setResults([]);
    setNotice("");
  };

  const handleSaveCurrentReference = () => {
    const total = items.reduce((sum, item) => sum + item.currentValue, 0);
    if (total <= 0) {
      setStorageError("Yeni referans için toplam değer 0'dan büyük olmalıdır.");
      return;
    }
    const nextItems = items.map((item) => ({
      ...item,
      targetWeight: item.currentValue / total,
    }));
    if (!persistPortfolio(nextItems, portfolioName, total, total)) return;
    setItems(nextItems);
    setGrandTotal(total);
    setReferenceTotal(total);
    setResults([]);
    setNotice("Mevcut değerler yeni portföy referansı olarak kaydedildi.");
  };

  const handleResetReference = () => {
    if (
      !confirm(
        "Mevcut portföy referansını ve hedef dağılım ağırlıklarını sıfırlamak istiyor musunuz?"
      )
    ) {
      return;
    }
    try {
      localStorage.removeItem(storageKey);
      setStorageError("");
    } catch (removeError) {
      console.error(removeError);
      setStorageError("Kayıtlı portföy silinemedi.");
      return;
    }
    createdAtRef.current = new Date().toISOString();
    setPortfolioName(DEFAULT_PORTFOLIO_NAME);
    setItemCount(DEFAULT_ITEM_COUNT);
    setSetupFields(createSetupFields(DEFAULT_ITEM_COUNT));
    setScreen(1);
    setItems([]);
    setResults([]);
    setGrandTotal(0);
    setReferenceTotal(0);
    setNotice("Portföy referansı sıfırlandı.");
  };

  const pnlUsd = referenceTotal > 0 ? grandTotal - referenceTotal : null;
  const pnlPct = pnlUsd != null && referenceTotal > 0 ? (pnlUsd / referenceTotal) * 100 : null;
  const totalTry = usdtTry != null ? grandTotal * usdtTry : null;
  const goldGrams =
    totalTry != null && goldPriceTRY != null && goldPriceTRY > 0 ? totalTry / goldPriceTRY : null;

  return (
    <div className="space-y-6 max-w-4xl mx-auto">
      <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-6 shadow-xl">
        <h2 className="text-xl font-bold text-white mb-2 flex items-center">
          <Coins className="w-5 h-5 text-[#f0b90b] mr-2" /> Akıllı Portföy Yönetimi &amp;
          Tekrar Ortalama (Rebalance)
        </h2>
        <p className="text-xs text-neutral-400 mb-6">
          Hedef bakiye dağılım oranlarınızı belirleyin ve piyasa sapmalarını hesaplayın.
          Referans yalnızca bu hesaba ve bu tarayıcıya kaydedilir.
        </p>

        {storageError && (
          <div
            className="mb-4 bg-[#f6465d]/10 border border-[#f6465d]/20 text-[#f6465d] text-xs px-4 py-3 rounded-lg"
            role="alert"
          >
            {storageError}
          </div>
        )}
        {notice && (
          <div
            className="mb-4 bg-[#0ecb81]/10 border border-[#0ecb81]/20 text-[#0ecb81] text-xs px-4 py-3 rounded-lg"
            role="status"
          >
            {notice}
          </div>
        )}

        {screen === 1 ? (
          <div className="space-y-6">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-neutral-400">Portföy Sınıfı İsmi</label>
                <input
                  type="text"
                  value={portfolioName}
                  onChange={(event) => setPortfolioName(event.target.value)}
                  className="w-full bg-[#1e2026] text-white border border-neutral-800 rounded-lg p-2.5 text-sm"
                  placeholder={DEFAULT_PORTFOLIO_NAME}
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-neutral-400">
                  Kaç Başlık / Coin Olacak?
                </label>
                <input
                  type="number"
                  value={itemCount}
                  onChange={(event) =>
                    setItemCount(Math.min(50, Math.max(1, parseInt(event.target.value, 10) || 1)))
                  }
                  className="w-32 bg-[#1e2026] text-white border border-neutral-800 rounded-lg p-2.5 text-sm"
                  min="1"
                  max="50"
                />
              </div>
            </div>

            <div className="space-y-3.5 border-t border-neutral-800 pt-4">
              <h4 className="text-sm font-bold text-white">
                Başlangıç Referans Değerleri &amp; Hedef Ağırlık Dağılımları
              </h4>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                {setupFields.map((field, index) => (
                  <div
                    key={index}
                    className="bg-neutral-800/40 p-4 border border-neutral-800/80 rounded-xl space-y-2"
                  >
                    <span className="text-xs text-[#f0b90b] font-bold block">
                      Enstrüman #{index + 1}
                    </span>
                    <div className="space-y-1">
                      <label className="text-[10px] text-neutral-400 font-medium">Başlık Adı</label>
                      <input
                        type="text"
                        value={field.name}
                        onChange={(event) => {
                          const value = event.target.value;
                          setSetupFields((current) =>
                            current.map((item, itemIndex) =>
                              itemIndex === index ? { ...item, name: value } : item
                            )
                          );
                        }}
                        className="w-full bg-[#1e2026] text-white border border-neutral-800 rounded-lg px-2.5 py-1.5 text-xs"
                        placeholder="Örn: Bitcoin"
                      />
                    </div>
                    <div className="space-y-1">
                      <label className="text-[10px] text-neutral-400 font-medium">
                        Büyüklük (USD)
                      </label>
                      <input
                        type="number"
                        min="0"
                        step="0.01"
                        value={field.initialValue}
                        onChange={(event) => {
                          const value = Number(event.target.value);
                          setSetupFields((current) =>
                            current.map((item, itemIndex) =>
                              itemIndex === index
                                ? {
                                    ...item,
                                    initialValue:
                                      Number.isFinite(value) && value >= 0 ? value : 0,
                                  }
                                : item
                            )
                          );
                        }}
                        className="w-full bg-[#1e2026] text-white border border-neutral-800 rounded-lg px-2.5 py-1.5 text-xs"
                      />
                    </div>
                    <div className="space-y-1">
                      <label className="text-[10px] text-neutral-400 font-medium">
                        Miktar (Adet)
                      </label>
                      <input
                        type="number"
                        min="0"
                        step="any"
                        value={field.quantity}
                        onChange={(event) => {
                          const value = Number(event.target.value);
                          setSetupFields((current) =>
                            current.map((item, itemIndex) =>
                              itemIndex === index
                                ? {
                                    ...item,
                                    quantity: Number.isFinite(value) && value >= 0 ? value : 0,
                                  }
                                : item
                            )
                          );
                        }}
                        className="w-full bg-[#1e2026] text-white border border-neutral-800 rounded-lg px-2.5 py-1.5 text-xs"
                      />
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <button
              type="button"
              onClick={handleCreateSetup}
              className="w-full px-4 py-2.5 bg-[#f0b90b] hover:bg-[#c9930a] text-neutral-900 font-bold rounded-lg text-sm transition"
            >
              Referansı Oluştur ve Kaydet
            </button>
          </div>
        ) : (
          <div className="space-y-6">
            <div className="flex justify-between items-center border-b border-neutral-800 pb-3">
              <h3 className="font-bold text-white text-lg tracking-wide">{portfolioName}</h3>
              <span className="text-xs text-neutral-400">Hesap #{accountId} yerel referansı</span>
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
                  {items.map((item, index) => {
                    const result = results[index];
                    let text = "Hesaplanmadı";
                    let colorClass = "text-neutral-500";
                    if (result) {
                      if (Math.abs(result.deviation) < 0.01) {
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
                      <tr key={`${item.name}-${index}`} className="hover:bg-neutral-800/40 transition">
                        <td className="px-4 py-3.5 font-sans font-bold text-white">{item.name}</td>
                        <td className="px-4 py-3.5 text-right text-neutral-300">
                          {(item.targetWeight * 100).toFixed(2)}%
                        </td>
                        <td className="px-4 py-3.5 text-right font-sans">
                          <input
                            type="number"
                            min="0"
                            step="0.01"
                            value={item.currentValue}
                            onChange={(event) =>
                              handleUpdateItemValue(index, "currentValue", Number(event.target.value))
                            }
                            className="bg-[#1e2026] text-white border border-neutral-800 rounded-lg px-2.5 py-1.5 focus:border-[#f0b90b] text-right font-mono text-sm max-w-[140px]"
                          />
                        </td>
                        <td className="px-4 py-3.5 text-right">
                          <input
                            type="number"
                            min="0"
                            step="any"
                            value={item.quantity}
                            onChange={(event) =>
                              handleUpdateItemValue(index, "quantity", Number(event.target.value))
                            }
                            className="bg-[#1e2026] text-white border border-neutral-800 rounded-lg px-2.5 py-1.5 focus:border-[#f0b90b] text-right font-mono text-sm max-w-[100px]"
                          />
                        </td>
                        <td
                          className={`px-4 py-3.5 text-center font-sans font-bold text-sm ${colorClass}`}
                        >
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
                type="button"
                onClick={handleCalculateRebalance}
                className="px-5 py-2.5 bg-[#f0b90b] hover:bg-[#c9930a] text-neutral-900 font-bold rounded-lg text-sm transition"
              >
                Ortalamayı Yeniden Hesapla
              </button>
              <button
                type="button"
                onClick={handleSaveCurrentReference}
                className="px-5 py-2.5 bg-neutral-800 hover:bg-neutral-700 text-white font-semibold rounded-lg text-sm transition"
              >
                Mevcut Değerleri Yeni Referans Yap
              </button>
              <button
                type="button"
                onClick={handleResetReference}
                className="px-5 py-2.5 bg-[#f6465d]/10 hover:bg-[#f6465d]/20 text-[#f6465d] border border-[#f6465d]/20 font-semibold rounded-lg text-sm transition"
              >
                Şablonu Sıfırla
              </button>
            </div>

            {results.length > 0 && (
              <div className="bg-[#1e2026] border border-neutral-800 p-6 rounded-xl space-y-4">
                <h4 className="text-sm font-bold text-white uppercase tracking-wider flex items-center">
                  <Percent className="w-4 h-4 text-[#f0b90b] mr-1.5" /> Portföy Analitik
                  Görünümü &amp; Altın Raporu
                </h4>

                <div className="grid grid-cols-1 md:grid-cols-4 gap-6 divide-y md:divide-y-0 md:divide-x divide-neutral-800 font-sans">
                  <div className="flex flex-col justify-center p-2">
                    <span className="text-xs text-neutral-400">Toplam Portföy Değeri</span>
                    <strong className="text-xl font-bold text-white mt-1">
                      <LiveValue value={grandTotal}>
                        ${grandTotal.toLocaleString("en-US", { minimumFractionDigits: 2 })}
                      </LiveValue>
                    </strong>
                    {pnlUsd != null && pnlPct != null && (
                      <span
                        className={`text-[10px] mt-0.5 ${
                          pnlUsd >= 0 ? "text-[#0ecb81]" : "text-[#f6465d]"
                        }`}
                      >
                        Referansa göre{" "}
                        <LiveValue value={pnlUsd} toneBySign>
                          {pnlUsd >= 0 ? "+" : ""}${pnlUsd.toFixed(2)} (
                          {pnlPct >= 0 ? "+" : ""}
                          {pnlPct.toFixed(2)}%)
                        </LiveValue>
                      </span>
                    )}
                  </div>

                  <div className="flex flex-col justify-center p-2 md:pl-6">
                    <span className="text-xs text-neutral-400">Referans Değeri</span>
                    <strong className="text-xl font-bold text-neutral-200 mt-1">
                      ${referenceTotal.toLocaleString("en-US", { minimumFractionDigits: 2 })}
                    </strong>
                  </div>

                  <div className="flex flex-col justify-center p-2 md:pl-6">
                    <span className="text-xs text-neutral-400">Türk Lirası Karşılığı</span>
                    <strong className="text-xl font-bold text-neutral-200 mt-1">
                      {totalTry == null
                        ? "—"
                        : `₺${totalTry.toLocaleString("tr-TR", { minimumFractionDigits: 2 })}`}
                    </strong>
                    <span className="text-[10px] text-neutral-500 mt-0.5">
                      {usdtTry == null ? (
                        "USDT/TRY alınamadı"
                      ) : (
                        <LiveValue value={usdtTry}>
                          1 USDT = ₺{usdtTry.toFixed(2)}
                        </LiveValue>
                      )}
                    </span>
                  </div>

                  <div className="flex flex-col justify-center p-2 md:pl-6">
                    <span className="text-xs text-neutral-400">Gram Altın Karşılığı</span>
                    <strong className="text-xl font-bold text-[#f0b90b] mt-1">
                      {goldGrams == null ? "—" : `${goldGrams.toFixed(2)} gr`}
                    </strong>
                    <span className="text-[10px] text-neutral-500 mt-0.5">
                      {goldPriceTRY == null ? (
                        "Gram altın fiyatı alınamadı"
                      ) : (
                        <LiveValue value={goldPriceTRY}>
                          Gram altın: ₺{goldPriceTRY.toFixed(2)}
                        </LiveValue>
                      )}
                    </span>
                  </div>
                </div>

                <div className="flex items-start gap-1.5 p-3 bg-neutral-900/60 rounded-lg text-xs text-neutral-400">
                  <AlertCircle className="w-4 h-4 text-[#f0b90b] shrink-0" />
                  <span>
                    {tickerError ||
                      `Kur bilgisi ${
                        tickerUpdatedAt
                          ? tickerUpdatedAt.toLocaleTimeString("tr-TR", {
                              hour: "2-digit",
                              minute: "2-digit",
                            })
                          : "henüz"
                      } güncellendi. Rebalance sonucu yalnızca hesaplama önerisidir; otomatik emir göndermez.`}
                  </span>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
