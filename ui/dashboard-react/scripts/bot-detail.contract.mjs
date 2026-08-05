import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const source = readFileSync(resolve(root, "src/features/bots/BotDetailPage.tsx"), "utf8");
const formatter = source.match(/function dateTimeMinute[\s\S]*?\n}\n/)?.[0] || "";

assert.ok(formatter, "Saniyesiz bot başlangıç tarihi biçimleyicisi bulunamadı.");
assert.doesNotMatch(formatter, /dateStyle\s*:/, "dateStyle; hour/minute ile birlikte kullanılamaz.");
assert.match(formatter, /day:\s*"2-digit"/);
assert.match(formatter, /month:\s*"2-digit"/);
assert.match(formatter, /year:\s*"numeric"/);
assert.match(formatter, /hour:\s*"2-digit"/);
assert.match(formatter, /minute:\s*"2-digit"/);

assert.doesNotThrow(() =>
  new Intl.DateTimeFormat("tr-TR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date("2026-07-22T05:32:00+03:00")),
);

assert.match(source, /Tur süresi/, "Aktif tur süresi özette gösterilmeli.");
assert.match(source, /Tur sayısı/, "Tur sayısı kutusu özette gösterilmeli.");
assert.match(source, /label="Referans fiyat"/, "Her seçili turun referans fiyat kartı gösterilmeli.");
assert.match(source, /function shortMainRegime/);
assert.match(source, /MAIN_REGIME_DETAILS/);
assert.match(source, /function heroBalance/);
assert.match(source, /Bu turun parametreleri/);
assert.match(source, /BarChart3[\s\S]{0,120}Performans/, "Performans özet sekmesinde başlık olarak kalmalı.");
assert.doesNotMatch(source, /id:\s*"performance"/);
assert.doesNotMatch(source, /İşlem başına ortalama/);
assert.doesNotMatch(source, /Profil · \$\{profileKey\}/);
assert.doesNotMatch(
  source,
  /Dinamik modda her tur başında motor planı yenilenir/,
);
assert.match(source, /grid grid-cols-3 gap-1 border-t/, "Bot detay sekmeleri hizalı olmalı.");
assert.match(source, /price_24h_change_pct/);
assert.match(source, /trades\.cycle_summary\.is_open !== true/);
assert.match(source, /R8: "Sert düşüş var"/);
assert.match(source, /const directionPending = direction\.includes\("İki yön"\)/);
assert.match(source, /trigger_pct_from_reference/);
assert.doesNotMatch(source, /Tur referansı/);
assert.match(source, /label={`Tetik fiyatı/);
assert.doesNotMatch(source, /Dip \/ anchor|Tepe \/ anchor/);
assert.match(source, /\{percent\(triggerPct\)\}/);
assert.match(source, /function TradeActivityCard/, "İşlemler gelişmiş kartlarla sunulmalı.");
assert.match(source, /const displayedFee =/);
assert.match(source, /trade\.fee_raw/);
assert.match(source, /selectedCycle === 1 && initialBuyTrade/, "Başlangıç alımı yalnız ilk turda görünmeli.");
assert.match(source, /Takip tepesi/);
assert.match(source, /Takip dibi/);
assert.match(source, /label="Toplam kazanç"/);
assert.match(
  source,
  /balance_end_usd \?\? performance\.total_usd/,
  "Toplam kazanç tutarı bakiyeden hesaplanmalı.",
);
assert.match(source, /label="Günlük kazanç"/);
assert.match(source, /Trailing ·/);
assert.match(source, /Kâr alışı/);
assert.match(source, /Kâr satışı/);
assert.match(source, /Trail \{percent\(trailingPct\)\}/);
assert.doesNotMatch(source, /label="Bakiye değişimi"/);
assert.match(source, /Alpha performansı/);
assert.match(source, /Komisyon etkisi/);
assert.match(source, /label="Tahmini yıllık USDT getirisi"/);
assert.match(source, /function CycleParametersCard/);
assert.match(source, /Aktif turun uygulanan parametreleri/);
assert.doesNotMatch(source, /getBotPerformanceChart/);
assert.doesNotMatch(source, /PerformanceChartView/);
assert.doesNotMatch(source, /Bot ve piyasa karşılaştırması/);
assert.doesNotMatch(source, /Gündelik kazanç/);
assert.match(source, /Kesinleşen tur kazancı/);
assert.match(source, /label="USDT kazancı"/);
assert.match(source, /inventory_pnl_coin/);
assert.match(source, /Toplam \{completedCycleCount\} tur tamamlandı/);
assert.match(source, /xl:grid-cols-3/, "Altı strateji kartı masaüstünde simetrik 3x2 dizilmeli.");
assert.match(source, /Ortalama alış maliyeti/);
assert.match(source, /Ortalama satış maliyeti/);
assert.match(source, /cashClosedCycles > 0/);
assert.match(source, /coinClosedCycles > 0/);
assert.doesNotMatch(source, /Tamamlanma · referansa göre/);
assert.match(source, /function coinPrice/);
assert.match(
  source,
  /directionPending[\s\S]*?\? "text-white"/,
  "İki yön bekleme aşaması başlığı beyaz olmalı.",
);
assert.doesNotMatch(source, /Son fiyat/);
assert.match(source, /planned_quote_usd/);
assert.match(source, /planned_base_qty/);
assert.match(source, /const profitAmountLabel = profitRebuy \? "Alış tutarı" : "Satış miktarı"/);
assert.doesNotMatch(source, /"Döngü miktarı"/);

console.log("Bot detail rendering contract: OK");
