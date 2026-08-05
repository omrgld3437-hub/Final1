import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const studio = readFileSync(resolve(root, "src/features/bots/BotCreateStudio.tsx"), "utf8");
const assistant = readFileSync(resolve(root, "src/features/assistant/ParamAssistantPanel.tsx"), "utf8");
const botsTab = readFileSync(resolve(root, "src/components/BotsTab.tsx"), "utf8");
const app = readFileSync(resolve(root, "src/App.tsx"), "utf8");

assert.match(studio, /top-\[env\(safe-area-inset-top\)\]/, "Bot oluşturma modalı iOS üst güvenli alanını korumalı.");
assert.match(studio, /relative flex h-full/, "Mobil modal kullanılabilir güvenli yüksekliğe sığmalı.");
assert.doesNotMatch(assistant, /Bu profil referans \/ koşullu plandır/);
assert.doesNotMatch(assistant, /parametre ile indikatör/);
assert.match(assistant, /aria-busy=\{loading\}/);
assert.match(assistant, /LoaderCircle/);
// V6 net_profile_library: calculate returns sealed 4+4 ui_config; /advice strips it.
assert.match(assistant, /\/api\/param-assistant\/calculate/);
assert.doesNotMatch(assistant, /\/api\/param-assistant\/advice/);
assert.match(assistant, /Forma uygula/);
assert.match(assistant, /first_start_buy_only:\s*false/);
assert.match(assistant, /Seçilen profil/);
assert.match(assistant, /Kademeli satış planı/);
assert.match(assistant, /Kademeli alış planı/);
assert.match(assistant, /Dağılım haritası/);
assert.match(assistant, /Tetik mesafesi/);
assert.match(assistant, /Kullanılacak pay/);
assert.match(assistant, /Kâr satışı tetiği/);
assert.match(assistant, /Kâr alışı tetiği/);
assert.doesNotMatch(assistant, /V6 · 4\+4/);
assert.doesNotMatch(assistant, /Analiz güveni/);
assert.doesNotMatch(assistant, /Coin bazlı piyasa rejimi/);
assert.doesNotMatch(assistant, /forma otomatik parametre uygulamaz/);
assert.match(studio, /symbol\.endsWith\("USDT"\)/, "Bot parite önerileri yalnız USDT olmalı.");
assert.match(studio, /function NumericInput/, "Mobil sayı alanları boş ara değeri koruyan ortak girişi kullanmalı.");
assert.match(studio, /type="text"\s+inputMode=\{inputMode\}/, "Mobil sayı klavyesi kontrollü metin girişiyle açılmalı.");
assert.match(studio, /entered === "0" \? "0," : entered/, "Ondalık kutusunda sıfırdan sonra virgül otomatik hazırlanmalı.");
assert.match(studio, /label="Grid adeti"/, "Grid sayacı anlaşılır adla gösterilmeli.");
assert.match(studio, /mt-4 hidden grid-cols-4.*sm:grid/, "Dört aşamalı grid bilgi şeridi mobilde gizlenmeli.");
assert.doesNotMatch(studio, /title="Bakiye koruması"/, "Bakiye koruması özet kartı kaldırılmalı.");
assert.match(
  studio,
  /Dinamik mod açık\.|Bot her turda girdiğiniz sabit parametreleri kullanır/,
  "Dinamik mod kısa durum metnini göstermeli.",
);
assert.doesNotMatch(
  studio,
  /Her turda Parametre Asistanı planı uygulanır/,
);
assert.doesNotMatch(studio, /PARAMETRE MOTORU/);
assert.doesNotMatch(studio, /ÇARPAN MODELİ AÇIK/);
assert.doesNotMatch(studio, /çarpanlı/);
assert.match(
  studio,
  /errorRef|scrollIntoView|scrollAreaRef/,
  "Doğrulama uyarısı mobilde görünür alana kaydırılmalı.",
);
assert.doesNotMatch(studio, /ayserose bot stüdyosu/i);
assert.doesNotMatch(studio, /Trailing DCA stratejini tasarla/);
assert.doesNotMatch(studio, /Karar korundu/);
assert.doesNotMatch(studio, /Uygulanan parametrelerin tamamını göster/);
assert.doesNotMatch(studio, /Grid mimarisi/);
assert.doesNotMatch(
  assistant,
  /result\.automatic_apply_label|result\.risk_display_label/,
);
assert.match(assistant, /ui_config values are already percent points/);
// Trailing is percent points (0.75 = %0.75). Never scale ≤1 values with ×100.
assert.doesNotMatch(
  assistant,
  /numeric\s*<=\s*1\s*&&\s*numeric\s*!==\s*0\s*\?\s*numeric\s*\*\s*100/,
);
assert.match(botsTab, /İlk botunuzu aşağıdaki butona basarak tasarlayın/);
assert.doesNotMatch(botsTab, /İlk stratejin için alan hazır/);
assert.doesNotMatch(botsTab, /Bütçe, grid ve trailing kararlarını görünür tutan bot stüdyosuyla başla/);
assert.doesNotMatch(botsTab, /Canlı durum, motor sağlığı ve performans aynı yüzeyde/);
assert.match(botsTab, /createPortal\(/, "Bot oluşturma penceresi sayfa yüzeyinden ayrılmalı.");
assert.match(botsTab, /onStudioOpenChange/, "Pencere durumu üst yönlendirmeye bildirilmeli.");
assert.match(botsTab, /useState<SortDirection>\("desc"\)/, "Botlar ilk açılışta en yüksek performans üstte başlamalı.");
assert.match(botsTab, /<ArrowUp className="h-5 w-5"/);
assert.match(botsTab, /<ArrowDown className="h-5 w-5"/);
assert.doesNotMatch(botsTab, /TrendingUp/);
assert.match(botsTab, /Botunuz oluşturuluyor\./);
assert.match(botsTab, /botunuz başarıyla çalıştırıldı\./);
assert.match(botsTab, /setCreationFeedbackLeaving\(true\)[\s\S]*?3_000/);
assert.match(app, /inert=\{botStudioOpen \|\| undefined\}/, "Açık pencerede arka plan etkileşimi kapanmalı.");
assert.match(app, /if \(botStudioOpenRef\.current\) return;/, "Açık pencerede bot detay yönlendirmesi engellenmeli.");

console.log("Bot create mobile safety contract: OK");
