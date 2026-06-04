import React, { useState } from "react";
import { Bot } from "../types";
import { useDashboard } from "../context/DashboardContext";
import { apiFetch } from "../lib/api";
import { Play, Square, CircleHelp, AlertTriangle, Cpu } from "lucide-react";

interface BotsTabProps {
  bots: Bot[];
  setBots: React.Dispatch<React.SetStateAction<Bot[]>>;
  availableUSDT: number;
}

export interface NewBotForm {
  symbol: string;
  budget_usd: number;
  base_pct: number;
  quote_pct: number;
  upCount: number;
  upTrail: number;
  downCount: number;
  downTrail: number;
  maxBuyLevels: number;
  rebuyTrigger: number;
  rebuyTrail: number;
  resellTrigger: number;
  resellTrail: number;
}

export default function BotsTab({ bots, setBots, availableUSDT }: BotsTabProps) {
  const { accountId } = useDashboard();
  const [showCreateWizard, setShowCreateWizard] = useState(false);
  const [currentStep, setCurrentStep] = useState(1);
  const [wizardError, setWizardError] = useState("");
  
  const [form, setForm] = useState<NewBotForm>({
    symbol: "BTCUSDT",
    budget_usd: 1000,
    base_pct: 50,
    quote_pct: 50,
    upCount: 2,
    upTrail: 0.5,
    downCount: 2,
    downTrail: 0.5,
    maxBuyLevels: 2,
    rebuyTrigger: 1.5,
    rebuyTrail: 0.30,
    resellTrigger: 1.5,
    resellTrail: 0.5,
  });

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

  const handleNextStep = () => {
    if (currentStep === 1) {
      if (!form.symbol.trim()) {
        setWizardError("Geçerli bir işlem çifti giriniz.");
        return;
      }
      if (form.budget_usd < 10) {
        setWizardError("Minimum bot bütçesi 10 USD'dir.");
        return;
      }
      if (form.budget_usd > availableUSDT) {
        setWizardError(`Mevcut bakiye yetersiz! Kullanılabilir bakiye: $${availableUSDT.toFixed(2)}`);
        return;
      }
    }
    if (currentStep === 2) {
      if (form.base_pct + form.quote_pct !== 100) {
        setWizardError("Base % ve Quote % toplamı 100 olmalıdır.");
        return;
      }
    }
    if (currentStep === 4) {
      if (form.downCount < 1) {
        setWizardError("En az bir alış grid seviyesi tanımlayın.");
        return;
      }
      if (form.maxBuyLevels < 1 || form.maxBuyLevels > form.downCount) {
        setWizardError("Maksimum alış seviyesi 1 ile alış grid sayısı arasında olmalıdır.");
        return;
      }
    }
    setWizardError("");
    setCurrentStep(prev => prev + 1);
  };

  const handlePrevStep = () => {
    setWizardError("");
    setCurrentStep(prev => prev - 1);
  };

  const handleCreateBot = () => {
    const payload = {
      ...form,
      strategy_id: "dca_grid_trailing",
      allocation: { base_pct: form.base_pct, quote_pct: form.quote_pct },
      up: { trail_pct: form.upTrail, grids: Array.from({ length: form.upCount }, (_, i) => ({ trigger_pct: (i + 1) * 0.5, qty_pct: 10 })) },
      down: { trail_pct: form.downTrail, grids: Array.from({ length: form.downCount }, (_, i) => ({ trigger_pct: (i + 1) * 0.5, qty_pct: 10 })) },
      max_buy_levels: form.maxBuyLevels,
      profit: {
        rebuy_trigger_pct: form.rebuyTrigger,
        rebuy_trail_pct: form.rebuyTrail,
        resell_trigger_pct: form.resellTrigger,
        resell_trail_pct: form.resellTrail,
      },
    };
    apiFetch<{ success?: boolean; bot_id?: number }>("/api/bots/create", {
      method: "POST",
      body: JSON.stringify({
        account_id: accountId,
        config_json: JSON.stringify(payload),
      }),
    })
      .then((data) => {
        if (data?.success && data.bot_id) {
          apiFetch(`/api/bots-engine/${data.bot_id}/start?account_id=${accountId}`, {
            method: "POST",
          }).then(() => {
            apiFetch<{ bots?: Bot[] }>(`/api/bots-engine?account_id=${accountId}`).then((d) => {
              if (d?.bots) setBots(d.bots);
            });
          });
          alert("Bot başarıyla oluşturuldu ve çalıştırıldı!");
          setShowCreateWizard(false);
          setCurrentStep(1);
        }
      })
      .catch(console.error);
  };

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center bg-neutral-900 border border-neutral-800 rounded-xl p-4 shadow-md">
        <div>
          <h3 className="font-bold text-lg text-white">Bot Yönetimi</h3>
          <p className="text-xs text-neutral-400">Trailing Stop ve DCA ızgara botlarınızı yönetin</p>
        </div>
        <button
          onClick={() => {
            setWizardError("");
            setCurrentStep(1);
            setShowCreateWizard(true);
          }}
          className="px-5 py-2.5 bg-[#f0b90b] hover:bg-[#c9930a] text-neutral-900 font-bold rounded-lg shadow-lg hover:shadow-xl transition"
        >
          + Bot Oluştur
        </button>
      </div>

      {/* Grid of Existing Bots */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {bots.map(bot => {
          const profitColor = bot.total_pnl_usd >= 0 ? "text-[#0ecb81]" : "text-[#f6465d]";
          return (
            <div key={bot.id} className="bg-neutral-900 border border-neutral-800 rounded-xl p-6 shadow-xl relative overflow-hidden group hover:border-[#f0b90b] transition">
              <div className="flex justify-between items-center border-b border-neutral-800 pb-3 mb-4">
                <div>
                  <h4 className="font-bold text-white text-base tracking-wide">{bot.symbol}</h4>
                  <span className="text-[10px] text-neutral-500 font-mono">ID: {bot.id}</span>
                </div>
                <span className={`text-xs px-2.5 py-1 rounded font-bold uppercase tracking-wider ${
                  bot.status === "running" ? "bg-[#0ecb81]/15 text-[#0ecb81]" : "bg-neutral-800 text-neutral-400"
                }`}>
                  {bot.status === "running" ? "Çalışıyor" : "Çevrimdışı"}
                </span>
              </div>

              <div className="space-y-3.5 mb-6 text-sm">
                <div className="flex justify-between border-b border-neutral-800/40 pb-2">
                  <span className="text-neutral-400">Başlangıç Bütçe:</span>
                  <strong className="text-white">${bot.budget_usd}</strong>
                </div>
                <div className="flex justify-between border-b border-neutral-800/40 pb-2">
                  <span className="text-neutral-400">Anlık Hacim Değeri:</span>
                  <strong className="text-white">${bot.current_usd?.toFixed(2)}</strong>
                </div>
                <div className="flex justify-between border-b border-neutral-800/40 pb-2">
                  <span className="text-neutral-400">Toplam Döngüler:</span>
                  <strong className="text-white">#{bot.total_cycles_completed}</strong>
                </div>
                <div className="flex justify-between">
                  <span className="text-neutral-400">Net Kâr / Zarar:</span>
                  <strong className={`${profitColor} font-bold`}>{bot.total_pnl_pct >= 0 ? '+' : ''}{bot.total_pnl_pct}% (${bot.total_pnl_usd})</strong>
                </div>
              </div>

              <div className="flex gap-2">
                <button
                  onClick={() => handleToggleBot(bot.id, bot.status)}
                  className={`flex-1 py-2 font-bold rounded-lg transition text-sm flex items-center justify-center gap-1.5 ${
                    bot.status === "running" 
                      ? "bg-[#f6465d]/10 hover:bg-[#f6465d]/20 text-[#f6465d] border border-[#f6465d]/20" 
                      : "bg-[#0ecb81]/10 hover:bg-[#0ecb81]/20 text-[#0ecb81] border border-[#0ecb81]/20"
                  }`}
                >
                  {bot.status === "running" ? (
                    <>
                      <Square className="w-3.5 h-3.5 fill-[#f6465d]" /> Durdur
                    </>
                  ) : (
                    <>
                      <Play className="w-3.5 h-3.5 fill-[#0ecb81]" /> Başlat
                    </>
                  )}
                </button>
              </div>
            </div>
          );
        })}
      </div>

      {/* Bot Create Wizard Overlay Modal */}
      {showCreateWizard && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-neutral-900 border border-neutral-800 rounded-2xl max-w-2xl w-full p-6 space-y-4 shadow-2xl relative">
            <button
              onClick={() => setShowCreateWizard(false)}
              className="absolute right-4 top-4 text-neutral-400 hover:text-white font-bold text-lg"
            >
              ✕
            </button>

            <h3 className="text-xl font-bold text-white mb-2 flex items-center">
              <Cpu className="w-5 h-5 text-[#f0b90b] mr-2" /> Trailing DCA Bot Oluşturucu
            </h3>

            {/* Stepper Header */}
            <div className="flex items-center justify-between border-b border-neutral-800 pb-3 text-xs font-semibold text-neutral-400">
              <span className={currentStep === 1 ? "text-[#f0b90b] font-bold" : ""}>1. Genel</span>
              <span>➔</span>
              <span className={currentStep === 2 ? "text-[#f0b90b] font-bold" : ""}>2. Dağılım</span>
              <span>➔</span>
              <span className={currentStep === 3 ? "text-[#f0b90b] font-bold" : ""}>3. Yukarı Grid</span>
              <span>➔</span>
              <span className={currentStep === 4 ? "text-[#f0b90b] font-bold text-bold" : ""}>4. Aşağı Grid</span>
              <span>➔</span>
              <span className={currentStep === 5 ? "text-[#f0b90b] font-bold text-bold" : ""}>5. Tetikler</span>
            </div>

            {wizardError && (
              <div className="bg-[#f6465d]/10 border border-[#f6465d]/30 text-[#f6465d] text-xs p-3 rounded-lg flex items-center gap-1.5">
                <AlertTriangle className="w-4 h-4 shrink-0" />
                <span>{wizardError}</span>
              </div>
            )}

            {/* Wizard step contents */}
            <div className="min-height-[240px] space-y-4 py-2">
              {currentStep === 1 && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="space-y-1.5">
                    <label className="text-xs font-semibold text-neutral-400">İşlem Çifti</label>
                    <input
                      type="text"
                      value={form.symbol}
                      onChange={e => setForm({ ...form, symbol: e.target.value.toUpperCase() })}
                      className="w-full bg-[#1e2026] text-white border border-neutral-800 rounded-lg p-2.5 text-sm"
                      placeholder="BTCUSDT"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-xs font-semibold text-neutral-400">Bot Bakiyesi (USDT)</label>
                    <input
                      type="number"
                      value={form.budget_usd}
                      onChange={e => setForm({ ...form, budget_usd: parseFloat(e.target.value) || 0 })}
                      className="w-full bg-[#1e2026] text-white border border-neutral-800 rounded-lg p-2.5 text-sm"
                      placeholder="Kullanılabilir: 8120.50"
                    />
                    <span className="text-[10px] text-neutral-500">Mevcut Bakiye: ${availableUSDT.toFixed(2)}</span>
                  </div>
                </div>
              )}

              {currentStep === 2 && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="space-y-1.5">
                    <label className="text-xs font-semibold text-neutral-400">Base % (Coin Yatırımı)</label>
                    <input
                      type="number"
                      value={form.base_pct}
                      onChange={e => setForm({ ...form, base_pct: parseFloat(e.target.value) || 0, quote_pct: 100 - (parseFloat(e.target.value) || 0) })}
                      className="w-full bg-[#1e2026] text-white border border-neutral-800 rounded-lg p-2.5 text-sm"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-xs font-semibold text-neutral-400">Quote % (Yedek USDT)</label>
                    <input
                      type="number"
                      value={form.quote_pct}
                      readOnly
                      className="w-full bg-neutral-800 text-neutral-500 border border-neutral-700 rounded-lg p-2.5 text-sm cursor-not-allowed"
                    />
                  </div>
                </div>
              )}

              {currentStep === 3 && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="space-y-1.5">
                    <label className="text-xs font-semibold text-neutral-400">Grid Sayısı</label>
                    <input
                      type="number"
                      value={form.upCount}
                      onChange={e => setForm({ ...form, upCount: parseInt(e.target.value) || 0 })}
                      className="w-full bg-[#1e2026] text-white border border-neutral-800 rounded-lg p-2.5 text-sm"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-xs font-semibold text-neutral-400">Trailing % (Tepe Arama)</label>
                    <input
                      type="number"
                      value={form.upTrail}
                      step="0.01"
                      onChange={e => setForm({ ...form, upTrail: parseFloat(e.target.value) || 0 })}
                      className="w-full bg-[#1e2026] text-white border border-neutral-800 rounded-lg p-2.5 text-sm"
                    />
                  </div>
                </div>
              )}

              {currentStep === 4 && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="space-y-1.5">
                    <label className="text-xs font-semibold text-neutral-400">Grid Sayısı</label>
                    <input
                      type="number"
                      value={form.downCount}
                      onChange={e => {
                        const downCount = parseInt(e.target.value) || 0;
                        setForm({ ...form, downCount, maxBuyLevels: Math.min(Math.max(1, form.maxBuyLevels), Math.max(1, downCount)) });
                      }}
                      className="w-full bg-[#1e2026] text-white border border-neutral-800 rounded-lg p-2.5 text-sm"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-xs font-semibold text-neutral-400">Trailing % (Dip Arama)</label>
                    <input
                      type="number"
                      value={form.downTrail}
                      step="0.01"
                      onChange={e => setForm({ ...form, downTrail: parseFloat(e.target.value) || 0 })}
                      className="w-full bg-[#1e2026] text-white border border-neutral-800 rounded-lg p-2.5 text-sm"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-xs font-semibold text-neutral-400">Maksimum Alış Seviyesi</label>
                    <input
                      type="number"
                      min={1}
                      max={Math.max(1, form.downCount)}
                      value={form.maxBuyLevels}
                      onChange={e => setForm({ ...form, maxBuyLevels: Math.min(parseInt(e.target.value) || 1, Math.max(1, form.downCount)) })}
                      className="w-full bg-[#1e2026] text-white border border-neutral-800 rounded-lg p-2.5 text-sm"
                    />
                  </div>
                </div>
              )}

              {currentStep === 5 && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="space-y-1.5">
                    <label className="text-xs font-semibold text-neutral-400">Kar Alımı (Rebuy) Tetik %</label>
                    <input
                      type="number"
                      value={form.rebuyTrigger}
                      step="0.01"
                      onChange={e => setForm({ ...form, rebuyTrigger: parseFloat(e.target.value) || 0 })}
                      className="w-full bg-[#1e2026] text-white border border-neutral-800 rounded-lg p-2.5 text-sm"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-xs font-semibold text-neutral-400">Rebuy Trailing %</label>
                    <input
                      type="number"
                      value={form.rebuyTrail}
                      step="0.01"
                      onChange={e => setForm({ ...form, rebuyTrail: parseFloat(e.target.value) || 0 })}
                      className="w-full bg-[#1e2026] text-white border border-neutral-800 rounded-lg p-2.5 text-sm"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-xs font-semibold text-neutral-400">Kar Satışı (Resell) Tetik %</label>
                    <input
                      type="number"
                      value={form.resellTrigger}
                      step="0.01"
                      onChange={e => setForm({ ...form, resellTrigger: parseFloat(e.target.value) || 0 })}
                      className="w-full bg-[#1e2026] text-white border border-neutral-800 rounded-lg p-2.5 text-sm"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-xs font-semibold text-neutral-400">Resell Trailing %</label>
                    <input
                      type="number"
                      value={form.resellTrail}
                      step="0.01"
                      onChange={e => setForm({ ...form, resellTrail: parseFloat(e.target.value) || 0 })}
                      className="w-full bg-[#1e2026] text-white border border-neutral-800 rounded-lg p-2.5 text-sm"
                    />
                  </div>
                </div>
              )}
            </div>

            {/* Step navigation actions */}
            <div className="flex justify-end gap-3 border-t border-neutral-800 pt-4">
              {currentStep > 1 && (
                <button
                  onClick={handlePrevStep}
                  className="px-4 py-2 bg-neutral-800 hover:bg-neutral-700 text-neutral-300 font-semibold rounded-lg text-sm transition"
                >
                  Geri
                </button>
              )}
              {currentStep < 5 ? (
                <button
                  onClick={handleNextStep}
                  className="px-5 py-2 bg-[#f0b90b] hover:bg-[#c9930a] text-neutral-900 font-bold rounded-lg text-sm transition"
                >
                  Devam Et
                </button>
              ) : (
                <button
                  onClick={handleCreateBot}
                  className="px-6 py-2 bg-[#0ecb81] hover:bg-[#0ca86a] text-white font-bold rounded-lg text-sm transition"
                >
                  Botu Başlat &amp; Bitir
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
