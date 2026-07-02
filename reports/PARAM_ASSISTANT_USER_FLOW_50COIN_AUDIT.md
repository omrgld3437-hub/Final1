# Parametre Asistanı 50 Coin Kullanıcı Akışı Audit Raporu

**Tarih:** 2026-06-27 15:30 UTC
**Test modu:** test-local
**Toplam coin:** 50
**Bütçe senaryoları:** 50 / 100 / 1000 USDT
**Toplam analiz:** 150
**Başarılı analiz:** 150
**Hatalı analiz:** 0

## Genel özet

| Metrik | Değer |
|--------|------:|
| deployable_grid | 0 |
| controlled_grid | 8 |
| restricted_deployable_grid | 0 |
| recommended_grid | 36 |
| no_trade | 18 |
| management_decision | 0 |
| single_probe | 0 |
| min_notional_limited_grid | 62 |
| first_start_buy_only | 26 |
| exact_v5_hit | 150 |
| fallback_used | 0 |
| runtime_used | 0 |
| symbol_substitutions | 0 |
| blocker_count | 0 |
| critical_count | 0 |
| warning_count | 0 |

## Kritik hata özeti

| Hata | Sayı |
|------|-----:|
| MIN_NOTIONAL_LIMITED_EXPECTED | 29 |

## En kötü 20 sonuç

| Sıra | Coin | Bütçe | Final | Güven | Hata | En büyük hata |
|-----:|------|------:|-------|------:|-----:|---------------|
| 1 | BTCUSDT | 50.0 | min_notional_limited_grid | 28 | 1 | MIN_NOTIONAL_LIMITED_EXPECTED |
| 2 | ETHUSDT | 50.0 | min_notional_limited_grid | 27 | 1 | MIN_NOTIONAL_LIMITED_EXPECTED |
| 3 | SOLUSDT | 50.0 | min_notional_limited_grid | 28 | 1 | MIN_NOTIONAL_LIMITED_EXPECTED |
| 4 | BNBUSDT | 50.0 | min_notional_limited_grid | 28 | 1 | MIN_NOTIONAL_LIMITED_EXPECTED |
| 5 | XRPUSDT | 50.0 | min_notional_limited_grid | 28 | 1 | MIN_NOTIONAL_LIMITED_EXPECTED |
| 6 | AVAXUSDT | 50.0 | min_notional_limited_grid | 27 | 1 | MIN_NOTIONAL_LIMITED_EXPECTED |
| 7 | DOGEUSDT | 50.0 | min_notional_limited_grid | 27 | 1 | MIN_NOTIONAL_LIMITED_EXPECTED |
| 8 | LINKUSDT | 50.0 | min_notional_limited_grid | 26 | 1 | MIN_NOTIONAL_LIMITED_EXPECTED |
| 9 | LTCUSDT | 50.0 | min_notional_limited_grid | 28 | 1 | MIN_NOTIONAL_LIMITED_EXPECTED |
| 10 | TRXUSDT | 50.0 | min_notional_limited_grid | 26 | 1 | MIN_NOTIONAL_LIMITED_EXPECTED |
| 11 | INJUSDT | 50.0 | min_notional_limited_grid | 29 | 1 | MIN_NOTIONAL_LIMITED_EXPECTED |
| 12 | SUIUSDT | 50.0 | min_notional_limited_grid | 28 | 1 | MIN_NOTIONAL_LIMITED_EXPECTED |
| 13 | SEIUSDT | 50.0 | min_notional_limited_grid | 27 | 1 | MIN_NOTIONAL_LIMITED_EXPECTED |
| 14 | SEIUSDT | 100.0 | min_notional_limited_grid | 27 | 1 | MIN_NOTIONAL_LIMITED_EXPECTED |
| 15 | AAVEUSDT | 50.0 | min_notional_limited_grid | 34 | 1 | MIN_NOTIONAL_LIMITED_EXPECTED |
| 16 | UNIUSDT | 50.0 | min_notional_limited_grid | 26 | 1 | MIN_NOTIONAL_LIMITED_EXPECTED |
| 17 | WLDUSDT | 50.0 | min_notional_limited_grid | 30 | 1 | MIN_NOTIONAL_LIMITED_EXPECTED |
| 18 | ICPUSDT | 50.0 | min_notional_limited_grid | 25 | 1 | MIN_NOTIONAL_LIMITED_EXPECTED |
| 19 | ICPUSDT | 100.0 | min_notional_limited_grid | 25 | 1 | MIN_NOTIONAL_LIMITED_EXPECTED |
| 20 | GALAUSDT | 50.0 | min_notional_limited_grid | 29 | 1 | MIN_NOTIONAL_LIMITED_EXPECTED |

## En iyi 20 sonuç

| Sıra | Coin | Bütçe | Final | Güven | Neden iyi |
|-----:|------|------:|-------|------:|-----------|
| 1 | AGLDUSDT | 1000.0 | recommended_grid | 62 | anomaly yok |
| 2 | AGLDUSDT | 100.0 | first_start_buy_only | 60 | anomaly yok |
| 3 | AAVEUSDT | 100.0 | first_start_buy_only | 55 | anomaly yok |
| 4 | AAVEUSDT | 1000.0 | recommended_grid | 55 | anomaly yok |
| 5 | JTOUSDT | 100.0 | first_start_buy_only | 55 | anomaly yok |
| 6 | JTOUSDT | 1000.0 | recommended_grid | 55 | anomaly yok |
| 7 | NEARUSDT | 100.0 | first_start_buy_only | 53 | anomaly yok |
| 8 | NEARUSDT | 1000.0 | recommended_grid | 53 | anomaly yok |
| 9 | DOTUSDT | 1000.0 | recommended_grid | 52 | anomaly yok |
| 10 | SEIUSDT | 1000.0 | recommended_grid | 52 | anomaly yok |
| 11 | DOTUSDT | 100.0 | first_start_buy_only | 50 | anomaly yok |
| 12 | ARBUSDT | 1000.0 | recommended_grid | 50 | anomaly yok |
| 13 | OPUSDT | 1000.0 | recommended_grid | 50 | anomaly yok |
| 14 | WLDUSDT | 100.0 | first_start_buy_only | 50 | anomaly yok |
| 15 | WLDUSDT | 1000.0 | recommended_grid | 50 | anomaly yok |
| 16 | SANDUSDT | 1000.0 | recommended_grid | 50 | anomaly yok |
| 17 | XRPUSDT | 100.0 | first_start_buy_only | 49 | anomaly yok |
| 18 | INJUSDT | 100.0 | first_start_buy_only | 49 | anomaly yok |
| 19 | INJUSDT | 1000.0 | recommended_grid | 49 | anomaly yok |
| 20 | GALAUSDT | 1000.0 | recommended_grid | 49 | anomaly yok |

## BTCUSDT — 50.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: BTCUSDT
- Kategori: Majors
- Girilen bütçe: 50.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 28/100
- Parametre skoru: 64/100
- Route: `A1|R5|D1|S4|V2|K2|L1`
- Shelf: `DPLV5_A1_R5_D1_S4_V2_K2_L1`

### Piyasa Özeti

- Rejim metni: Kırılım öncesi sıkışma · Üst tepeler · normal kontrollü
- Spread: 1.646e-05%
- RSI 5m/1h: 62.68833625 / 61.8021417
- BTC risk skoru: 70
- Vol persentil: 32.76553106
- Crash hızı: -0.18604575

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %58.0 · USDT %42.0

### Güvenlik

- Max exposure: %62.02
- Worst exposure: %100.0
- Aktif alış bütçesi: 21.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| INFO | MIN_NOTIONAL_LIMITED_EXPECTED | Piyasa tamamen kötü değil; bütçe/min-notional nedeniyle kontrollü grid beklenmiyor. | min_notional_limited_grid |

### Ham cevap özeti

```
Parametre Skoru 64/100. Rejim Kırılım öncesi sıkışma / kırılım hazırlığı. Risk durumu normal kontrollü. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## BTCUSDT — 100.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: BTCUSDT
- Kategori: Majors
- Girilen bütçe: 100.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: first_start_buy_only
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 48/100
- Parametre skoru: 64/100
- Route: `A1|R5|D1|S4|V2|K2|L1`
- Shelf: `DPLV5_A1_R5_D1_S4_V2_K2_L1`

### Piyasa Özeti

- Rejim metni: Kırılım öncesi sıkışma · Üst tepeler · normal kontrollü
- Spread: 1.647e-05%
- RSI 5m/1h: 62.68833625 / 61.8021417
- BTC risk skoru: 70
- Vol persentil: 32.76553106
- Crash hızı: -0.18604575

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %58.0 · USDT %42.0

### Güvenlik

- Max exposure: %62.02
- Worst exposure: %58.0
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 64/100. Rejim Kırılım öncesi sıkışma / kırılım hazırlığı. Risk durumu normal kontrollü. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## BTCUSDT — 1000.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: BTCUSDT
- Kategori: Majors
- Girilen bütçe: 1000.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: controlled_grid
- Deployable: evet
- Final action: CONTROLLED_GRID
- Güven: 46/100
- Parametre skoru: 64/100
- Route: `A1|R5|D1|S4|V2|K2|L1`
- Shelf: `DPLV5_A1_R5_D1_S4_V2_K2_L1`

### Piyasa Özeti

- Rejim metni: Kırılım öncesi sıkışma · Üst tepeler · normal kontrollü
- Spread: 1.647e-05%
- RSI 5m/1h: 62.68833625 / 61.8021417
- BTC risk skoru: 70
- Vol persentil: 32.76553106
- Crash hızı: -0.18604575

### Grid Özeti

- Alış: 2 kademe · dağılım [30.0, 70.0]
- Satış: 3 kademe · dağılım [15.0, 35.0, 50.0]
- Hedef: coin %58.0 · USDT %42.0

### Güvenlik

- Max exposure: %62.02
- Worst exposure: %61.67
- Aktif alış bütçesi: 36.69 USDT
- Fee bad: True
- Güvenlik sonucu: Kontrollü grid / fee verisi eksik

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 64/100. Rejim Kırılım öncesi sıkışma / kırılım hazırlığı, risk durumu normal kontrollü. Risk skoru 48/100, fırsat skoru 59/100. Volatilite 40, BTC piyasa riski 70. . Base tahsisi %58.0, quote %42.0, maksimum base exposure %62.0 ile sınırlandı. Alışlar 2 kademeye bölündü; grid aralığı alış %2.48 / satış %2.97. Dengeleme: Base/quote hedefi anlamlı değişti ancak piyasa güvenlik koşulları uygun olmadığı için rebalance ertelendi (fee_bad).
```

## ETHUSDT — 50.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: ETHUSDT
- Kategori: Majors
- Girilen bütçe: 50.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 27/100
- Parametre skoru: 62/100
- Route: `A2|R2|D1|S4|V2|K1|L2`
- Shelf: `DPLV5_A2_R2_D1_S4_V2_K1_L2`

### Piyasa Özeti

- Rejim metni: Dengeli aralık · Üst tepeler · savunmacı
- Spread: 0.00062467%
- RSI 5m/1h: 62.64131787 / 65.13463898
- BTC risk skoru: 70
- Vol persentil: 45.59118236
- Crash hızı: -0.24393887

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %44.64 · USDT %55.36

### Güvenlik

- Max exposure: %44.64
- Worst exposure: %100.0
- Aktif alış bütçesi: 27.68 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| INFO | MIN_NOTIONAL_LIMITED_EXPECTED | Piyasa tamamen kötü değil; bütçe/min-notional nedeniyle kontrollü grid beklenmiyor. | min_notional_limited_grid |

### Ham cevap özeti

```
Parametre Skoru 62/100. Rejim Dengeli aralık. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## ETHUSDT — 100.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: ETHUSDT
- Kategori: Majors
- Girilen bütçe: 100.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: first_start_buy_only
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 47/100
- Parametre skoru: 62/100
- Route: `A2|R2|D1|S4|V2|K1|L2`
- Shelf: `DPLV5_A2_R2_D1_S4_V2_K1_L2`

### Piyasa Özeti

- Rejim metni: Dengeli aralık · Üst tepeler · savunmacı
- Spread: 0.00062467%
- RSI 5m/1h: 62.64131787 / 65.13463898
- BTC risk skoru: 70
- Vol persentil: 45.59118236
- Crash hızı: -0.24393887

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %44.64 · USDT %55.36

### Güvenlik

- Max exposure: %44.64
- Worst exposure: %44.64
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 62/100. Rejim Dengeli aralık. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## ETHUSDT — 1000.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: ETHUSDT
- Kategori: Majors
- Girilen bütçe: 1000.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: recommended_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 47/100
- Parametre skoru: 62/100
- Route: `A2|R2|D1|S4|V2|K1|L2`
- Shelf: `DPLV5_A2_R2_D1_S4_V2_K1_L2`

### Piyasa Özeti

- Rejim metni: Dengeli aralık · Üst tepeler · savunmacı
- Spread: 0.00062448%
- RSI 5m/1h: 62.64131787 / 65.13463898
- BTC risk skoru: 70
- Vol persentil: 45.59118236
- Crash hızı: -0.24393887

### Grid Özeti

- Alış: 3 kademe · dağılım []
- Satış: 3 kademe · dağılım []
- Hedef: coin %44.64 · USDT %55.36

### Güvenlik

- Max exposure: %44.64
- Worst exposure: %44.64
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 62/100. Rejim Dengeli aralık. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## SOLUSDT — 50.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: SOLUSDT
- Kategori: Majors
- Girilen bütçe: 50.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 28/100
- Parametre skoru: 63/100
- Route: `A3|R3|D1|S4|V3|K2|L1`
- Shelf: `DPLV5_A3_R3_D1_S4_V3_K2_L1`

### Piyasa Özeti

- Rejim metni: Düşük volatilite sıkışma · Üst tepeler · normal kontrollü
- Spread: 0.01372024%
- RSI 5m/1h: 63.59011693 / 64.20713952
- BTC risk skoru: 70
- Vol persentil: 22.84569138
- Crash hızı: -0.16431603

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %51.0 · USDT %49.0

### Güvenlik

- Max exposure: %53.2
- Worst exposure: %100.0
- Aktif alış bütçesi: 24.5 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| INFO | MIN_NOTIONAL_LIMITED_EXPECTED | Piyasa tamamen kötü değil; bütçe/min-notional nedeniyle kontrollü grid beklenmiyor. | min_notional_limited_grid |

### Ham cevap özeti

```
Parametre Skoru 63/100. Rejim Düşük volatilite sıkışma. Risk durumu normal kontrollü. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## SOLUSDT — 100.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: SOLUSDT
- Kategori: Majors
- Girilen bütçe: 100.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: first_start_buy_only
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 48/100
- Parametre skoru: 63/100
- Route: `A3|R3|D1|S4|V3|K2|L1`
- Shelf: `DPLV5_A3_R3_D1_S4_V3_K2_L1`

### Piyasa Özeti

- Rejim metni: Düşük volatilite sıkışma · Üst tepeler · normal kontrollü
- Spread: 0.01372024%
- RSI 5m/1h: 63.59011693 / 64.20713952
- BTC risk skoru: 70
- Vol persentil: 22.84569138
- Crash hızı: -0.16431603

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %51.0 · USDT %49.0

### Güvenlik

- Max exposure: %53.2
- Worst exposure: %51.0
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 63/100. Rejim Düşük volatilite sıkışma. Risk durumu normal kontrollü. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## SOLUSDT — 1000.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: SOLUSDT
- Kategori: Majors
- Girilen bütçe: 1000.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: controlled_grid
- Deployable: evet
- Final action: CONTROLLED_GRID
- Güven: 45/100
- Parametre skoru: 63/100
- Route: `A3|R3|D1|S4|V3|K2|L1`
- Shelf: `DPLV5_A3_R3_D1_S4_V3_K2_L1`

### Piyasa Özeti

- Rejim metni: Düşük volatilite sıkışma · Üst tepeler · normal kontrollü
- Spread: 0.01372024%
- RSI 5m/1h: 63.59011693 / 64.20713952
- BTC risk skoru: 70
- Vol persentil: 22.84569138
- Crash hızı: -0.16431603

### Grid Özeti

- Alış: 2 kademe · dağılım [40.0, 60.0]
- Satış: 3 kademe · dağılım [15.0, 35.0, 50.0]
- Hedef: coin %51.0 · USDT %49.0

### Güvenlik

- Max exposure: %53.2
- Worst exposure: %52.9
- Aktif alış bütçesi: 11.4 USDT
- Fee bad: True
- Güvenlik sonucu: Kontrollü grid / fee verisi eksik

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 63/100. Rejim Düşük volatilite sıkışma, risk durumu normal kontrollü. Risk skoru 66/100, fırsat skoru 58/100. Volatilite 40, BTC piyasa riski 70. . Base tahsisi %51.0, quote %49.0, maksimum base exposure %53.2 ile sınırlandı. Alışlar 2 kademeye bölündü; grid aralığı alış %3.34 / satış %4.00. Dengeleme: Base/quote hedefi anlamlı değişti ancak piyasa güvenlik koşulları uygun olmadığı için rebalance ertelendi (fee_bad).
```

## BNBUSDT — 50.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: BNBUSDT
- Kategori: Majors
- Girilen bütçe: 50.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 28/100
- Parametre skoru: 64/100
- Route: `A3|R2|D1|S4|V2|K2|L2`
- Shelf: `DPLV5_A3_R2_D1_S4_V2_K2_L2`

### Piyasa Özeti

- Rejim metni: Dengeli aralık · Üst tepeler · normal kontrollü
- Spread: 0.00176836%
- RSI 5m/1h: 56.61152203 / 52.06280573
- BTC risk skoru: 70
- Vol persentil: 37.1743487
- Crash hızı: -0.19063085

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %56.0 · USDT %44.0

### Güvenlik

- Max exposure: %58.9
- Worst exposure: %100.0
- Aktif alış bütçesi: 22.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| INFO | MIN_NOTIONAL_LIMITED_EXPECTED | Piyasa tamamen kötü değil; bütçe/min-notional nedeniyle kontrollü grid beklenmiyor. | min_notional_limited_grid |

### Ham cevap özeti

```
Parametre Skoru 64/100. Rejim Dengeli aralık. Risk durumu normal kontrollü. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## BNBUSDT — 100.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: BNBUSDT
- Kategori: Majors
- Girilen bütçe: 100.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: first_start_buy_only
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 48/100
- Parametre skoru: 64/100
- Route: `A3|R2|D1|S4|V2|K2|L2`
- Shelf: `DPLV5_A3_R2_D1_S4_V2_K2_L2`

### Piyasa Özeti

- Rejim metni: Dengeli aralık · Üst tepeler · normal kontrollü
- Spread: 0.00176836%
- RSI 5m/1h: 56.61152203 / 52.06280573
- BTC risk skoru: 70
- Vol persentil: 37.1743487
- Crash hızı: -0.19063085

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %56.0 · USDT %44.0

### Güvenlik

- Max exposure: %58.9
- Worst exposure: %56.0
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 64/100. Rejim Dengeli aralık. Risk durumu normal kontrollü. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## BNBUSDT — 1000.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: BNBUSDT
- Kategori: Majors
- Girilen bütçe: 1000.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: controlled_grid
- Deployable: evet
- Final action: CONTROLLED_GRID
- Güven: 46/100
- Parametre skoru: 64/100
- Route: `A3|R2|D1|S4|V2|K2|L2`
- Shelf: `DPLV5_A3_R2_D1_S4_V2_K2_L2`

### Piyasa Özeti

- Rejim metni: Dengeli aralık · Üst tepeler · normal kontrollü
- Spread: 0.00176836%
- RSI 5m/1h: 56.61152203 / 52.06280573
- BTC risk skoru: 70
- Vol persentil: 37.1743487
- Crash hızı: -0.19063085

### Grid Özeti

- Alış: 2 kademe · dağılım [40.0, 60.0]
- Satış: 3 kademe · dağılım [15.0, 35.0, 50.0]
- Hedef: coin %56.0 · USDT %44.0

### Güvenlik

- Max exposure: %58.9
- Worst exposure: %58.78
- Aktif alış bütçesi: 27.77 USDT
- Fee bad: True
- Güvenlik sonucu: Kontrollü grid / fee verisi eksik

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 64/100. Rejim Dengeli aralık, risk durumu normal kontrollü. Risk skoru 53/100, fırsat skoru 59/100. Volatilite 40, BTC piyasa riski 70. . Base tahsisi %56.0, quote %44.0, maksimum base exposure %58.9 ile sınırlandı. Alışlar 2 kademeye bölündü; grid aralığı alış %2.27 / satış %2.72. Dengeleme: Base/quote hedefi anlamlı değişti ancak piyasa güvenlik koşulları uygun olmadığı için rebalance ertelendi (fee_bad).
```

## XRPUSDT — 50.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: XRPUSDT
- Kategori: Majors
- Girilen bütçe: 50.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 28/100
- Parametre skoru: 64/100
- Route: `A3|R2|D1|S4|V2|K2|L1`
- Shelf: `DPLV5_A3_R2_D1_S4_V2_K2_L1`

### Piyasa Özeti

- Rejim metni: Dengeli aralık · Üst tepeler · normal kontrollü
- Spread: 0.00931923%
- RSI 5m/1h: 79.22657115 / 68.33879019
- BTC risk skoru: 70
- Vol persentil: 38.72745491
- Crash hızı: -0.03726477

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %56.0 · USDT %44.0

### Güvenlik

- Max exposure: %58.9
- Worst exposure: %100.0
- Aktif alış bütçesi: 22.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| INFO | MIN_NOTIONAL_LIMITED_EXPECTED | Piyasa tamamen kötü değil; bütçe/min-notional nedeniyle kontrollü grid beklenmiyor. | min_notional_limited_grid |

### Ham cevap özeti

```
Parametre Skoru 64/100. Rejim Dengeli aralık. Risk durumu normal kontrollü. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## XRPUSDT — 100.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: XRPUSDT
- Kategori: Majors
- Girilen bütçe: 100.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: first_start_buy_only
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 49/100
- Parametre skoru: 64/100
- Route: `A3|R2|D1|S4|V2|K2|L1`
- Shelf: `DPLV5_A3_R2_D1_S4_V2_K2_L1`

### Piyasa Özeti

- Rejim metni: Dengeli aralık · Üst tepeler · normal kontrollü
- Spread: 0.00931923%
- RSI 5m/1h: 79.22657115 / 68.33879019
- BTC risk skoru: 70
- Vol persentil: 38.72745491
- Crash hızı: -0.03726477

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %56.0 · USDT %44.0

### Güvenlik

- Max exposure: %58.9
- Worst exposure: %56.0
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 64/100. Rejim Dengeli aralık. Risk durumu normal kontrollü. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## XRPUSDT — 1000.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: XRPUSDT
- Kategori: Majors
- Girilen bütçe: 1000.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: controlled_grid
- Deployable: evet
- Final action: CONTROLLED_GRID
- Güven: 46/100
- Parametre skoru: 64/100
- Route: `A3|R2|D1|S4|V2|K2|L1`
- Shelf: `DPLV5_A3_R2_D1_S4_V2_K2_L1`

### Piyasa Özeti

- Rejim metni: Dengeli aralık · Üst tepeler · normal kontrollü
- Spread: 0.00931923%
- RSI 5m/1h: 79.22657115 / 68.33879019
- BTC risk skoru: 70
- Vol persentil: 38.72745491
- Crash hızı: -0.03726477

### Grid Özeti

- Alış: 2 kademe · dağılım [40.0, 60.0]
- Satış: 3 kademe · dağılım [15.0, 35.0, 50.0]
- Hedef: coin %56.0 · USDT %44.0

### Güvenlik

- Max exposure: %58.9
- Worst exposure: %58.78
- Aktif alış bütçesi: 27.77 USDT
- Fee bad: True
- Güvenlik sonucu: Kontrollü grid / fee verisi eksik

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 64/100. Rejim Dengeli aralık, risk durumu normal kontrollü. Risk skoru 46/100, fırsat skoru 62/100. Volatilite 40, BTC piyasa riski 70. . Base tahsisi %56.0, quote %44.0, maksimum base exposure %58.9 ile sınırlandı. Alışlar 2 kademeye bölündü; grid aralığı alış %2.27 / satış %2.72. Dengeleme: Base/quote hedefi anlamlı değişti ancak piyasa güvenlik koşulları uygun olmadığı için rebalance ertelendi (fee_bad).
```

## ADAUSDT — 50.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: ADAUSDT
- Kategori: Major alt
- Girilen bütçe: 50.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 26/100
- Parametre skoru: 62/100
- Route: `A3|R2|D1|S4|V3|K2|L2`
- Shelf: `DPLV5_A3_R2_D1_S4_V3_K2_L2`

### Piyasa Özeti

- Rejim metni: Dengeli aralık · Üst tepeler · normal kontrollü
- Spread: 0.06722689%
- RSI 5m/1h: 57.37366573 / 60.28841161
- BTC risk skoru: 70
- Vol persentil: 41.58316633
- Crash hızı: -0.26809651

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %56.0 · USDT %44.0

### Güvenlik

- Max exposure: %58.9
- Worst exposure: %100.0
- Aktif alış bütçesi: 22.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 62/100. Rejim Dengeli aralık. Risk durumu normal kontrollü. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## ADAUSDT — 100.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: ADAUSDT
- Kategori: Major alt
- Girilen bütçe: 100.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: first_start_buy_only
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 47/100
- Parametre skoru: 62/100
- Route: `A3|R2|D1|S4|V3|K2|L2`
- Shelf: `DPLV5_A3_R2_D1_S4_V3_K2_L2`

### Piyasa Özeti

- Rejim metni: Dengeli aralık · Üst tepeler · normal kontrollü
- Spread: 0.06722689%
- RSI 5m/1h: 57.37366573 / 60.28841161
- BTC risk skoru: 70
- Vol persentil: 41.58316633
- Crash hızı: -0.26809651

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %56.0 · USDT %44.0

### Güvenlik

- Max exposure: %58.9
- Worst exposure: %56.0
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 62/100. Rejim Dengeli aralık. Risk durumu normal kontrollü. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## ADAUSDT — 1000.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: ADAUSDT
- Kategori: Major alt
- Girilen bütçe: 1000.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: controlled_grid
- Deployable: evet
- Final action: CONTROLLED_GRID
- Güven: 44/100
- Parametre skoru: 62/100
- Route: `A3|R2|D1|S4|V3|K2|L2`
- Shelf: `DPLV5_A3_R2_D1_S4_V3_K2_L2`

### Piyasa Özeti

- Rejim metni: Dengeli aralık · Üst tepeler · normal kontrollü
- Spread: 0.06722689%
- RSI 5m/1h: 57.37366573 / 60.28841161
- BTC risk skoru: 70
- Vol persentil: 41.58316633
- Crash hızı: -0.26809651

### Grid Özeti

- Alış: 2 kademe · dağılım [40.0, 60.0]
- Satış: 3 kademe · dağılım [15.0, 35.0, 50.0]
- Hedef: coin %56.0 · USDT %44.0

### Güvenlik

- Max exposure: %58.9
- Worst exposure: %58.78
- Aktif alış bütçesi: 27.77 USDT
- Fee bad: True
- Güvenlik sonucu: Kontrollü grid / fee verisi eksik

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 62/100. Rejim Dengeli aralık, risk durumu normal kontrollü. Risk skoru 41/100, fırsat skoru 60/100. Volatilite 40, BTC piyasa riski 70. . Base tahsisi %56.0, quote %44.0, maksimum base exposure %58.9 ile sınırlandı. Alışlar 2 kademeye bölündü; grid aralığı alış %3.50 / satış %4.19. Dengeleme: Base/quote hedefi anlamlı değişti ancak piyasa güvenlik koşulları uygun olmadığı için rebalance ertelendi (fee_bad).
```

## AVAXUSDT — 50.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: AVAXUSDT
- Kategori: Major alt
- Girilen bütçe: 50.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 27/100
- Parametre skoru: 61/100
- Route: `A3|R2|D1|S4|V3|K2|L2`
- Shelf: `DPLV5_A3_R2_D1_S4_V3_K2_L2`

### Piyasa Özeti

- Rejim metni: Dengeli aralık · Üst tepeler · normal kontrollü
- Spread: 0.01507045%
- RSI 5m/1h: 62.62055749 / 61.35577207
- BTC risk skoru: 70
- Vol persentil: 38.52705411
- Crash hızı: -0.19554753

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %56.0 · USDT %44.0

### Güvenlik

- Max exposure: %58.9
- Worst exposure: %100.0
- Aktif alış bütçesi: 22.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| INFO | MIN_NOTIONAL_LIMITED_EXPECTED | Piyasa tamamen kötü değil; bütçe/min-notional nedeniyle kontrollü grid beklenmiyor. | min_notional_limited_grid |

### Ham cevap özeti

```
Parametre Skoru 61/100. Rejim Dengeli aralık. Risk durumu normal kontrollü. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## AVAXUSDT — 100.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: AVAXUSDT
- Kategori: Major alt
- Girilen bütçe: 100.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: first_start_buy_only
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 47/100
- Parametre skoru: 61/100
- Route: `A3|R2|D1|S4|V3|K2|L2`
- Shelf: `DPLV5_A3_R2_D1_S4_V3_K2_L2`

### Piyasa Özeti

- Rejim metni: Dengeli aralık · Üst tepeler · normal kontrollü
- Spread: 0.01507045%
- RSI 5m/1h: 62.62055749 / 61.35577207
- BTC risk skoru: 70
- Vol persentil: 38.52705411
- Crash hızı: -0.19554753

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %56.0 · USDT %44.0

### Güvenlik

- Max exposure: %58.9
- Worst exposure: %56.0
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 61/100. Rejim Dengeli aralık. Risk durumu normal kontrollü. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## AVAXUSDT — 1000.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: AVAXUSDT
- Kategori: Major alt
- Girilen bütçe: 1000.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: controlled_grid
- Deployable: evet
- Final action: CONTROLLED_GRID
- Güven: 44/100
- Parametre skoru: 61/100
- Route: `A3|R2|D1|S4|V3|K2|L2`
- Shelf: `DPLV5_A3_R2_D1_S4_V3_K2_L2`

### Piyasa Özeti

- Rejim metni: Dengeli aralık · Üst tepeler · normal kontrollü
- Spread: 0.01507045%
- RSI 5m/1h: 62.62055749 / 61.35577207
- BTC risk skoru: 70
- Vol persentil: 38.52705411
- Crash hızı: -0.19554753

### Grid Özeti

- Alış: 2 kademe · dağılım [40.0, 60.0]
- Satış: 3 kademe · dağılım [15.0, 35.0, 50.0]
- Hedef: coin %56.0 · USDT %44.0

### Güvenlik

- Max exposure: %58.9
- Worst exposure: %58.78
- Aktif alış bütçesi: 27.77 USDT
- Fee bad: True
- Güvenlik sonucu: Kontrollü grid / fee verisi eksik

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 61/100. Rejim Dengeli aralık, risk durumu normal kontrollü. Risk skoru 76/100, fırsat skoru 58/100. Volatilite 40, BTC piyasa riski 70. . Base tahsisi %56.0, quote %44.0, maksimum base exposure %58.9 ile sınırlandı. Alışlar 2 kademeye bölündü; grid aralığı alış %3.34 / satış %4.00. Dengeleme: Base/quote hedefi anlamlı değişti ancak piyasa güvenlik koşulları uygun olmadığı için rebalance ertelendi (fee_bad).
```

## DOGEUSDT — 50.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: DOGEUSDT
- Kategori: Meme
- Girilen bütçe: 50.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 27/100
- Parametre skoru: 62/100
- Route: `A5|R2|D1|S4|V2|K1|L2`
- Shelf: `DPLV5_A5_R2_D1_S4_V2_K1_L2`

### Piyasa Özeti

- Rejim metni: Dengeli aralık · Üst tepeler · savunmacı
- Spread: 0.01312767%
- RSI 5m/1h: 63.26469081 / 60.58902353
- BTC risk skoru: 70
- Vol persentil: 42.13426854
- Crash hızı: -0.20967108

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %36.6 · USDT %63.4

### Güvenlik

- Max exposure: %36.6
- Worst exposure: %100.0
- Aktif alış bütçesi: 31.7 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| INFO | MIN_NOTIONAL_LIMITED_EXPECTED | Piyasa tamamen kötü değil; bütçe/min-notional nedeniyle kontrollü grid beklenmiyor. | min_notional_limited_grid |

### Ham cevap özeti

```
Parametre Skoru 62/100. Rejim Dengeli aralık. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## DOGEUSDT — 100.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: DOGEUSDT
- Kategori: Meme
- Girilen bütçe: 100.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: first_start_buy_only
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 48/100
- Parametre skoru: 62/100
- Route: `A5|R2|D1|S4|V2|K1|L2`
- Shelf: `DPLV5_A5_R2_D1_S4_V2_K1_L2`

### Piyasa Özeti

- Rejim metni: Dengeli aralık · Üst tepeler · savunmacı
- Spread: 0.01312767%
- RSI 5m/1h: 63.26469081 / 60.58902353
- BTC risk skoru: 70
- Vol persentil: 42.13426854
- Crash hızı: -0.20967108

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %36.6 · USDT %63.4

### Güvenlik

- Max exposure: %36.6
- Worst exposure: %36.6
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 62/100. Rejim Dengeli aralık. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## DOGEUSDT — 1000.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: DOGEUSDT
- Kategori: Meme
- Girilen bütçe: 1000.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: recommended_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 48/100
- Parametre skoru: 62/100
- Route: `A5|R2|D1|S4|V2|K1|L2`
- Shelf: `DPLV5_A5_R2_D1_S4_V2_K1_L2`

### Piyasa Özeti

- Rejim metni: Dengeli aralık · Üst tepeler · savunmacı
- Spread: 0.01312767%
- RSI 5m/1h: 63.26469081 / 60.58902353
- BTC risk skoru: 70
- Vol persentil: 42.13426854
- Crash hızı: -0.20967108

### Grid Özeti

- Alış: 3 kademe · dağılım []
- Satış: 3 kademe · dağılım []
- Hedef: coin %36.6 · USDT %63.4

### Güvenlik

- Max exposure: %36.6
- Worst exposure: %36.6
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 62/100. Rejim Dengeli aralık. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## LINKUSDT — 50.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: LINKUSDT
- Kategori: Major alt
- Girilen bütçe: 50.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 26/100
- Parametre skoru: 60/100
- Route: `A3|R3|D1|S4|V2|K1|L2`
- Shelf: `DPLV5_A3_R3_D1_S4_V2_K1_L2`

### Piyasa Özeti

- Rejim metni: Düşük volatilite sıkışma · Üst tepeler · savunmacı
- Spread: 0.01344176%
- RSI 5m/1h: 64.55702809 / 63.47529267
- BTC risk skoru: 70
- Vol persentil: 20.84168337
- Crash hızı: -0.22794315

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %40.32 · USDT %59.68

### Güvenlik

- Max exposure: %40.32
- Worst exposure: %100.0
- Aktif alış bütçesi: 29.84 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| INFO | MIN_NOTIONAL_LIMITED_EXPECTED | Piyasa tamamen kötü değil; bütçe/min-notional nedeniyle kontrollü grid beklenmiyor. | min_notional_limited_grid |

### Ham cevap özeti

```
Parametre Skoru 60/100. Rejim Düşük volatilite sıkışma. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## LINKUSDT — 100.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: LINKUSDT
- Kategori: Major alt
- Girilen bütçe: 100.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: first_start_buy_only
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 46/100
- Parametre skoru: 60/100
- Route: `A3|R3|D1|S4|V2|K1|L2`
- Shelf: `DPLV5_A3_R3_D1_S4_V2_K1_L2`

### Piyasa Özeti

- Rejim metni: Düşük volatilite sıkışma · Üst tepeler · savunmacı
- Spread: 0.01344176%
- RSI 5m/1h: 64.55702809 / 63.47529267
- BTC risk skoru: 70
- Vol persentil: 20.84168337
- Crash hızı: -0.22794315

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %40.32 · USDT %59.68

### Güvenlik

- Max exposure: %40.32
- Worst exposure: %40.32
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 60/100. Rejim Düşük volatilite sıkışma. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## LINKUSDT — 1000.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: LINKUSDT
- Kategori: Major alt
- Girilen bütçe: 1000.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: recommended_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 46/100
- Parametre skoru: 60/100
- Route: `A3|R3|D1|S4|V2|K1|L2`
- Shelf: `DPLV5_A3_R3_D1_S4_V2_K1_L2`

### Piyasa Özeti

- Rejim metni: Düşük volatilite sıkışma · Üst tepeler · savunmacı
- Spread: 0.01344176%
- RSI 5m/1h: 64.55702809 / 63.47529267
- BTC risk skoru: 70
- Vol persentil: 20.84168337
- Crash hızı: -0.22794315

### Grid Özeti

- Alış: 3 kademe · dağılım []
- Satış: 3 kademe · dağılım []
- Hedef: coin %40.32 · USDT %59.68

### Güvenlik

- Max exposure: %40.32
- Worst exposure: %40.32
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 60/100. Rejim Düşük volatilite sıkışma. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## DOTUSDT — 50.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: DOTUSDT
- Kategori: Major alt
- Girilen bütçe: 50.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 30/100
- Parametre skoru: 51/100
- Route: `A3|R2|D2|S4|V3|K1|L2`
- Shelf: `DPLV5_A3_R2_D2_S4_V3_K1_L2`

### Piyasa Özeti

- Rejim metni: Dengeli aralık · Üst tepeler · savunmacı
- Spread: 0.1179941%
- RSI 5m/1h: 57.22607599 / 50.61546143
- BTC risk skoru: 70
- Vol persentil: 48.64729459
- Crash hızı: -0.23529412

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %40.0 · USDT %60.0

### Güvenlik

- Max exposure: %44.64
- Worst exposure: %100.0
- Aktif alış bütçesi: 30.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 51/100. Rejim Dengeli aralık. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## DOTUSDT — 100.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: DOTUSDT
- Kategori: Major alt
- Girilen bütçe: 100.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: first_start_buy_only
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 50/100
- Parametre skoru: 51/100
- Route: `A3|R2|D2|S4|V3|K1|L2`
- Shelf: `DPLV5_A3_R2_D2_S4_V3_K1_L2`

### Piyasa Özeti

- Rejim metni: Dengeli aralık · Üst tepeler · savunmacı
- Spread: 0.1179941%
- RSI 5m/1h: 57.22607599 / 50.61546143
- BTC risk skoru: 70
- Vol persentil: 48.64729459
- Crash hızı: -0.23529412

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %40.0 · USDT %60.0

### Güvenlik

- Max exposure: %44.64
- Worst exposure: %40.0
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 51/100. Rejim Dengeli aralık. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## DOTUSDT — 1000.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: DOTUSDT
- Kategori: Major alt
- Girilen bütçe: 1000.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: recommended_grid
- Deployable: hayır
- Final action: CONTROLLED_GRID
- Güven: 52/100
- Parametre skoru: 51/100
- Route: `A3|R2|D2|S4|V3|K1|L2`
- Shelf: `DPLV5_A3_R2_D2_S4_V3_K1_L2`

### Piyasa Özeti

- Rejim metni: Dengeli aralık · Üst tepeler · savunmacı
- Spread: 0.1179941%
- RSI 5m/1h: 57.22607599 / 50.61546143
- BTC risk skoru: 70
- Vol persentil: 48.64729459
- Crash hızı: -0.23529412

### Grid Özeti

- Alış: 2 kademe · dağılım [35.0, 65.0]
- Satış: 3 kademe · dağılım [10.0, 25.0, 65.0]
- Hedef: coin %40.0 · USDT %60.0

### Güvenlik

- Max exposure: %44.64
- Worst exposure: %44.46
- Aktif alış bütçesi: 44.55 USDT
- Fee bad: True
- Güvenlik sonucu: Parametre referans olarak üretildi; spread/risk/fee koşulları nedeniyle kontrollü başlangıç kapalı tutuldu.

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 51/100. Rejim Dengeli aralık, risk durumu savunmacı. Risk skoru 24/100, fırsat skoru 60/100. Volatilite 40, BTC piyasa riski 70. . Base tahsisi %40.0, quote %60.0, maksimum base exposure %44.6 ile sınırlandı. Alışlar 2 kademeye bölündü; grid aralığı alış %4.05 / satış %3.98. Dengeleme: Base/quote hedefi anlamlı değişti ancak piyasa güvenlik koşulları uygun olmadığı için rebalance ertelendi (fee_bad).
```

## LTCUSDT — 50.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: LTCUSDT
- Kategori: Majors
- Girilen bütçe: 50.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 28/100
- Parametre skoru: 63/100
- Route: `A3|R4|D1|S5|V2|K2|L2`
- Shelf: `DPLV5_A3_R4_D1_S5_V2_K2_L2`

### Piyasa Özeti

- Rejim metni: Volatil aralık · Alt dipler · normal kontrollü
- Spread: 0.02325852%
- RSI 5m/1h: 51.10232804 / 64.7751668
- BTC risk skoru: 70
- Vol persentil: 55.61122244
- Crash hızı: -0.13927577

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %48.49 · USDT %51.51

### Güvenlik

- Max exposure: %48.49
- Worst exposure: %100.0
- Aktif alış bütçesi: 25.75 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| INFO | MIN_NOTIONAL_LIMITED_EXPECTED | Piyasa tamamen kötü değil; bütçe/min-notional nedeniyle kontrollü grid beklenmiyor. | min_notional_limited_grid |

### Ham cevap özeti

```
Parametre Skoru 63/100. Rejim Volatil aralık. Risk durumu normal kontrollü. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## LTCUSDT — 100.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: LTCUSDT
- Kategori: Majors
- Girilen bütçe: 100.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: first_start_buy_only
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 48/100
- Parametre skoru: 63/100
- Route: `A3|R4|D1|S5|V2|K2|L2`
- Shelf: `DPLV5_A3_R4_D1_S5_V2_K2_L2`

### Piyasa Özeti

- Rejim metni: Volatil aralık · Alt dipler · normal kontrollü
- Spread: 0.02325852%
- RSI 5m/1h: 51.10232804 / 64.7751668
- BTC risk skoru: 70
- Vol persentil: 55.61122244
- Crash hızı: -0.13927577

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %48.49 · USDT %51.51

### Güvenlik

- Max exposure: %48.49
- Worst exposure: %48.49
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 63/100. Rejim Volatil aralık. Risk durumu normal kontrollü. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## LTCUSDT — 1000.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: LTCUSDT
- Kategori: Majors
- Girilen bütçe: 1000.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: recommended_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 48/100
- Parametre skoru: 63/100
- Route: `A3|R4|D1|S5|V2|K2|L2`
- Shelf: `DPLV5_A3_R4_D1_S5_V2_K2_L2`

### Piyasa Özeti

- Rejim metni: Volatil aralık · Alt dipler · normal kontrollü
- Spread: 0.02325852%
- RSI 5m/1h: 51.10232804 / 64.7751668
- BTC risk skoru: 70
- Vol persentil: 55.61122244
- Crash hızı: -0.13927577

### Grid Özeti

- Alış: 3 kademe · dağılım []
- Satış: 3 kademe · dağılım []
- Hedef: coin %48.49 · USDT %51.51

### Güvenlik

- Max exposure: %48.49
- Worst exposure: %48.49
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 63/100. Rejim Volatil aralık. Risk durumu normal kontrollü. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## TRXUSDT — 50.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: TRXUSDT
- Kategori: Major alt
- Girilen bütçe: 50.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 26/100
- Parametre skoru: 62/100
- Route: `A4|R3|D2|S4|V1|K2|L2`
- Shelf: `DPLV5_A4_R3_D2_S4_V1_K2_L2`

### Piyasa Özeti

- Rejim metni: Düşük volatilite sıkışma · Üst tepeler · normal kontrollü
- Spread: 0.0311575%
- RSI 5m/1h: 50.65743492 / 46.75374428
- BTC risk skoru: 70
- Vol persentil: 14.07815631
- Crash hızı: -0.06228589

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %45.0 · USDT %55.0

### Güvenlik

- Max exposure: %48.94
- Worst exposure: %100.0
- Aktif alış bütçesi: 27.5 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| INFO | MIN_NOTIONAL_LIMITED_EXPECTED | Piyasa tamamen kötü değil; bütçe/min-notional nedeniyle kontrollü grid beklenmiyor. | min_notional_limited_grid |

### Ham cevap özeti

```
Parametre Skoru 62/100. Rejim Düşük volatilite sıkışma. Risk durumu normal kontrollü. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## TRXUSDT — 100.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: TRXUSDT
- Kategori: Major alt
- Girilen bütçe: 100.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: first_start_buy_only
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 46/100
- Parametre skoru: 62/100
- Route: `A4|R3|D2|S4|V1|K2|L2`
- Shelf: `DPLV5_A4_R3_D2_S4_V1_K2_L2`

### Piyasa Özeti

- Rejim metni: Düşük volatilite sıkışma · Üst tepeler · normal kontrollü
- Spread: 0.0311575%
- RSI 5m/1h: 50.65743492 / 46.75374428
- BTC risk skoru: 70
- Vol persentil: 14.07815631
- Crash hızı: -0.06228589

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %45.0 · USDT %55.0

### Güvenlik

- Max exposure: %48.94
- Worst exposure: %45.0
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 62/100. Rejim Düşük volatilite sıkışma. Risk durumu normal kontrollü. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## TRXUSDT — 1000.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: TRXUSDT
- Kategori: Major alt
- Girilen bütçe: 1000.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: controlled_grid
- Deployable: evet
- Final action: CONTROLLED_GRID
- Güven: 43/100
- Parametre skoru: 62/100
- Route: `A4|R3|D2|S4|V1|K2|L2`
- Shelf: `DPLV5_A4_R3_D2_S4_V1_K2_L2`

### Piyasa Özeti

- Rejim metni: Düşük volatilite sıkışma · Üst tepeler · normal kontrollü
- Spread: 0.0311575%
- RSI 5m/1h: 50.65743492 / 46.75374428
- BTC risk skoru: 70
- Vol persentil: 14.07815631
- Crash hızı: -0.06228589

### Grid Özeti

- Alış: 2 kademe · dağılım [35.0, 65.0]
- Satış: 3 kademe · dağılım [15.0, 35.0, 50.0]
- Hedef: coin %45.0 · USDT %55.0

### Güvenlik

- Max exposure: %48.94
- Worst exposure: %48.47
- Aktif alış bütçesi: 34.71 USDT
- Fee bad: True
- Güvenlik sonucu: Kontrollü grid / fee verisi eksik

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 62/100. Rejim Düşük volatilite sıkışma, risk durumu normal kontrollü. Risk skoru 61/100, fırsat skoru 57/100. Volatilite 40, BTC piyasa riski 70. . Base tahsisi %45.0, quote %55.0, maksimum base exposure %48.9 ile sınırlandı. Alışlar 2 kademeye bölündü; grid aralığı alış %2.65 / satış %2.88. Dengeleme: Base/quote hedefi anlamlı değişti ancak piyasa güvenlik koşulları uygun olmadığı için rebalance ertelendi (fee_bad).
```

## MATICUSDT — 50.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: MATICUSDT
- Kategori: Major alt
- Girilen bütçe: 50.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 26/100
- Parametre skoru: 54/100
- Route: `A4|R3|D2|S1|V2|K1|L3`
- Shelf: `DPLV5_A4_R3_D2_S1_V2_K1_L3`

### Piyasa Özeti

- Rejim metni: Düşük volatilite sıkışma · Aralık orta bölge · savunmacı
- Spread: None%
- RSI 5m/1h: 47.90102732 / 52.07619542
- BTC risk skoru: 70
- Vol persentil: 24.3987976
- Crash hızı: -0.05271481

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %32.64 · USDT %67.36

### Güvenlik

- Max exposure: %32.64
- Worst exposure: %100.0
- Aktif alış bütçesi: 33.68 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 54/100. Rejim Düşük volatilite sıkışma. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## MATICUSDT — 100.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: MATICUSDT
- Kategori: Major alt
- Girilen bütçe: 100.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 26/100
- Parametre skoru: 54/100
- Route: `A4|R3|D2|S1|V2|K1|L3`
- Shelf: `DPLV5_A4_R3_D2_S1_V2_K1_L3`

### Piyasa Özeti

- Rejim metni: Düşük volatilite sıkışma · Aralık orta bölge · savunmacı
- Spread: None%
- RSI 5m/1h: 47.90102732 / 52.07619542
- BTC risk skoru: 70
- Vol persentil: 24.3987976
- Crash hızı: -0.05271481

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %32.64 · USDT %67.36

### Güvenlik

- Max exposure: %32.64
- Worst exposure: %100.0
- Aktif alış bütçesi: 67.36 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 54/100. Rejim Düşük volatilite sıkışma. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## MATICUSDT — 1000.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: MATICUSDT
- Kategori: Major alt
- Girilen bütçe: 1000.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: recommended_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 47/100
- Parametre skoru: 54/100
- Route: `A4|R3|D2|S1|V2|K1|L3`
- Shelf: `DPLV5_A4_R3_D2_S1_V2_K1_L3`

### Piyasa Özeti

- Rejim metni: Düşük volatilite sıkışma · Aralık orta bölge · savunmacı
- Spread: None%
- RSI 5m/1h: 47.90102732 / 52.07619542
- BTC risk skoru: 70
- Vol persentil: 24.3987976
- Crash hızı: -0.05271481

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %32.64 · USDT %67.36

### Güvenlik

- Max exposure: %32.64
- Worst exposure: %32.64
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 54/100. Rejim Düşük volatilite sıkışma. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## ATOMUSDT — 50.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: ATOMUSDT
- Kategori: Major alt
- Girilen bütçe: 50.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 25/100
- Parametre skoru: 59/100
- Route: `A6|R2|D1|S4|V2|K1|L3`
- Shelf: `DPLV5_A6_R2_D1_S4_V2_K1_L3`

### Piyasa Özeti

- Rejim metni: Dengeli aralık · Üst tepeler · savunmacı
- Spread: 0.06205399%
- RSI 5m/1h: 66.05460162 / 55.94752115
- BTC risk skoru: 70
- Vol persentil: 43.93787575
- Crash hızı: -0.06234414

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %27.1 · USDT %72.9

### Güvenlik

- Max exposure: %27.1
- Worst exposure: %100.0
- Aktif alış bütçesi: 36.45 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 59/100. Rejim Dengeli aralık. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## ATOMUSDT — 100.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: ATOMUSDT
- Kategori: Major alt
- Girilen bütçe: 100.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 25/100
- Parametre skoru: 59/100
- Route: `A6|R2|D1|S4|V2|K1|L3`
- Shelf: `DPLV5_A6_R2_D1_S4_V2_K1_L3`

### Piyasa Özeti

- Rejim metni: Dengeli aralık · Üst tepeler · savunmacı
- Spread: 0.06205399%
- RSI 5m/1h: 66.05460162 / 55.94752115
- BTC risk skoru: 70
- Vol persentil: 43.93787575
- Crash hızı: -0.06234414

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %27.1 · USDT %72.9

### Güvenlik

- Max exposure: %27.1
- Worst exposure: %100.0
- Aktif alış bütçesi: 72.9 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 59/100. Rejim Dengeli aralık. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## ATOMUSDT — 1000.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: ATOMUSDT
- Kategori: Major alt
- Girilen bütçe: 1000.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: recommended_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 45/100
- Parametre skoru: 59/100
- Route: `A6|R2|D1|S4|V2|K1|L3`
- Shelf: `DPLV5_A6_R2_D1_S4_V2_K1_L3`

### Piyasa Özeti

- Rejim metni: Dengeli aralık · Üst tepeler · savunmacı
- Spread: 0.06205399%
- RSI 5m/1h: 66.05460162 / 55.94752115
- BTC risk skoru: 70
- Vol persentil: 43.93787575
- Crash hızı: -0.06234414

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %27.1 · USDT %72.9

### Güvenlik

- Max exposure: %27.1
- Worst exposure: %27.1
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 59/100. Rejim Dengeli aralık. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## NEARUSDT — 50.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: NEARUSDT
- Kategori: Major alt
- Girilen bütçe: 50.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 33/100
- Parametre skoru: 53/100
- Route: `A4|R6|D1|S4|V3|K1|L2`
- Shelf: `DPLV5_A4_R6_D1_S4_V3_K1_L2`

### Piyasa Özeti

- Rejim metni: Kırılım devamı · Üst tepeler · savunmacı
- Spread: 0.05275653%
- RSI 5m/1h: 74.60556494 / 69.048464
- BTC risk skoru: 70
- Vol persentil: 76.20240481
- Crash hızı: -0.52687039

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %46.37 · USDT %53.63

### Güvenlik

- Max exposure: %46.37
- Worst exposure: %100.0
- Aktif alış bütçesi: 26.82 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 53/100. Rejim Kırılım devamı. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## NEARUSDT — 100.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: NEARUSDT
- Kategori: Major alt
- Girilen bütçe: 100.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: first_start_buy_only
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 53/100
- Parametre skoru: 53/100
- Route: `A4|R6|D1|S4|V3|K1|L2`
- Shelf: `DPLV5_A4_R6_D1_S4_V3_K1_L2`

### Piyasa Özeti

- Rejim metni: Kırılım devamı · Üst tepeler · savunmacı
- Spread: 0.05272871%
- RSI 5m/1h: 74.60556494 / 69.048464
- BTC risk skoru: 70
- Vol persentil: 76.20240481
- Crash hızı: -0.52687039

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %46.37 · USDT %53.63

### Güvenlik

- Max exposure: %46.37
- Worst exposure: %46.37
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 53/100. Rejim Kırılım devamı. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## NEARUSDT — 1000.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: NEARUSDT
- Kategori: Major alt
- Girilen bütçe: 1000.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: recommended_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 53/100
- Parametre skoru: 53/100
- Route: `A4|R6|D1|S4|V3|K1|L2`
- Shelf: `DPLV5_A4_R6_D1_S4_V3_K1_L2`

### Piyasa Özeti

- Rejim metni: Kırılım devamı · Üst tepeler · savunmacı
- Spread: 0.05272871%
- RSI 5m/1h: 74.60556494 / 69.048464
- BTC risk skoru: 70
- Vol persentil: 76.20240481
- Crash hızı: -0.52687039

### Grid Özeti

- Alış: 3 kademe · dağılım []
- Satış: 3 kademe · dağılım []
- Hedef: coin %46.37 · USDT %53.63

### Güvenlik

- Max exposure: %46.37
- Worst exposure: %46.37
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 53/100. Rejim Kırılım devamı. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## APTUSDT — 50.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: APTUSDT
- Kategori: Major alt
- Girilen bütçe: 50.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 25/100
- Parametre skoru: 61/100
- Route: `A4|R2|D1|S4|V3|K1|L3`
- Shelf: `DPLV5_A4_R2_D1_S4_V3_K1_L3`

### Piyasa Özeti

- Rejim metni: Dengeli aralık · Üst tepeler · savunmacı
- Spread: 0.16515277%
- RSI 5m/1h: 59.93853822 / 54.8704374
- BTC risk skoru: 70
- Vol persentil: 41.38276553
- Crash hızı: -0.32948929

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %36.14 · USDT %63.86

### Güvenlik

- Max exposure: %36.14
- Worst exposure: %100.0
- Aktif alış bütçesi: 31.93 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 61/100. Rejim Dengeli aralık. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## APTUSDT — 100.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: APTUSDT
- Kategori: Major alt
- Girilen bütçe: 100.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: first_start_buy_only
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 45/100
- Parametre skoru: 61/100
- Route: `A4|R2|D1|S4|V3|K1|L3`
- Shelf: `DPLV5_A4_R2_D1_S4_V3_K1_L3`

### Piyasa Özeti

- Rejim metni: Dengeli aralık · Üst tepeler · savunmacı
- Spread: 0.16515277%
- RSI 5m/1h: 59.93853822 / 54.8704374
- BTC risk skoru: 70
- Vol persentil: 41.38276553
- Crash hızı: -0.32948929

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %36.14 · USDT %63.86

### Güvenlik

- Max exposure: %36.14
- Worst exposure: %36.14
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 61/100. Rejim Dengeli aralık. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## APTUSDT — 1000.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: APTUSDT
- Kategori: Major alt
- Girilen bütçe: 1000.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: recommended_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 45/100
- Parametre skoru: 61/100
- Route: `A4|R2|D1|S4|V3|K1|L3`
- Shelf: `DPLV5_A4_R2_D1_S4_V3_K1_L3`

### Piyasa Özeti

- Rejim metni: Dengeli aralık · Üst tepeler · savunmacı
- Spread: 0.16515277%
- RSI 5m/1h: 59.93853822 / 54.8704374
- BTC risk skoru: 70
- Vol persentil: 41.38276553
- Crash hızı: -0.32948929

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %36.14 · USDT %63.86

### Güvenlik

- Max exposure: %36.14
- Worst exposure: %36.14
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 61/100. Rejim Dengeli aralık. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## ARBUSDT — 50.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: ARBUSDT
- Kategori: Major alt
- Girilen bütçe: 50.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 30/100
- Parametre skoru: 50/100
- Route: `A6|R4|D2|S7|V3|K1|L3`
- Shelf: `DPLV5_A6_R4_D2_S7_V3_K1_L3`

### Piyasa Özeti

- Rejim metni: Volatil aralık · Kırılım retesti · savunmacı
- Spread: 0.1325381%
- RSI 5m/1h: 54.69742693 / 60.00613726
- BTC risk skoru: 70
- Vol persentil: 60.52104208
- Crash hızı: -0.39630119

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %27.56 · USDT %72.44

### Güvenlik

- Max exposure: %27.56
- Worst exposure: %100.0
- Aktif alış bütçesi: 36.22 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 50/100. Rejim Volatil aralık. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## ARBUSDT — 100.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: ARBUSDT
- Kategori: Major alt
- Girilen bütçe: 100.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 30/100
- Parametre skoru: 50/100
- Route: `A6|R4|D2|S7|V3|K1|L3`
- Shelf: `DPLV5_A6_R4_D2_S7_V3_K1_L3`

### Piyasa Özeti

- Rejim metni: Volatil aralık · Kırılım retesti · savunmacı
- Spread: 0.1325381%
- RSI 5m/1h: 54.69742693 / 60.00613726
- BTC risk skoru: 70
- Vol persentil: 60.52104208
- Crash hızı: -0.39630119

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %27.56 · USDT %72.44

### Güvenlik

- Max exposure: %27.56
- Worst exposure: %100.0
- Aktif alış bütçesi: 72.44 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 50/100. Rejim Volatil aralık. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## ARBUSDT — 1000.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: ARBUSDT
- Kategori: Major alt
- Girilen bütçe: 1000.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: recommended_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 50/100
- Parametre skoru: 50/100
- Route: `A6|R4|D2|S7|V3|K1|L3`
- Shelf: `DPLV5_A6_R4_D2_S7_V3_K1_L3`

### Piyasa Özeti

- Rejim metni: Volatil aralık · Kırılım retesti · savunmacı
- Spread: 0.1325381%
- RSI 5m/1h: 54.69742693 / 60.00613726
- BTC risk skoru: 70
- Vol persentil: 60.52104208
- Crash hızı: -0.39630119

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %27.56 · USDT %72.44

### Güvenlik

- Max exposure: %27.56
- Worst exposure: %27.56
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 50/100. Rejim Volatil aralık. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## OPUSDT — 50.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: OPUSDT
- Kategori: Major alt
- Girilen bütçe: 50.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 24/100
- Parametre skoru: 58/100
- Route: `A4|R10|D2|S5|V3|K1|L2`
- Shelf: `DPLV5_A4_R10_D2_S5_V3_K1_L2`

### Piyasa Özeti

- Rejim metni: Alt dipli düşüş · Alt dipler · savunmacı
- Spread: 0.09675859%
- RSI 5m/1h: 49.27097734 / 42.52037718
- BTC risk skoru: 70
- Vol persentil: 32.86573146
- Crash hızı: -0.48216008

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %18.0 · USDT %82.0

### Güvenlik

- Max exposure: %26.23
- Worst exposure: %100.0
- Aktif alış bütçesi: 41.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 58/100. Rejim Alt dipli düşüş. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## OPUSDT — 100.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: OPUSDT
- Kategori: Major alt
- Girilen bütçe: 100.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 24/100
- Parametre skoru: 58/100
- Route: `A4|R10|D2|S5|V3|K1|L2`
- Shelf: `DPLV5_A4_R10_D2_S5_V3_K1_L2`

### Piyasa Özeti

- Rejim metni: Alt dipli düşüş · Alt dipler · savunmacı
- Spread: 0.09675859%
- RSI 5m/1h: 49.27097734 / 42.52037718
- BTC risk skoru: 70
- Vol persentil: 32.86573146
- Crash hızı: -0.48216008

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %18.0 · USDT %82.0

### Güvenlik

- Max exposure: %26.23
- Worst exposure: %100.0
- Aktif alış bütçesi: 82.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 58/100. Rejim Alt dipli düşüş. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## OPUSDT — 1000.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: OPUSDT
- Kategori: Major alt
- Girilen bütçe: 1000.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: recommended_grid
- Deployable: hayır
- Final action: CONTROLLED_GRID
- Güven: 50/100
- Parametre skoru: 58/100
- Route: `A4|R10|D2|S5|V3|K1|L2`
- Shelf: `DPLV5_A4_R10_D2_S5_V3_K1_L2`

### Piyasa Özeti

- Rejim metni: Alt dipli düşüş · Alt dipler · savunmacı
- Spread: 0.09675859%
- RSI 5m/1h: 49.27097734 / 42.52037718
- BTC risk skoru: 70
- Vol persentil: 32.86573146
- Crash hızı: -0.48216008

### Grid Özeti

- Alış: 2 kademe · dağılım [28.0, 72.0]
- Satış: 2 kademe · dağılım [30.0, 70.0]
- Hedef: coin %18.0 · USDT %82.0

### Güvenlik

- Max exposure: %26.23
- Worst exposure: %25.16
- Aktif alış bütçesi: 71.63 USDT
- Fee bad: True
- Güvenlik sonucu: Parametre referans olarak üretildi; spread/risk/fee koşulları nedeniyle kontrollü başlangıç kapalı tutuldu.

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 58/100. Rejim Alt dipli düşüş, risk durumu savunmacı. Risk skoru 59/100, fırsat skoru 37/100. Volatilite 40, BTC piyasa riski 70. . Base tahsisi %18.0, quote %82.0, maksimum base exposure %26.2 ile sınırlandı. Alışlar 2 kademeye bölündü; grid aralığı alış %9.35 / satış %6.47. Dengeleme: Base/quote hedefi anlamlı değişti ancak piyasa güvenlik koşulları uygun olmadığı için rebalance ertelendi (fee_bad).
```

## INJUSDT — 50.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: INJUSDT
- Kategori: Major alt
- Girilen bütçe: 50.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 29/100
- Parametre skoru: 64/100
- Route: `A3|R2|D1|S5|V4|K2|L2`
- Shelf: `DPLV5_A3_R2_D1_S5_V4_K2_L2`

### Piyasa Özeti

- Rejim metni: Dengeli aralık · Alt dipler · normal kontrollü
- Spread: 0.0203314%
- RSI 5m/1h: 51.01717904 / 57.69026665
- BTC risk skoru: 70
- Vol persentil: 42.53507014
- Crash hızı: -0.30512612

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %47.69 · USDT %52.31

### Güvenlik

- Max exposure: %47.69
- Worst exposure: %100.0
- Aktif alış bütçesi: 26.16 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| INFO | MIN_NOTIONAL_LIMITED_EXPECTED | Piyasa tamamen kötü değil; bütçe/min-notional nedeniyle kontrollü grid beklenmiyor. | min_notional_limited_grid |

### Ham cevap özeti

```
Parametre Skoru 64/100. Rejim Dengeli aralık. Risk durumu normal kontrollü. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## INJUSDT — 100.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: INJUSDT
- Kategori: Major alt
- Girilen bütçe: 100.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: first_start_buy_only
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 49/100
- Parametre skoru: 64/100
- Route: `A3|R2|D1|S5|V4|K2|L2`
- Shelf: `DPLV5_A3_R2_D1_S5_V4_K2_L2`

### Piyasa Özeti

- Rejim metni: Dengeli aralık · Alt dipler · normal kontrollü
- Spread: 0.0203314%
- RSI 5m/1h: 51.01717904 / 57.69026665
- BTC risk skoru: 70
- Vol persentil: 42.53507014
- Crash hızı: -0.30512612

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %47.69 · USDT %52.31

### Güvenlik

- Max exposure: %47.69
- Worst exposure: %47.69
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 64/100. Rejim Dengeli aralık. Risk durumu normal kontrollü. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## INJUSDT — 1000.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: INJUSDT
- Kategori: Major alt
- Girilen bütçe: 1000.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: recommended_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 49/100
- Parametre skoru: 64/100
- Route: `A3|R2|D1|S5|V4|K2|L2`
- Shelf: `DPLV5_A3_R2_D1_S5_V4_K2_L2`

### Piyasa Özeti

- Rejim metni: Dengeli aralık · Alt dipler · normal kontrollü
- Spread: 0.02031901%
- RSI 5m/1h: 51.01717904 / 57.69026665
- BTC risk skoru: 70
- Vol persentil: 42.53507014
- Crash hızı: -0.30512612

### Grid Özeti

- Alış: 3 kademe · dağılım []
- Satış: 3 kademe · dağılım []
- Hedef: coin %47.69 · USDT %52.31

### Güvenlik

- Max exposure: %47.69
- Worst exposure: %47.69
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 64/100. Rejim Dengeli aralık. Risk durumu normal kontrollü. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## SUIUSDT — 50.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: SUIUSDT
- Kategori: Major alt
- Girilen bütçe: 50.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 28/100
- Parametre skoru: 63/100
- Route: `A3|R2|D1|S4|V3|K2|L2`
- Shelf: `DPLV5_A3_R2_D1_S4_V3_K2_L2`

### Piyasa Özeti

- Rejim metni: Dengeli aralık · Üst tepeler · normal kontrollü
- Spread: 0.01407559%
- RSI 5m/1h: 68.8154094 / 60.52682045
- BTC risk skoru: 70
- Vol persentil: 38.47695391
- Crash hızı: -0.12684989

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %54.19 · USDT %45.81

### Güvenlik

- Max exposure: %54.19
- Worst exposure: %100.0
- Aktif alış bütçesi: 22.91 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| INFO | MIN_NOTIONAL_LIMITED_EXPECTED | Piyasa tamamen kötü değil; bütçe/min-notional nedeniyle kontrollü grid beklenmiyor. | min_notional_limited_grid |

### Ham cevap özeti

```
Parametre Skoru 63/100. Rejim Dengeli aralık. Risk durumu normal kontrollü. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## SUIUSDT — 100.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: SUIUSDT
- Kategori: Major alt
- Girilen bütçe: 100.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: first_start_buy_only
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 48/100
- Parametre skoru: 63/100
- Route: `A3|R2|D1|S4|V3|K2|L2`
- Shelf: `DPLV5_A3_R2_D1_S4_V3_K2_L2`

### Piyasa Özeti

- Rejim metni: Dengeli aralık · Üst tepeler · normal kontrollü
- Spread: 0.01407559%
- RSI 5m/1h: 68.8154094 / 60.52682045
- BTC risk skoru: 70
- Vol persentil: 38.47695391
- Crash hızı: -0.12684989

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %54.19 · USDT %45.81

### Güvenlik

- Max exposure: %54.19
- Worst exposure: %54.19
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 63/100. Rejim Dengeli aralık. Risk durumu normal kontrollü. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## SUIUSDT — 1000.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: SUIUSDT
- Kategori: Major alt
- Girilen bütçe: 1000.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: recommended_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 48/100
- Parametre skoru: 63/100
- Route: `A3|R2|D1|S4|V3|K2|L2`
- Shelf: `DPLV5_A3_R2_D1_S4_V3_K2_L2`

### Piyasa Özeti

- Rejim metni: Dengeli aralık · Üst tepeler · normal kontrollü
- Spread: 0.01407559%
- RSI 5m/1h: 68.8154094 / 60.52682045
- BTC risk skoru: 70
- Vol persentil: 38.47695391
- Crash hızı: -0.12684989

### Grid Özeti

- Alış: 3 kademe · dağılım []
- Satış: 3 kademe · dağılım []
- Hedef: coin %54.19 · USDT %45.81

### Güvenlik

- Max exposure: %54.19
- Worst exposure: %54.19
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 63/100. Rejim Dengeli aralık. Risk durumu normal kontrollü. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## SEIUSDT — 50.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: SEIUSDT
- Kategori: Major alt
- Girilen bütçe: 50.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 27/100
- Parametre skoru: 55/100
- Route: `A4|R12|D2|S4|V3|K1|L2`
- Shelf: `DPLV5_A4_R12_D2_S4_V3_K1_L2`

### Piyasa Özeti

- Rejim metni: Kapitülasyon tepkisi · Üst tepeler · savunmacı
- Spread: 0.01934797%
- RSI 5m/1h: 53.09308158 / 39.63529468
- BTC risk skoru: 70
- Vol persentil: 29.90981964
- Crash hızı: -0.28996714

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %26.0 · USDT %74.0

### Güvenlik

- Max exposure: %31.8
- Worst exposure: %100.0
- Aktif alış bütçesi: 37.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| INFO | MIN_NOTIONAL_LIMITED_EXPECTED | Piyasa tamamen kötü değil; bütçe/min-notional nedeniyle kontrollü grid beklenmiyor. | min_notional_limited_grid |

### Ham cevap özeti

```
Parametre Skoru 55/100. Rejim Kapitülasyon tepkisi. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## SEIUSDT — 100.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: SEIUSDT
- Kategori: Major alt
- Girilen bütçe: 100.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 27/100
- Parametre skoru: 55/100
- Route: `A4|R12|D2|S4|V3|K1|L2`
- Shelf: `DPLV5_A4_R12_D2_S4_V3_K1_L2`

### Piyasa Özeti

- Rejim metni: Kapitülasyon tepkisi · Üst tepeler · savunmacı
- Spread: 0.01934797%
- RSI 5m/1h: 53.09308158 / 39.63529468
- BTC risk skoru: 70
- Vol persentil: 29.90981964
- Crash hızı: -0.28996714

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %26.0 · USDT %74.0

### Güvenlik

- Max exposure: %31.8
- Worst exposure: %100.0
- Aktif alış bütçesi: 74.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| INFO | MIN_NOTIONAL_LIMITED_EXPECTED | Piyasa tamamen kötü değil; bütçe/min-notional nedeniyle kontrollü grid beklenmiyor. | min_notional_limited_grid |

### Ham cevap özeti

```
Parametre Skoru 55/100. Rejim Kapitülasyon tepkisi. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## SEIUSDT — 1000.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: SEIUSDT
- Kategori: Major alt
- Girilen bütçe: 1000.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: recommended_grid
- Deployable: hayır
- Final action: CONTROLLED_GRID
- Güven: 52/100
- Parametre skoru: 55/100
- Route: `A4|R12|D2|S4|V3|K1|L2`
- Shelf: `DPLV5_A4_R12_D2_S4_V3_K1_L2`

### Piyasa Özeti

- Rejim metni: Kapitülasyon tepkisi · Üst tepeler · savunmacı
- Spread: 0.01934797%
- RSI 5m/1h: 53.09308158 / 39.63529468
- BTC risk skoru: 70
- Vol persentil: 29.90981964
- Crash hızı: -0.28996714

### Grid Özeti

- Alış: 2 kademe · dağılım [28.0, 72.0]
- Satış: 2 kademe · dağılım [30.0, 70.0]
- Hedef: coin %26.0 · USDT %74.0

### Güvenlik

- Max exposure: %31.8
- Worst exposure: %31.49
- Aktif alış bütçesi: 54.95 USDT
- Fee bad: True
- Güvenlik sonucu: Parametre referans olarak üretildi; spread/risk/fee koşulları nedeniyle kontrollü başlangıç kapalı tutuldu.

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 55/100. Rejim Kapitülasyon tepkisi, risk durumu savunmacı. Risk skoru 29/100, fırsat skoru 58/100. Volatilite 40, BTC piyasa riski 70. . Base tahsisi %26.0, quote %74.0, maksimum base exposure %31.8 ile sınırlandı. Alışlar 2 kademeye bölündü; grid aralığı alış %5.51 / satış %5.43. Dengeleme: Base/quote hedefi anlamlı değişti ancak piyasa güvenlik koşulları uygun olmadığı için rebalance ertelendi (fee_bad).
```

## AAVEUSDT — 50.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: AAVEUSDT
- Kategori: High volume alt
- Girilen bütçe: 50.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 34/100
- Parametre skoru: 66/100
- Route: `A4|R2|D1|S6|V4|K2|L2`
- Shelf: `DPLV5_A4_R2_D1_S6_V4_K2_L2`

### Piyasa Özeti

- Rejim metni: Dengeli aralık · Kırılım hazırlığı · normal kontrollü
- Spread: 0.01024853%
- RSI 5m/1h: 56.97301391 / 62.91445534
- BTC risk skoru: 70
- Vol persentil: 59.76953908
- Crash hızı: -0.10248002

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %49.85 · USDT %50.15

### Güvenlik

- Max exposure: %49.85
- Worst exposure: %100.0
- Aktif alış bütçesi: 25.07 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| INFO | MIN_NOTIONAL_LIMITED_EXPECTED | Piyasa tamamen kötü değil; bütçe/min-notional nedeniyle kontrollü grid beklenmiyor. | min_notional_limited_grid |

### Ham cevap özeti

```
Parametre Skoru 66/100. Rejim Dengeli aralık. Risk durumu normal kontrollü. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## AAVEUSDT — 100.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: AAVEUSDT
- Kategori: High volume alt
- Girilen bütçe: 100.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: first_start_buy_only
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 55/100
- Parametre skoru: 66/100
- Route: `A4|R2|D1|S6|V4|K2|L2`
- Shelf: `DPLV5_A4_R2_D1_S6_V4_K2_L2`

### Piyasa Özeti

- Rejim metni: Dengeli aralık · Kırılım hazırlığı · normal kontrollü
- Spread: 0.01024538%
- RSI 5m/1h: 56.97301391 / 62.91445534
- BTC risk skoru: 70
- Vol persentil: 59.76953908
- Crash hızı: -0.10248002

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %49.85 · USDT %50.15

### Güvenlik

- Max exposure: %49.85
- Worst exposure: %49.85
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 66/100. Rejim Dengeli aralık. Risk durumu normal kontrollü. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## AAVEUSDT — 1000.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: AAVEUSDT
- Kategori: High volume alt
- Girilen bütçe: 1000.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: recommended_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 55/100
- Parametre skoru: 66/100
- Route: `A4|R2|D1|S6|V4|K2|L2`
- Shelf: `DPLV5_A4_R2_D1_S6_V4_K2_L2`

### Piyasa Özeti

- Rejim metni: Dengeli aralık · Kırılım hazırlığı · normal kontrollü
- Spread: 0.01024433%
- RSI 5m/1h: 56.97301391 / 62.91445534
- BTC risk skoru: 70
- Vol persentil: 59.76953908
- Crash hızı: -0.10248002

### Grid Özeti

- Alış: 3 kademe · dağılım []
- Satış: 3 kademe · dağılım []
- Hedef: coin %49.85 · USDT %50.15

### Güvenlik

- Max exposure: %49.85
- Worst exposure: %49.85
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 66/100. Rejim Dengeli aralık. Risk durumu normal kontrollü. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## UNIUSDT — 50.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: UNIUSDT
- Kategori: High volume alt
- Girilen bütçe: 50.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 26/100
- Parametre skoru: 59/100
- Route: `A4|R3|D1|S4|V3|K1|L2`
- Shelf: `DPLV5_A4_R3_D1_S4_V3_K1_L2`

### Piyasa Özeti

- Rejim metni: Düşük volatilite sıkışma · Üst tepeler · savunmacı
- Spread: 0.0334616%
- RSI 5m/1h: 75.29386331 / 62.60153356
- BTC risk skoru: 70
- Vol persentil: 18.63727455
- Crash hızı: -0.23434884

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %34.12 · USDT %65.88

### Güvenlik

- Max exposure: %34.12
- Worst exposure: %100.0
- Aktif alış bütçesi: 32.94 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| INFO | MIN_NOTIONAL_LIMITED_EXPECTED | Piyasa tamamen kötü değil; bütçe/min-notional nedeniyle kontrollü grid beklenmiyor. | min_notional_limited_grid |

### Ham cevap özeti

```
Parametre Skoru 59/100. Rejim Düşük volatilite sıkışma. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## UNIUSDT — 100.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: UNIUSDT
- Kategori: High volume alt
- Girilen bütçe: 100.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: first_start_buy_only
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 46/100
- Parametre skoru: 59/100
- Route: `A4|R3|D1|S4|V3|K1|L2`
- Shelf: `DPLV5_A4_R3_D1_S4_V3_K1_L2`

### Piyasa Özeti

- Rejim metni: Düşük volatilite sıkışma · Üst tepeler · savunmacı
- Spread: 0.0334616%
- RSI 5m/1h: 75.29386331 / 62.60153356
- BTC risk skoru: 70
- Vol persentil: 18.63727455
- Crash hızı: -0.23434884

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %34.12 · USDT %65.88

### Güvenlik

- Max exposure: %34.12
- Worst exposure: %34.12
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 59/100. Rejim Düşük volatilite sıkışma. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## UNIUSDT — 1000.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: UNIUSDT
- Kategori: High volume alt
- Girilen bütçe: 1000.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: recommended_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 46/100
- Parametre skoru: 59/100
- Route: `A4|R3|D1|S4|V3|K1|L2`
- Shelf: `DPLV5_A4_R3_D1_S4_V3_K1_L2`

### Piyasa Özeti

- Rejim metni: Düşük volatilite sıkışma · Üst tepeler · savunmacı
- Spread: 0.0334616%
- RSI 5m/1h: 75.29386331 / 62.60153356
- BTC risk skoru: 70
- Vol persentil: 18.63727455
- Crash hızı: -0.23434884

### Grid Özeti

- Alış: 3 kademe · dağılım []
- Satış: 3 kademe · dağılım []
- Hedef: coin %34.12 · USDT %65.88

### Güvenlik

- Max exposure: %34.12
- Worst exposure: %34.12
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 59/100. Rejim Düşük volatilite sıkışma. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## COMPUSDT — 50.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: COMPUSDT
- Kategori: High volume alt
- Girilen bütçe: 50.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 27/100
- Parametre skoru: 50/100
- Route: `A6|R7|D1|S2|V3|K1|L3`
- Shelf: `DPLV5_A6_R7_D1_S2_V3_K1_L3`

### Piyasa Özeti

- Rejim metni: Toparlanma · Aralık üst bölge · savunmacı
- Spread: 0.06159532%
- RSI 5m/1h: 67.77839755 / 60.71600491
- BTC risk skoru: 70
- Vol persentil: 39.57915832
- Crash hızı: -0.12360939

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %26.23 · USDT %73.77

### Güvenlik

- Max exposure: %26.23
- Worst exposure: %100.0
- Aktif alış bütçesi: 36.88 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 50/100. Rejim Toparlanma. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## COMPUSDT — 100.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: COMPUSDT
- Kategori: High volume alt
- Girilen bütçe: 100.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 27/100
- Parametre skoru: 50/100
- Route: `A6|R7|D1|S2|V3|K1|L3`
- Shelf: `DPLV5_A6_R7_D1_S2_V3_K1_L3`

### Piyasa Özeti

- Rejim metni: Toparlanma · Aralık üst bölge · savunmacı
- Spread: 0.06159532%
- RSI 5m/1h: 67.77839755 / 60.71600491
- BTC risk skoru: 70
- Vol persentil: 39.57915832
- Crash hızı: -0.12360939

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %26.23 · USDT %73.77

### Güvenlik

- Max exposure: %26.23
- Worst exposure: %100.0
- Aktif alış bütçesi: 73.77 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 50/100. Rejim Toparlanma. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## COMPUSDT — 1000.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: COMPUSDT
- Kategori: High volume alt
- Girilen bütçe: 1000.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: recommended_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 48/100
- Parametre skoru: 50/100
- Route: `A6|R7|D1|S2|V3|K1|L3`
- Shelf: `DPLV5_A6_R7_D1_S2_V3_K1_L3`

### Piyasa Özeti

- Rejim metni: Toparlanma · Aralık üst bölge · savunmacı
- Spread: 0.06159532%
- RSI 5m/1h: 67.77839755 / 60.71600491
- BTC risk skoru: 70
- Vol persentil: 39.57915832
- Crash hızı: -0.12360939

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %26.23 · USDT %73.77

### Güvenlik

- Max exposure: %26.23
- Worst exposure: %26.23
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 50/100. Rejim Toparlanma. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## MKRUSDT — 50.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: MKRUSDT
- Kategori: High volume alt
- Girilen bütçe: 50.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 25/100
- Parametre skoru: 62/100
- Route: `A4|R4|D2|S4|V4|K2|L3`
- Shelf: `DPLV5_A4_R4_D2_S4_V4_K2_L3`

### Piyasa Özeti

- Rejim metni: Volatil aralık · Üst tepeler · normal kontrollü
- Spread: None%
- RSI 5m/1h: 54.9745111 / 45.24448959
- BTC risk skoru: 70
- Vol persentil: 56.66332665
- Crash hızı: -0.2377924

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %41.04 · USDT %58.96

### Güvenlik

- Max exposure: %41.04
- Worst exposure: %100.0
- Aktif alış bütçesi: 29.48 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 62/100. Rejim Volatil aralık. Risk durumu normal kontrollü. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## MKRUSDT — 100.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: MKRUSDT
- Kategori: High volume alt
- Girilen bütçe: 100.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: first_start_buy_only
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 45/100
- Parametre skoru: 62/100
- Route: `A4|R4|D2|S4|V4|K2|L3`
- Shelf: `DPLV5_A4_R4_D2_S4_V4_K2_L3`

### Piyasa Özeti

- Rejim metni: Volatil aralık · Üst tepeler · normal kontrollü
- Spread: None%
- RSI 5m/1h: 54.9745111 / 45.24448959
- BTC risk skoru: 70
- Vol persentil: 56.66332665
- Crash hızı: -0.2377924

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %41.04 · USDT %58.96

### Güvenlik

- Max exposure: %41.04
- Worst exposure: %41.04
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 62/100. Rejim Volatil aralık. Risk durumu normal kontrollü. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## MKRUSDT — 1000.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: MKRUSDT
- Kategori: High volume alt
- Girilen bütçe: 1000.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: recommended_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 45/100
- Parametre skoru: 62/100
- Route: `A4|R4|D2|S4|V4|K2|L3`
- Shelf: `DPLV5_A4_R4_D2_S4_V4_K2_L3`

### Piyasa Özeti

- Rejim metni: Volatil aralık · Üst tepeler · normal kontrollü
- Spread: None%
- RSI 5m/1h: 54.9745111 / 45.24448959
- BTC risk skoru: 70
- Vol persentil: 56.66332665
- Crash hızı: -0.2377924

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %41.04 · USDT %58.96

### Güvenlik

- Max exposure: %41.04
- Worst exposure: %41.04
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 62/100. Rejim Volatil aralık. Risk durumu normal kontrollü. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## FETUSDT — 50.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: FETUSDT
- Kategori: AI / narrative coin
- Girilen bütçe: 50.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 27/100
- Parametre skoru: 62/100
- Route: `A4|R2|D3|S5|V4|K2|L2`
- Shelf: `DPLV5_A4_R2_D3_S5_V4_K2_L2`

### Piyasa Özeti

- Rejim metni: Dengeli aralık · Alt dipler · normal kontrollü
- Spread: 0.05581915%
- RSI 5m/1h: 43.6281352 / 56.91368925
- BTC risk skoru: 70
- Vol persentil: 40.48096192
- Crash hızı: -0.38910506

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %42.0 · USDT %58.0

### Güvenlik

- Max exposure: %43.87
- Worst exposure: %100.0
- Aktif alış bütçesi: 29.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 62/100. Rejim Dengeli aralık. Risk durumu normal kontrollü. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## FETUSDT — 100.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: FETUSDT
- Kategori: AI / narrative coin
- Girilen bütçe: 100.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: first_start_buy_only
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 48/100
- Parametre skoru: 62/100
- Route: `A4|R2|D3|S5|V4|K2|L2`
- Shelf: `DPLV5_A4_R2_D3_S5_V4_K2_L2`

### Piyasa Özeti

- Rejim metni: Dengeli aralık · Alt dipler · normal kontrollü
- Spread: 0.05581915%
- RSI 5m/1h: 43.6281352 / 56.91368925
- BTC risk skoru: 70
- Vol persentil: 40.48096192
- Crash hızı: -0.38910506

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %42.0 · USDT %58.0

### Güvenlik

- Max exposure: %43.87
- Worst exposure: %42.0
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 62/100. Rejim Dengeli aralık. Risk durumu normal kontrollü. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## FETUSDT — 1000.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: FETUSDT
- Kategori: AI / narrative coin
- Girilen bütçe: 1000.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: controlled_grid
- Deployable: evet
- Final action: CONTROLLED_GRID
- Güven: 45/100
- Parametre skoru: 62/100
- Route: `A4|R2|D3|S5|V4|K2|L2`
- Shelf: `DPLV5_A4_R2_D3_S5_V4_K2_L2`

### Piyasa Özeti

- Rejim metni: Dengeli aralık · Alt dipler · normal kontrollü
- Spread: 0.05581915%
- RSI 5m/1h: 43.6281352 / 56.91368925
- BTC risk skoru: 70
- Vol persentil: 40.48096192
- Crash hızı: -0.38910506

### Grid Özeti

- Alış: 2 kademe · dağılım [40.0, 60.0]
- Satış: 3 kademe · dağılım [15.0, 30.0, 55.0]
- Hedef: coin %42.0 · USDT %58.0

### Güvenlik

- Max exposure: %43.87
- Worst exposure: %43.62
- Aktif alış bütçesi: 16.24 USDT
- Fee bad: True
- Güvenlik sonucu: Kontrollü grid / fee verisi eksik

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 62/100. Rejim Dengeli aralık, risk durumu normal kontrollü. Risk skoru 58/100, fırsat skoru 35/100. Volatilite 65, BTC piyasa riski 70. . Base tahsisi %42.0, quote %58.0, maksimum base exposure %43.9 ile sınırlandı. Alışlar 2 kademeye bölündü; grid aralığı alış %8.65 / satış %5.51. Dengeleme: Base/quote hedefi anlamlı değişti ancak piyasa güvenlik koşulları uygun olmadığı için rebalance ertelendi (fee_bad).
```

## RNDRUSDT — 50.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: RNDRUSDT
- Kategori: AI / narrative coin
- Girilen bütçe: 50.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 25/100
- Parametre skoru: 62/100
- Route: `A4|R13|D1|S4|V4|K2|L3`
- Shelf: `DPLV5_A4_R13_D1_S4_V4_K2_L3`

### Piyasa Özeti

- Rejim metni: Yüksek volatilite düzensizliği · Üst tepeler · normal kontrollü
- Spread: None%
- RSI 5m/1h: 53.37367037 / 52.47623992
- BTC risk skoru: 70
- Vol persentil: 84.56913828
- Crash hızı: -0.67815767

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %32.55 · USDT %67.45

### Güvenlik

- Max exposure: %32.55
- Worst exposure: %100.0
- Aktif alış bütçesi: 33.73 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 62/100. Rejim Şok volatilite. Risk durumu normal kontrollü. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## RNDRUSDT — 100.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: RNDRUSDT
- Kategori: AI / narrative coin
- Girilen bütçe: 100.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 25/100
- Parametre skoru: 62/100
- Route: `A4|R13|D1|S4|V4|K2|L3`
- Shelf: `DPLV5_A4_R13_D1_S4_V4_K2_L3`

### Piyasa Özeti

- Rejim metni: Yüksek volatilite düzensizliği · Üst tepeler · normal kontrollü
- Spread: None%
- RSI 5m/1h: 53.37367037 / 52.47623992
- BTC risk skoru: 70
- Vol persentil: 84.56913828
- Crash hızı: -0.67815767

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %32.55 · USDT %67.45

### Güvenlik

- Max exposure: %32.55
- Worst exposure: %100.0
- Aktif alış bütçesi: 67.45 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 62/100. Rejim Şok volatilite. Risk durumu normal kontrollü. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## RNDRUSDT — 1000.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: RNDRUSDT
- Kategori: AI / narrative coin
- Girilen bütçe: 1000.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: recommended_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 45/100
- Parametre skoru: 62/100
- Route: `A4|R13|D1|S4|V4|K2|L3`
- Shelf: `DPLV5_A4_R13_D1_S4_V4_K2_L3`

### Piyasa Özeti

- Rejim metni: Yüksek volatilite düzensizliği · Üst tepeler · normal kontrollü
- Spread: None%
- RSI 5m/1h: 53.37367037 / 52.47623992
- BTC risk skoru: 70
- Vol persentil: 84.56913828
- Crash hızı: -0.67815767

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %32.55 · USDT %67.45

### Güvenlik

- Max exposure: %32.55
- Worst exposure: %32.55
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 62/100. Rejim Şok volatilite. Risk durumu normal kontrollü. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## AIUSDT — 50.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: AIUSDT
- Kategori: AI / narrative coin
- Girilen bütçe: 50.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: no_trade
- Deployable: hayır
- Final action: NO_TRADE
- Güven: 38/100
- Parametre skoru: 42/100
- Route: `A6|R4|D2|S1|V3|K1|L4`
- Shelf: `DPLV5_A6_R4_D2_S1_V3_K1_L4`

### Piyasa Özeti

- Rejim metni: Volatil aralık · Aralık orta bölge · savunmacı
- Spread: 0.54200542%
- RSI 5m/1h: 52.43764657 / 49.97613302
- BTC risk skoru: 70
- Vol persentil: 64.62925852
- Crash hızı: -0.54054054

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %21.92 · USDT %78.08

### Güvenlik

- Max exposure: %None
- Worst exposure: %None
- Aktif alış bütçesi: None USDT
- Fee bad: False
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 42/100. Rejim Volatil aralık. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil, spread/fee verimliliği zayıf, likidite düşük, engeller: likidite çok düşük. Bu koşulda yeni alış veya satış yönetimi önerilmedi.
```

## AIUSDT — 100.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: AIUSDT
- Kategori: AI / narrative coin
- Girilen bütçe: 100.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: no_trade
- Deployable: hayır
- Final action: NO_TRADE
- Güven: 38/100
- Parametre skoru: 42/100
- Route: `A6|R4|D2|S1|V3|K1|L4`
- Shelf: `DPLV5_A6_R4_D2_S1_V3_K1_L4`

### Piyasa Özeti

- Rejim metni: Volatil aralık · Aralık orta bölge · savunmacı
- Spread: 0.54200542%
- RSI 5m/1h: 52.43764657 / 49.97613302
- BTC risk skoru: 70
- Vol persentil: 64.62925852
- Crash hızı: -0.54054054

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %21.92 · USDT %78.08

### Güvenlik

- Max exposure: %None
- Worst exposure: %None
- Aktif alış bütçesi: None USDT
- Fee bad: False
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 42/100. Rejim Volatil aralık. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil, spread/fee verimliliği zayıf, likidite düşük, engeller: likidite çok düşük. Bu koşulda yeni alış veya satış yönetimi önerilmedi.
```

## AIUSDT — 1000.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: AIUSDT
- Kategori: AI / narrative coin
- Girilen bütçe: 1000.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: no_trade
- Deployable: hayır
- Final action: NO_TRADE
- Güven: 38/100
- Parametre skoru: 42/100
- Route: `A6|R4|D2|S1|V3|K1|L4`
- Shelf: `DPLV5_A6_R4_D2_S1_V3_K1_L4`

### Piyasa Özeti

- Rejim metni: Volatil aralık · Aralık orta bölge · savunmacı
- Spread: 0.54200542%
- RSI 5m/1h: 52.43764657 / 49.97613302
- BTC risk skoru: 70
- Vol persentil: 64.62925852
- Crash hızı: -0.54054054

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %21.92 · USDT %78.08

### Güvenlik

- Max exposure: %None
- Worst exposure: %None
- Aktif alış bütçesi: None USDT
- Fee bad: False
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 42/100. Rejim Volatil aralık. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil, spread/fee verimliliği zayıf, likidite düşük, engeller: likidite çok düşük. Bu koşulda yeni alış veya satış yönetimi önerilmedi.
```

## WLDUSDT — 50.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: WLDUSDT
- Kategori: AI / narrative coin
- Girilen bütçe: 50.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 30/100
- Parametre skoru: 58/100
- Route: `A3|R3|D1|S4|V4|K1|L2`
- Shelf: `DPLV5_A3_R3_D1_S4_V4_K1_L2`

### Piyasa Özeti

- Rejim metni: Düşük volatilite sıkışma · Üst tepeler · savunmacı
- Spread: 0.02127433%
- RSI 5m/1h: 62.73483416 / 50.50291323
- BTC risk skoru: 70
- Vol persentil: 9.61923848
- Crash hızı: -0.08550663

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %34.12 · USDT %65.88

### Güvenlik

- Max exposure: %34.12
- Worst exposure: %100.0
- Aktif alış bütçesi: 32.94 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| INFO | MIN_NOTIONAL_LIMITED_EXPECTED | Piyasa tamamen kötü değil; bütçe/min-notional nedeniyle kontrollü grid beklenmiyor. | min_notional_limited_grid |

### Ham cevap özeti

```
Parametre Skoru 58/100. Rejim Düşük volatilite sıkışma. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## WLDUSDT — 100.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: WLDUSDT
- Kategori: AI / narrative coin
- Girilen bütçe: 100.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: first_start_buy_only
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 50/100
- Parametre skoru: 58/100
- Route: `A3|R3|D1|S4|V4|K1|L2`
- Shelf: `DPLV5_A3_R3_D1_S4_V4_K1_L2`

### Piyasa Özeti

- Rejim metni: Düşük volatilite sıkışma · Üst tepeler · savunmacı
- Spread: 0.02127433%
- RSI 5m/1h: 62.73483416 / 50.50291323
- BTC risk skoru: 70
- Vol persentil: 9.61923848
- Crash hızı: -0.08550663

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %34.12 · USDT %65.88

### Güvenlik

- Max exposure: %34.12
- Worst exposure: %34.12
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 58/100. Rejim Düşük volatilite sıkışma. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## WLDUSDT — 1000.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: WLDUSDT
- Kategori: AI / narrative coin
- Girilen bütçe: 1000.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: recommended_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 50/100
- Parametre skoru: 58/100
- Route: `A3|R3|D1|S4|V4|K1|L2`
- Shelf: `DPLV5_A3_R3_D1_S4_V4_K1_L2`

### Piyasa Özeti

- Rejim metni: Düşük volatilite sıkışma · Üst tepeler · savunmacı
- Spread: 0.02127433%
- RSI 5m/1h: 62.73483416 / 50.50291323
- BTC risk skoru: 70
- Vol persentil: 9.61923848
- Crash hızı: -0.08550663

### Grid Özeti

- Alış: 3 kademe · dağılım []
- Satış: 3 kademe · dağılım []
- Hedef: coin %34.12 · USDT %65.88

### Güvenlik

- Max exposure: %34.12
- Worst exposure: %34.12
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 58/100. Rejim Düşük volatilite sıkışma. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## FILUSDT — 50.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: FILUSDT
- Kategori: Major alt
- Girilen bütçe: 50.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 24/100
- Parametre skoru: 58/100
- Route: `A6|R5|D1|S4|V3|K1|L3`
- Shelf: `DPLV5_A6_R5_D1_S4_V3_K1_L3`

### Piyasa Özeti

- Rejim metni: Kırılım öncesi sıkışma · Üst tepeler · savunmacı
- Spread: 0.13342228%
- RSI 5m/1h: 57.22166735 / 55.82032411
- BTC risk skoru: 70
- Vol persentil: 33.81763527
- Crash hızı: -0.39893617

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %30.41 · USDT %69.59

### Güvenlik

- Max exposure: %30.41
- Worst exposure: %100.0
- Aktif alış bütçesi: 34.8 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 58/100. Rejim Kırılım öncesi sıkışma / kırılım hazırlığı. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## FILUSDT — 100.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: FILUSDT
- Kategori: Major alt
- Girilen bütçe: 100.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 24/100
- Parametre skoru: 58/100
- Route: `A6|R5|D1|S4|V3|K1|L3`
- Shelf: `DPLV5_A6_R5_D1_S4_V3_K1_L3`

### Piyasa Özeti

- Rejim metni: Kırılım öncesi sıkışma · Üst tepeler · savunmacı
- Spread: 0.13342228%
- RSI 5m/1h: 57.22166735 / 55.82032411
- BTC risk skoru: 70
- Vol persentil: 33.81763527
- Crash hızı: -0.39893617

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %30.41 · USDT %69.59

### Güvenlik

- Max exposure: %30.41
- Worst exposure: %100.0
- Aktif alış bütçesi: 69.59 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 58/100. Rejim Kırılım öncesi sıkışma / kırılım hazırlığı. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## FILUSDT — 1000.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: FILUSDT
- Kategori: Major alt
- Girilen bütçe: 1000.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: recommended_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 44/100
- Parametre skoru: 58/100
- Route: `A6|R5|D1|S4|V3|K1|L3`
- Shelf: `DPLV5_A6_R5_D1_S4_V3_K1_L3`

### Piyasa Özeti

- Rejim metni: Kırılım öncesi sıkışma · Üst tepeler · savunmacı
- Spread: 0.13342228%
- RSI 5m/1h: 57.22166735 / 55.82032411
- BTC risk skoru: 70
- Vol persentil: 33.81763527
- Crash hızı: -0.39893617

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %30.41 · USDT %69.59

### Güvenlik

- Max exposure: %30.41
- Worst exposure: %30.41
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 58/100. Rejim Kırılım öncesi sıkışma / kırılım hazırlığı. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## ICPUSDT — 50.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: ICPUSDT
- Kategori: Major alt
- Girilen bütçe: 50.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 25/100
- Parametre skoru: 60/100
- Route: `A6|R3|D2|S1|V3|K1|L3`
- Shelf: `DPLV5_A6_R3_D2_S1_V3_K1_L3`

### Piyasa Özeti

- Rejim metni: Düşük volatilite sıkışma · Aralık orta bölge · savunmacı
- Spread: 0.04558924%
- RSI 5m/1h: 54.19530683 / 53.38679781
- BTC risk skoru: 70
- Vol persentil: 17.23446894
- Crash hızı: -0.18239854

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %26.61 · USDT %73.39

### Güvenlik

- Max exposure: %26.61
- Worst exposure: %100.0
- Aktif alış bütçesi: 36.7 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| INFO | MIN_NOTIONAL_LIMITED_EXPECTED | Piyasa tamamen kötü değil; bütçe/min-notional nedeniyle kontrollü grid beklenmiyor. | min_notional_limited_grid |

### Ham cevap özeti

```
Parametre Skoru 60/100. Rejim Düşük volatilite sıkışma. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## ICPUSDT — 100.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: ICPUSDT
- Kategori: Major alt
- Girilen bütçe: 100.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 25/100
- Parametre skoru: 60/100
- Route: `A6|R3|D2|S1|V3|K1|L3`
- Shelf: `DPLV5_A6_R3_D2_S1_V3_K1_L3`

### Piyasa Özeti

- Rejim metni: Düşük volatilite sıkışma · Aralık orta bölge · savunmacı
- Spread: 0.04558924%
- RSI 5m/1h: 54.19530683 / 53.38679781
- BTC risk skoru: 70
- Vol persentil: 17.23446894
- Crash hızı: -0.18239854

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %26.61 · USDT %73.39

### Güvenlik

- Max exposure: %26.61
- Worst exposure: %100.0
- Aktif alış bütçesi: 73.39 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| INFO | MIN_NOTIONAL_LIMITED_EXPECTED | Piyasa tamamen kötü değil; bütçe/min-notional nedeniyle kontrollü grid beklenmiyor. | min_notional_limited_grid |

### Ham cevap özeti

```
Parametre Skoru 60/100. Rejim Düşük volatilite sıkışma. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## ICPUSDT — 1000.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: ICPUSDT
- Kategori: Major alt
- Girilen bütçe: 1000.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: recommended_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 45/100
- Parametre skoru: 60/100
- Route: `A6|R3|D2|S1|V3|K1|L3`
- Shelf: `DPLV5_A6_R3_D2_S1_V3_K1_L3`

### Piyasa Özeti

- Rejim metni: Düşük volatilite sıkışma · Aralık orta bölge · savunmacı
- Spread: 0.04558924%
- RSI 5m/1h: 54.19530683 / 53.38679781
- BTC risk skoru: 70
- Vol persentil: 17.23446894
- Crash hızı: -0.18239854

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %26.61 · USDT %73.39

### Güvenlik

- Max exposure: %26.61
- Worst exposure: %26.61
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 60/100. Rejim Düşük volatilite sıkışma. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## GALAUSDT — 50.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: GALAUSDT
- Kategori: Game/metaverse
- Girilen bütçe: 50.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 29/100
- Parametre skoru: 47/100
- Route: `A6|R3|D1|S4|V2|K1|L3`
- Shelf: `DPLV5_A6_R3_D1_S4_V2_K1_L3`

### Piyasa Özeti

- Rejim metni: Düşük volatilite sıkışma · Üst tepeler · savunmacı
- Spread: 0.04313133%
- RSI 5m/1h: 63.57115091 / 52.51773249
- BTC risk skoru: 70
- Vol persentil: 8.96793587
- Crash hızı: -0.21542439

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %26.61 · USDT %73.39

### Güvenlik

- Max exposure: %26.61
- Worst exposure: %100.0
- Aktif alış bütçesi: 36.7 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| INFO | MIN_NOTIONAL_LIMITED_EXPECTED | Piyasa tamamen kötü değil; bütçe/min-notional nedeniyle kontrollü grid beklenmiyor. | min_notional_limited_grid |

### Ham cevap özeti

```
Parametre Skoru 47/100. Rejim Düşük volatilite sıkışma. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## GALAUSDT — 100.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: GALAUSDT
- Kategori: Game/metaverse
- Girilen bütçe: 100.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 29/100
- Parametre skoru: 47/100
- Route: `A6|R3|D1|S4|V2|K1|L3`
- Shelf: `DPLV5_A6_R3_D1_S4_V2_K1_L3`

### Piyasa Özeti

- Rejim metni: Düşük volatilite sıkışma · Üst tepeler · savunmacı
- Spread: 0.04313133%
- RSI 5m/1h: 63.57115091 / 52.51773249
- BTC risk skoru: 70
- Vol persentil: 8.96793587
- Crash hızı: -0.21542439

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %26.61 · USDT %73.39

### Güvenlik

- Max exposure: %26.61
- Worst exposure: %100.0
- Aktif alış bütçesi: 73.39 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| INFO | MIN_NOTIONAL_LIMITED_EXPECTED | Piyasa tamamen kötü değil; bütçe/min-notional nedeniyle kontrollü grid beklenmiyor. | min_notional_limited_grid |

### Ham cevap özeti

```
Parametre Skoru 47/100. Rejim Düşük volatilite sıkışma. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## GALAUSDT — 1000.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: GALAUSDT
- Kategori: Game/metaverse
- Girilen bütçe: 1000.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: recommended_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 49/100
- Parametre skoru: 47/100
- Route: `A6|R3|D1|S4|V2|K1|L3`
- Shelf: `DPLV5_A6_R3_D1_S4_V2_K1_L3`

### Piyasa Özeti

- Rejim metni: Düşük volatilite sıkışma · Üst tepeler · savunmacı
- Spread: 0.04313133%
- RSI 5m/1h: 63.57115091 / 52.51773249
- BTC risk skoru: 70
- Vol persentil: 8.96793587
- Crash hızı: -0.21542439

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %26.61 · USDT %73.39

### Güvenlik

- Max exposure: %26.61
- Worst exposure: %26.61
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 47/100. Rejim Düşük volatilite sıkışma. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## SANDUSDT — 50.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: SANDUSDT
- Kategori: Game/metaverse
- Girilen bütçe: 50.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 30/100
- Parametre skoru: 47/100
- Route: `A6|R3|D1|S4|V2|K1|L3`
- Shelf: `DPLV5_A6_R3_D1_S4_V2_K1_L3`

### Piyasa Özeti

- Rejim metni: Düşük volatilite sıkışma · Üst tepeler · savunmacı
- Spread: 0.02088773%
- RSI 5m/1h: 68.99953979 / 59.0343548
- BTC risk skoru: 70
- Vol persentil: 5.26052104
- Crash hızı: -0.22978901

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %24.48 · USDT %75.52

### Güvenlik

- Max exposure: %24.48
- Worst exposure: %100.0
- Aktif alış bütçesi: 37.76 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| INFO | MIN_NOTIONAL_LIMITED_EXPECTED | Piyasa tamamen kötü değil; bütçe/min-notional nedeniyle kontrollü grid beklenmiyor. | min_notional_limited_grid |

### Ham cevap özeti

```
Parametre Skoru 47/100. Rejim Düşük volatilite sıkışma. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## SANDUSDT — 100.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: SANDUSDT
- Kategori: Game/metaverse
- Girilen bütçe: 100.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 30/100
- Parametre skoru: 47/100
- Route: `A6|R3|D1|S4|V2|K1|L3`
- Shelf: `DPLV5_A6_R3_D1_S4_V2_K1_L3`

### Piyasa Özeti

- Rejim metni: Düşük volatilite sıkışma · Üst tepeler · savunmacı
- Spread: 0.02089646%
- RSI 5m/1h: 68.99953979 / 59.0343548
- BTC risk skoru: 70
- Vol persentil: 5.26052104
- Crash hızı: -0.22978901

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %24.48 · USDT %75.52

### Güvenlik

- Max exposure: %24.48
- Worst exposure: %100.0
- Aktif alış bütçesi: 75.52 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| INFO | MIN_NOTIONAL_LIMITED_EXPECTED | Piyasa tamamen kötü değil; bütçe/min-notional nedeniyle kontrollü grid beklenmiyor. | min_notional_limited_grid |

### Ham cevap özeti

```
Parametre Skoru 47/100. Rejim Düşük volatilite sıkışma. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## SANDUSDT — 1000.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: SANDUSDT
- Kategori: Game/metaverse
- Girilen bütçe: 1000.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: recommended_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 50/100
- Parametre skoru: 47/100
- Route: `A6|R3|D1|S4|V2|K1|L3`
- Shelf: `DPLV5_A6_R3_D1_S4_V2_K1_L3`

### Piyasa Özeti

- Rejim metni: Düşük volatilite sıkışma · Üst tepeler · savunmacı
- Spread: 0.02089646%
- RSI 5m/1h: 68.99953979 / 59.0343548
- BTC risk skoru: 70
- Vol persentil: 5.26052104
- Crash hızı: -0.22978901

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %24.48 · USDT %75.52

### Güvenlik

- Max exposure: %24.48
- Worst exposure: %24.48
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 47/100. Rejim Düşük volatilite sıkışma. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## MANAUSDT — 50.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: MANAUSDT
- Kategori: Game/metaverse
- Girilen bütçe: 50.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 27/100
- Parametre skoru: 44/100
- Route: `A6|R3|D1|S4|V3|K1|L3`
- Shelf: `DPLV5_A6_R3_D1_S4_V3_K1_L3`

### Piyasa Özeti

- Rejim metni: Düşük volatilite sıkışma · Üst tepeler · savunmacı
- Spread: 0.15278839%
- RSI 5m/1h: 66.42408693 / 52.11713399
- BTC risk skoru: 70
- Vol persentil: 10.22044088
- Crash hızı: -0.1529052

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %24.48 · USDT %75.52

### Güvenlik

- Max exposure: %24.48
- Worst exposure: %100.0
- Aktif alış bütçesi: 37.76 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 44/100. Rejim Düşük volatilite sıkışma. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## MANAUSDT — 100.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: MANAUSDT
- Kategori: Game/metaverse
- Girilen bütçe: 100.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 27/100
- Parametre skoru: 44/100
- Route: `A6|R3|D1|S4|V3|K1|L3`
- Shelf: `DPLV5_A6_R3_D1_S4_V3_K1_L3`

### Piyasa Özeti

- Rejim metni: Düşük volatilite sıkışma · Üst tepeler · savunmacı
- Spread: 0.15278839%
- RSI 5m/1h: 66.42408693 / 52.11713399
- BTC risk skoru: 70
- Vol persentil: 10.22044088
- Crash hızı: -0.1529052

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %24.48 · USDT %75.52

### Güvenlik

- Max exposure: %24.48
- Worst exposure: %100.0
- Aktif alış bütçesi: 75.52 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 44/100. Rejim Düşük volatilite sıkışma. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## MANAUSDT — 1000.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: MANAUSDT
- Kategori: Game/metaverse
- Girilen bütçe: 1000.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: recommended_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 47/100
- Parametre skoru: 44/100
- Route: `A6|R3|D1|S4|V3|K1|L3`
- Shelf: `DPLV5_A6_R3_D1_S4_V3_K1_L3`

### Piyasa Özeti

- Rejim metni: Düşük volatilite sıkışma · Üst tepeler · savunmacı
- Spread: 0.15278839%
- RSI 5m/1h: 66.42408693 / 52.11713399
- BTC risk skoru: 70
- Vol persentil: 10.22044088
- Crash hızı: -0.1529052

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %24.48 · USDT %75.52

### Güvenlik

- Max exposure: %24.48
- Worst exposure: %24.48
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 44/100. Rejim Düşük volatilite sıkışma. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## AXSUSDT — 50.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: AXSUSDT
- Kategori: Game/metaverse
- Girilen bütçe: 50.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 27/100
- Parametre skoru: 44/100
- Route: `A6|R12|D1|S4|V3|K1|L3`
- Shelf: `DPLV5_A6_R12_D1_S4_V3_K1_L3`

### Piyasa Özeti

- Rejim metni: Kapitülasyon tepkisi · Üst tepeler · savunmacı
- Spread: 0.10055304%
- RSI 5m/1h: 60.62393345 / 45.69110013
- BTC risk skoru: 70
- Vol persentil: 3.25651303
- Crash hızı: -0.20100503

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %22.81 · USDT %77.19

### Güvenlik

- Max exposure: %22.81
- Worst exposure: %100.0
- Aktif alış bütçesi: 38.59 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 44/100. Rejim Kapitülasyon tepkisi. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## AXSUSDT — 100.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: AXSUSDT
- Kategori: Game/metaverse
- Girilen bütçe: 100.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 27/100
- Parametre skoru: 44/100
- Route: `A6|R12|D1|S4|V3|K1|L3`
- Shelf: `DPLV5_A6_R12_D1_S4_V3_K1_L3`

### Piyasa Özeti

- Rejim metni: Kapitülasyon tepkisi · Üst tepeler · savunmacı
- Spread: 0.10055304%
- RSI 5m/1h: 60.62393345 / 45.69110013
- BTC risk skoru: 70
- Vol persentil: 3.25651303
- Crash hızı: -0.20100503

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %22.81 · USDT %77.19

### Güvenlik

- Max exposure: %22.81
- Worst exposure: %100.0
- Aktif alış bütçesi: 77.19 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 44/100. Rejim Kapitülasyon tepkisi. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## AXSUSDT — 1000.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: AXSUSDT
- Kategori: Game/metaverse
- Girilen bütçe: 1000.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: recommended_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 47/100
- Parametre skoru: 44/100
- Route: `A6|R12|D1|S4|V3|K1|L3`
- Shelf: `DPLV5_A6_R12_D1_S4_V3_K1_L3`

### Piyasa Özeti

- Rejim metni: Kapitülasyon tepkisi · Üst tepeler · savunmacı
- Spread: 0.10055304%
- RSI 5m/1h: 60.62393345 / 45.69110013
- BTC risk skoru: 70
- Vol persentil: 3.25651303
- Crash hızı: -0.20100503

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %22.81 · USDT %77.19

### Güvenlik

- Max exposure: %22.81
- Worst exposure: %22.81
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 44/100. Rejim Kapitülasyon tepkisi. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## ENJUSDT — 50.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: ENJUSDT
- Kategori: Game/metaverse
- Girilen bütçe: 50.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 29/100
- Parametre skoru: 47/100
- Route: `A6|R3|D2|S4|V3|K1|L3`
- Shelf: `DPLV5_A6_R3_D2_S4_V3_K1_L3`

### Piyasa Özeti

- Rejim metni: Düşük volatilite sıkışma · Üst tepeler · savunmacı
- Spread: 0.03370976%
- RSI 5m/1h: 55.08868704 / 47.69953794
- BTC risk skoru: 70
- Vol persentil: 20.39078156
- Crash hızı: -0.30272452

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %26.61 · USDT %73.39

### Güvenlik

- Max exposure: %26.61
- Worst exposure: %100.0
- Aktif alış bütçesi: 36.7 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| INFO | MIN_NOTIONAL_LIMITED_EXPECTED | Piyasa tamamen kötü değil; bütçe/min-notional nedeniyle kontrollü grid beklenmiyor. | min_notional_limited_grid |

### Ham cevap özeti

```
Parametre Skoru 47/100. Rejim Düşük volatilite sıkışma. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## ENJUSDT — 100.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: ENJUSDT
- Kategori: Game/metaverse
- Girilen bütçe: 100.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 29/100
- Parametre skoru: 47/100
- Route: `A6|R3|D2|S4|V3|K1|L3`
- Shelf: `DPLV5_A6_R3_D2_S4_V3_K1_L3`

### Piyasa Özeti

- Rejim metni: Düşük volatilite sıkışma · Üst tepeler · savunmacı
- Spread: 0.03370976%
- RSI 5m/1h: 55.08868704 / 47.69953794
- BTC risk skoru: 70
- Vol persentil: 20.39078156
- Crash hızı: -0.30272452

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %26.61 · USDT %73.39

### Güvenlik

- Max exposure: %26.61
- Worst exposure: %100.0
- Aktif alış bütçesi: 73.39 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| INFO | MIN_NOTIONAL_LIMITED_EXPECTED | Piyasa tamamen kötü değil; bütçe/min-notional nedeniyle kontrollü grid beklenmiyor. | min_notional_limited_grid |

### Ham cevap özeti

```
Parametre Skoru 47/100. Rejim Düşük volatilite sıkışma. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## ENJUSDT — 1000.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: ENJUSDT
- Kategori: Game/metaverse
- Girilen bütçe: 1000.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: recommended_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 49/100
- Parametre skoru: 47/100
- Route: `A6|R3|D2|S4|V3|K1|L3`
- Shelf: `DPLV5_A6_R3_D2_S4_V3_K1_L3`

### Piyasa Özeti

- Rejim metni: Düşük volatilite sıkışma · Üst tepeler · savunmacı
- Spread: 0.03370976%
- RSI 5m/1h: 55.08868704 / 47.69953794
- BTC risk skoru: 70
- Vol persentil: 20.39078156
- Crash hızı: -0.30272452

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %26.61 · USDT %73.39

### Güvenlik

- Max exposure: %26.61
- Worst exposure: %26.61
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 47/100. Rejim Düşük volatilite sıkışma. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## PEPEUSDT — 50.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: PEPEUSDT
- Kategori: Meme
- Girilen bütçe: 50.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: no_trade
- Deployable: hayır
- Final action: NO_TRADE
- Güven: 43/100
- Parametre skoru: 49/100
- Route: `A5|R7|D1|S4|V4|K1|L3`
- Shelf: `DPLV5_A5_R7_D1_S4_V4_K1_L3`

### Piyasa Özeti

- Rejim metni: Toparlanma · Üst tepeler · savunmacı
- Spread: 0.40733198%
- RSI 5m/1h: 68.84943859 / 65.18851563
- BTC risk skoru: 70
- Vol persentil: 68.53707415
- Crash hızı: 0.0

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %26.39 · USDT %73.61

### Güvenlik

- Max exposure: %None
- Worst exposure: %None
- Aktif alış bütçesi: None USDT
- Fee bad: False
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 49/100. Rejim Toparlanma. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil, spread/fee verimliliği zayıf, engeller: spread çok yüksek. Bu koşulda yeni alış veya satış yönetimi önerilmedi.
```

## PEPEUSDT — 100.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: PEPEUSDT
- Kategori: Meme
- Girilen bütçe: 100.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: no_trade
- Deployable: hayır
- Final action: NO_TRADE
- Güven: 43/100
- Parametre skoru: 49/100
- Route: `A5|R7|D1|S4|V4|K1|L3`
- Shelf: `DPLV5_A5_R7_D1_S4_V4_K1_L3`

### Piyasa Özeti

- Rejim metni: Toparlanma · Üst tepeler · savunmacı
- Spread: 0.40733198%
- RSI 5m/1h: 68.84943859 / 65.18851563
- BTC risk skoru: 70
- Vol persentil: 68.53707415
- Crash hızı: 0.0

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %26.39 · USDT %73.61

### Güvenlik

- Max exposure: %None
- Worst exposure: %None
- Aktif alış bütçesi: None USDT
- Fee bad: False
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 49/100. Rejim Toparlanma. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil, spread/fee verimliliği zayıf, engeller: spread çok yüksek. Bu koşulda yeni alış veya satış yönetimi önerilmedi.
```

## PEPEUSDT — 1000.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: PEPEUSDT
- Kategori: Meme
- Girilen bütçe: 1000.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: no_trade
- Deployable: hayır
- Final action: NO_TRADE
- Güven: 43/100
- Parametre skoru: 49/100
- Route: `A5|R7|D1|S4|V4|K1|L3`
- Shelf: `DPLV5_A5_R7_D1_S4_V4_K1_L3`

### Piyasa Özeti

- Rejim metni: Toparlanma · Üst tepeler · savunmacı
- Spread: 0.40733198%
- RSI 5m/1h: 68.84943859 / 65.18851563
- BTC risk skoru: 70
- Vol persentil: 68.53707415
- Crash hızı: 0.0

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %26.39 · USDT %73.61

### Güvenlik

- Max exposure: %None
- Worst exposure: %None
- Aktif alış bütçesi: None USDT
- Fee bad: False
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 49/100. Rejim Toparlanma. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil, spread/fee verimliliği zayıf, engeller: spread çok yüksek. Bu koşulda yeni alış veya satış yönetimi önerilmedi.
```

## FLOKIUSDT — 50.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: FLOKIUSDT
- Kategori: Meme
- Girilen bütçe: 50.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 29/100
- Parametre skoru: 46/100
- Route: `A5|R3|D1|S4|V3|K1|L3`
- Shelf: `DPLV5_A5_R3_D1_S4_V3_K1_L3`

### Piyasa Özeti

- Rejim metni: Düşük volatilite sıkışma · Üst tepeler · savunmacı
- Spread: 0.04499438%
- RSI 5m/1h: 70.19549343 / 55.09347764
- BTC risk skoru: 70
- Vol persentil: 22.54509018
- Crash hızı: -0.090009

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %26.76 · USDT %73.24

### Güvenlik

- Max exposure: %26.76
- Worst exposure: %100.0
- Aktif alış bütçesi: 36.62 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| INFO | MIN_NOTIONAL_LIMITED_EXPECTED | Piyasa tamamen kötü değil; bütçe/min-notional nedeniyle kontrollü grid beklenmiyor. | min_notional_limited_grid |

### Ham cevap özeti

```
Parametre Skoru 46/100. Rejim Düşük volatilite sıkışma. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## FLOKIUSDT — 100.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: FLOKIUSDT
- Kategori: Meme
- Girilen bütçe: 100.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 29/100
- Parametre skoru: 46/100
- Route: `A5|R3|D1|S4|V3|K1|L3`
- Shelf: `DPLV5_A5_R3_D1_S4_V3_K1_L3`

### Piyasa Özeti

- Rejim metni: Düşük volatilite sıkışma · Üst tepeler · savunmacı
- Spread: 0.04499438%
- RSI 5m/1h: 70.19549343 / 55.09347764
- BTC risk skoru: 70
- Vol persentil: 22.54509018
- Crash hızı: -0.090009

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %26.76 · USDT %73.24

### Güvenlik

- Max exposure: %26.76
- Worst exposure: %100.0
- Aktif alış bütçesi: 73.24 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 46/100. Rejim Düşük volatilite sıkışma. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## FLOKIUSDT — 1000.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: FLOKIUSDT
- Kategori: Meme
- Girilen bütçe: 1000.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: recommended_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 49/100
- Parametre skoru: 46/100
- Route: `A5|R3|D1|S4|V3|K1|L3`
- Shelf: `DPLV5_A5_R3_D1_S4_V3_K1_L3`

### Piyasa Özeti

- Rejim metni: Düşük volatilite sıkışma · Üst tepeler · savunmacı
- Spread: 0.04499438%
- RSI 5m/1h: 70.19549343 / 55.09347764
- BTC risk skoru: 70
- Vol persentil: 22.54509018
- Crash hızı: -0.090009

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %26.76 · USDT %73.24

### Güvenlik

- Max exposure: %26.76
- Worst exposure: %26.76
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 46/100. Rejim Düşük volatilite sıkışma. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## SHIBUSDT — 50.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: SHIBUSDT
- Kategori: Meme
- Girilen bütçe: 50.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 25/100
- Parametre skoru: 61/100
- Route: `A5|R4|D2|S4|V3|K1|L3`
- Shelf: `DPLV5_A5_R4_D2_S4_V3_K1_L3`

### Piyasa Özeti

- Rejim metni: Volatil aralık · Üst tepeler · savunmacı
- Spread: 0.23282887%
- RSI 5m/1h: 54.73841577 / 58.66703813
- BTC risk skoru: 70
- Vol persentil: 64.82965932
- Crash hızı: -0.23255814

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %30.13 · USDT %69.87

### Güvenlik

- Max exposure: %30.13
- Worst exposure: %100.0
- Aktif alış bütçesi: 34.94 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 61/100. Rejim Volatil aralık. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## SHIBUSDT — 100.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: SHIBUSDT
- Kategori: Meme
- Girilen bütçe: 100.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 25/100
- Parametre skoru: 61/100
- Route: `A5|R4|D2|S4|V3|K1|L3`
- Shelf: `DPLV5_A5_R4_D2_S4_V3_K1_L3`

### Piyasa Özeti

- Rejim metni: Volatil aralık · Üst tepeler · savunmacı
- Spread: 0.23282887%
- RSI 5m/1h: 54.73841577 / 58.66703813
- BTC risk skoru: 70
- Vol persentil: 64.82965932
- Crash hızı: -0.23255814

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %30.13 · USDT %69.87

### Güvenlik

- Max exposure: %30.13
- Worst exposure: %100.0
- Aktif alış bütçesi: 69.87 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 61/100. Rejim Volatil aralık. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## SHIBUSDT — 1000.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: SHIBUSDT
- Kategori: Meme
- Girilen bütçe: 1000.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: recommended_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 45/100
- Parametre skoru: 61/100
- Route: `A5|R4|D2|S4|V3|K1|L3`
- Shelf: `DPLV5_A5_R4_D2_S4_V3_K1_L3`

### Piyasa Özeti

- Rejim metni: Volatil aralık · Üst tepeler · savunmacı
- Spread: 0.23282887%
- RSI 5m/1h: 54.73841577 / 58.66703813
- BTC risk skoru: 70
- Vol persentil: 64.82965932
- Crash hızı: -0.23255814

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %30.13 · USDT %69.87

### Güvenlik

- Max exposure: %30.13
- Worst exposure: %30.13
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 61/100. Rejim Volatil aralık. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## BONKUSDT — 50.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: BONKUSDT
- Kategori: Meme
- Girilen bütçe: 50.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 23/100
- Parametre skoru: 56/100
- Route: `A5|R7|D1|S4|V3|K1|L3`
- Shelf: `DPLV5_A5_R7_D1_S4_V3_K1_L3`

### Piyasa Özeti

- Rejim metni: Toparlanma · Üst tepeler · savunmacı
- Spread: 0.23228804%
- RSI 5m/1h: 64.5465946 / 64.81124785
- BTC risk skoru: 70
- Vol persentil: 69.58917836
- Crash hızı: -0.46296296

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %31.17 · USDT %68.83

### Güvenlik

- Max exposure: %31.17
- Worst exposure: %100.0
- Aktif alış bütçesi: 34.41 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 56/100. Rejim Toparlanma. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## BONKUSDT — 100.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: BONKUSDT
- Kategori: Meme
- Girilen bütçe: 100.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 23/100
- Parametre skoru: 56/100
- Route: `A5|R7|D1|S4|V3|K1|L3`
- Shelf: `DPLV5_A5_R7_D1_S4_V3_K1_L3`

### Piyasa Özeti

- Rejim metni: Toparlanma · Üst tepeler · savunmacı
- Spread: 0.23228804%
- RSI 5m/1h: 64.5465946 / 64.81124785
- BTC risk skoru: 70
- Vol persentil: 69.58917836
- Crash hızı: -0.46296296

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %31.17 · USDT %68.83

### Güvenlik

- Max exposure: %31.17
- Worst exposure: %100.0
- Aktif alış bütçesi: 68.83 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 56/100. Rejim Toparlanma. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## BONKUSDT — 1000.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: BONKUSDT
- Kategori: Meme
- Girilen bütçe: 1000.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: recommended_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 43/100
- Parametre skoru: 56/100
- Route: `A5|R7|D1|S4|V3|K1|L3`
- Shelf: `DPLV5_A5_R7_D1_S4_V3_K1_L3`

### Piyasa Özeti

- Rejim metni: Toparlanma · Üst tepeler · savunmacı
- Spread: 0.23228804%
- RSI 5m/1h: 64.5465946 / 64.81124785
- BTC risk skoru: 70
- Vol persentil: 69.58917836
- Crash hızı: -0.46296296

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %31.17 · USDT %68.83

### Güvenlik

- Max exposure: %31.17
- Worst exposure: %31.17
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 56/100. Rejim Toparlanma. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## JTOUSDT — 50.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: JTOUSDT
- Kategori: Low liquidity / risky alt
- Girilen bütçe: 50.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 35/100
- Parametre skoru: 68/100
- Route: `A4|R3|D1|S4|V4|K2|L2`
- Shelf: `DPLV5_A4_R3_D1_S4_V4_K2_L2`

### Piyasa Özeti

- Rejim metni: Düşük volatilite sıkışma · Üst tepeler · normal kontrollü
- Spread: 0.01229634%
- RSI 5m/1h: 61.329832 / 53.20679265
- BTC risk skoru: 70
- Vol persentil: 23.29659319
- Crash hızı: -0.20840995

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %45.03 · USDT %54.97

### Güvenlik

- Max exposure: %45.03
- Worst exposure: %100.0
- Aktif alış bütçesi: 27.48 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 68/100. Rejim Düşük volatilite sıkışma. Risk durumu normal kontrollü. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## JTOUSDT — 100.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: JTOUSDT
- Kategori: Low liquidity / risky alt
- Girilen bütçe: 100.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: first_start_buy_only
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 55/100
- Parametre skoru: 68/100
- Route: `A4|R3|D1|S4|V4|K2|L2`
- Shelf: `DPLV5_A4_R3_D1_S4_V4_K2_L2`

### Piyasa Özeti

- Rejim metni: Düşük volatilite sıkışma · Üst tepeler · normal kontrollü
- Spread: 0.02459117%
- RSI 5m/1h: 61.329832 / 53.20679265
- BTC risk skoru: 70
- Vol persentil: 23.29659319
- Crash hızı: -0.20840995

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %45.03 · USDT %54.97

### Güvenlik

- Max exposure: %45.03
- Worst exposure: %45.03
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 68/100. Rejim Düşük volatilite sıkışma. Risk durumu normal kontrollü. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## JTOUSDT — 1000.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: JTOUSDT
- Kategori: Low liquidity / risky alt
- Girilen bütçe: 1000.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: recommended_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 55/100
- Parametre skoru: 68/100
- Route: `A4|R3|D1|S4|V4|K2|L2`
- Shelf: `DPLV5_A4_R3_D1_S4_V4_K2_L2`

### Piyasa Özeti

- Rejim metni: Düşük volatilite sıkışma · Üst tepeler · normal kontrollü
- Spread: 0.02459117%
- RSI 5m/1h: 61.329832 / 53.20679265
- BTC risk skoru: 70
- Vol persentil: 23.29659319
- Crash hızı: -0.20840995

### Grid Özeti

- Alış: 3 kademe · dağılım []
- Satış: 3 kademe · dağılım []
- Hedef: coin %45.03 · USDT %54.97

### Güvenlik

- Max exposure: %45.03
- Worst exposure: %45.03
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 68/100. Rejim Düşük volatilite sıkışma. Risk durumu normal kontrollü. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## JUPUSDT — 50.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: JUPUSDT
- Kategori: Major alt
- Girilen bütçe: 50.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 26/100
- Parametre skoru: 59/100
- Route: `A4|R5|D1|S4|V4|K1|L2`
- Shelf: `DPLV5_A4_R5_D1_S4_V4_K1_L2`

### Piyasa Özeti

- Rejim metni: Kırılım öncesi sıkışma · Üst tepeler · savunmacı
- Spread: 0.08714597%
- RSI 5m/1h: 76.87355341 / 57.36420057
- BTC risk skoru: 70
- Vol persentil: 34.56913828
- Crash hızı: -0.26246719

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %35.88 · USDT %64.12

### Güvenlik

- Max exposure: %35.88
- Worst exposure: %100.0
- Aktif alış bütçesi: 32.06 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 59/100. Rejim Kırılım öncesi sıkışma / kırılım hazırlığı. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## JUPUSDT — 100.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: JUPUSDT
- Kategori: Major alt
- Girilen bütçe: 100.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: first_start_buy_only
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 46/100
- Parametre skoru: 59/100
- Route: `A4|R5|D1|S4|V4|K1|L2`
- Shelf: `DPLV5_A4_R5_D1_S4_V4_K1_L2`

### Piyasa Özeti

- Rejim metni: Kırılım öncesi sıkışma · Üst tepeler · savunmacı
- Spread: 0.08714597%
- RSI 5m/1h: 76.87355341 / 57.36420057
- BTC risk skoru: 70
- Vol persentil: 34.56913828
- Crash hızı: -0.26246719

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %35.88 · USDT %64.12

### Güvenlik

- Max exposure: %35.88
- Worst exposure: %35.88
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 59/100. Rejim Kırılım öncesi sıkışma / kırılım hazırlığı. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## JUPUSDT — 1000.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: JUPUSDT
- Kategori: Major alt
- Girilen bütçe: 1000.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: recommended_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 46/100
- Parametre skoru: 59/100
- Route: `A4|R5|D1|S4|V4|K1|L2`
- Shelf: `DPLV5_A4_R5_D1_S4_V4_K1_L2`

### Piyasa Özeti

- Rejim metni: Kırılım öncesi sıkışma · Üst tepeler · savunmacı
- Spread: 0.08714597%
- RSI 5m/1h: 76.87355341 / 57.36420057
- BTC risk skoru: 70
- Vol persentil: 34.56913828
- Crash hızı: -0.26246719

### Grid Özeti

- Alış: 3 kademe · dağılım []
- Satış: 3 kademe · dağılım []
- Hedef: coin %35.88 · USDT %64.12

### Güvenlik

- Max exposure: %35.88
- Worst exposure: %35.88
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 59/100. Rejim Kırılım öncesi sıkışma / kırılım hazırlığı. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## TIAUSDT — 50.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: TIAUSDT
- Kategori: Major alt
- Girilen bütçe: 50.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 27/100
- Parametre skoru: 62/100
- Route: `A4|R5|D1|S4|V4|K2|L2`
- Shelf: `DPLV5_A4_R5_D1_S4_V4_K2_L2`

### Piyasa Özeti

- Rejim metni: Kırılım öncesi sıkışma · Üst tepeler · normal kontrollü
- Spread: 0.02638871%
- RSI 5m/1h: 67.59667891 / 56.54031544
- BTC risk skoru: 70
- Vol persentil: 19.18837675
- Crash hızı: -0.15860428

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %47.34 · USDT %52.66

### Güvenlik

- Max exposure: %47.34
- Worst exposure: %100.0
- Aktif alış bütçesi: 26.33 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| INFO | MIN_NOTIONAL_LIMITED_EXPECTED | Piyasa tamamen kötü değil; bütçe/min-notional nedeniyle kontrollü grid beklenmiyor. | min_notional_limited_grid |

### Ham cevap özeti

```
Parametre Skoru 62/100. Rejim Kırılım öncesi sıkışma / kırılım hazırlığı. Risk durumu normal kontrollü. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## TIAUSDT — 100.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: TIAUSDT
- Kategori: Major alt
- Girilen bütçe: 100.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: first_start_buy_only
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 47/100
- Parametre skoru: 62/100
- Route: `A4|R5|D1|S4|V4|K2|L2`
- Shelf: `DPLV5_A4_R5_D1_S4_V4_K2_L2`

### Piyasa Özeti

- Rejim metni: Kırılım öncesi sıkışma · Üst tepeler · normal kontrollü
- Spread: 0.02639567%
- RSI 5m/1h: 67.59667891 / 56.54031544
- BTC risk skoru: 70
- Vol persentil: 19.18837675
- Crash hızı: -0.15860428

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %47.34 · USDT %52.66

### Güvenlik

- Max exposure: %47.34
- Worst exposure: %47.34
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 62/100. Rejim Kırılım öncesi sıkışma / kırılım hazırlığı. Risk durumu normal kontrollü. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## TIAUSDT — 1000.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: TIAUSDT
- Kategori: Major alt
- Girilen bütçe: 1000.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: recommended_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 47/100
- Parametre skoru: 62/100
- Route: `A4|R5|D1|S4|V4|K2|L2`
- Shelf: `DPLV5_A4_R5_D1_S4_V4_K2_L2`

### Piyasa Özeti

- Rejim metni: Kırılım öncesi sıkışma · Üst tepeler · normal kontrollü
- Spread: 0.02639567%
- RSI 5m/1h: 67.59667891 / 56.54031544
- BTC risk skoru: 70
- Vol persentil: 19.18837675
- Crash hızı: -0.15860428

### Grid Özeti

- Alış: 3 kademe · dağılım []
- Satış: 3 kademe · dağılım []
- Hedef: coin %47.34 · USDT %52.66

### Güvenlik

- Max exposure: %47.34
- Worst exposure: %47.34
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 62/100. Rejim Kırılım öncesi sıkışma / kırılım hazırlığı. Risk durumu normal kontrollü. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## PYTHUSDT — 50.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: PYTHUSDT
- Kategori: Major alt
- Girilen bütçe: 50.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 24/100
- Parametre skoru: 57/100
- Route: `A6|R7|D1|S6|V3|K1|L3`
- Shelf: `DPLV5_A6_R7_D1_S6_V3_K1_L3`

### Piyasa Özeti

- Rejim metni: Toparlanma · Kırılım hazırlığı · savunmacı
- Spread: 0.02923549%
- RSI 5m/1h: 58.38861219 / 56.01062371
- BTC risk skoru: 70
- Vol persentil: 7.31462926
- Crash hızı: -0.20449898

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %28.51 · USDT %71.49

### Güvenlik

- Max exposure: %28.51
- Worst exposure: %100.0
- Aktif alış bütçesi: 35.74 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| INFO | MIN_NOTIONAL_LIMITED_EXPECTED | Piyasa tamamen kötü değil; bütçe/min-notional nedeniyle kontrollü grid beklenmiyor. | min_notional_limited_grid |

### Ham cevap özeti

```
Parametre Skoru 57/100. Rejim Toparlanma. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## PYTHUSDT — 100.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: PYTHUSDT
- Kategori: Major alt
- Girilen bütçe: 100.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 24/100
- Parametre skoru: 57/100
- Route: `A6|R7|D1|S6|V3|K1|L3`
- Shelf: `DPLV5_A6_R7_D1_S6_V3_K1_L3`

### Piyasa Özeti

- Rejim metni: Toparlanma · Kırılım hazırlığı · savunmacı
- Spread: 0.0292526%
- RSI 5m/1h: 58.38861219 / 56.01062371
- BTC risk skoru: 70
- Vol persentil: 7.31462926
- Crash hızı: -0.20449898

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %28.51 · USDT %71.49

### Güvenlik

- Max exposure: %28.51
- Worst exposure: %100.0
- Aktif alış bütçesi: 71.49 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| INFO | MIN_NOTIONAL_LIMITED_EXPECTED | Piyasa tamamen kötü değil; bütçe/min-notional nedeniyle kontrollü grid beklenmiyor. | min_notional_limited_grid |

### Ham cevap özeti

```
Parametre Skoru 57/100. Rejim Toparlanma. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## PYTHUSDT — 1000.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: PYTHUSDT
- Kategori: Major alt
- Girilen bütçe: 1000.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: recommended_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 44/100
- Parametre skoru: 57/100
- Route: `A6|R7|D1|S6|V3|K1|L3`
- Shelf: `DPLV5_A6_R7_D1_S6_V3_K1_L3`

### Piyasa Özeti

- Rejim metni: Toparlanma · Kırılım hazırlığı · savunmacı
- Spread: 0.0292526%
- RSI 5m/1h: 58.38861219 / 56.01062371
- BTC risk skoru: 70
- Vol persentil: 7.31462926
- Crash hızı: -0.20449898

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %28.51 · USDT %71.49

### Güvenlik

- Max exposure: %28.51
- Worst exposure: %28.51
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 57/100. Rejim Toparlanma. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## TONUSDT — 50.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: TONUSDT
- Kategori: Major alt
- Girilen bütçe: 50.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 25/100
- Parametre skoru: 58/100
- Route: `A4|R3|D2|S1|V3|K1|L2`
- Shelf: `DPLV5_A4_R3_D2_S1_V3_K1_L2`

### Piyasa Özeti

- Rejim metni: Düşük volatilite sıkışma · Aralık orta bölge · savunmacı
- Spread: 0.06355259%
- RSI 5m/1h: 56.67577368 / 54.91363812
- BTC risk skoru: 70
- Vol persentil: 5.91182365
- Crash hızı: -0.06361323

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %35.0 · USDT %65.0

### Güvenlik

- Max exposure: %37.09
- Worst exposure: %100.0
- Aktif alış bütçesi: 32.5 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 58/100. Rejim Düşük volatilite sıkışma. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## TONUSDT — 100.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: TONUSDT
- Kategori: Major alt
- Girilen bütçe: 100.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: first_start_buy_only
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 45/100
- Parametre skoru: 58/100
- Route: `A4|R3|D2|S1|V3|K1|L2`
- Shelf: `DPLV5_A4_R3_D2_S1_V3_K1_L2`

### Piyasa Özeti

- Rejim metni: Düşük volatilite sıkışma · Aralık orta bölge · savunmacı
- Spread: 0.06355259%
- RSI 5m/1h: 56.67577368 / 54.91363812
- BTC risk skoru: 70
- Vol persentil: 5.91182365
- Crash hızı: -0.06361323

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %35.0 · USDT %65.0

### Güvenlik

- Max exposure: %37.09
- Worst exposure: %35.0
- Aktif alış bütçesi: 0.0 USDT
- Fee bad: True
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 58/100. Rejim Düşük volatilite sıkışma. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil; engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## TONUSDT — 1000.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: TONUSDT
- Kategori: Major alt
- Girilen bütçe: 1000.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: recommended_grid
- Deployable: hayır
- Final action: CONTROLLED_GRID
- Güven: 47/100
- Parametre skoru: 58/100
- Route: `A4|R3|D2|S1|V3|K1|L2`
- Shelf: `DPLV5_A4_R3_D2_S1_V3_K1_L2`

### Piyasa Özeti

- Rejim metni: Düşük volatilite sıkışma · Aralık orta bölge · savunmacı
- Spread: 0.06355259%
- RSI 5m/1h: 56.67577368 / 54.91363812
- BTC risk skoru: 70
- Vol persentil: 5.91182365
- Crash hızı: -0.06361323

### Grid Özeti

- Alış: 2 kademe · dağılım [35.0, 65.0]
- Satış: 3 kademe · dağılım [12.0, 28.0, 60.0]
- Hedef: coin %35.0 · USDT %65.0

### Güvenlik

- Max exposure: %37.09
- Worst exposure: %36.82
- Aktif alış bütçesi: 11.83 USDT
- Fee bad: True
- Güvenlik sonucu: Parametre referans olarak üretildi; spread/risk/fee koşulları nedeniyle kontrollü başlangıç kapalı tutuldu.

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 58/100. Rejim Düşük volatilite sıkışma, risk durumu savunmacı. Risk skoru 44/100, fırsat skoru 50/100. Volatilite 40, BTC piyasa riski 70. . Base tahsisi %35.0, quote %65.0, maksimum base exposure %37.1 ile sınırlandı. Alışlar 2 kademeye bölündü; grid aralığı alış %4.55 / satış %4.14. Dengeleme: Base/quote hedefi anlamlı değişti ancak piyasa güvenlik koşulları uygun olmadığı için rebalance ertelendi (fee_bad).
```

## ASRUSDT — 50.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: ASRUSDT
- Kategori: Fan token / özel yapı
- Girilen bütçe: 50.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: no_trade
- Deployable: hayır
- Final action: NO_TRADE
- Güven: 39/100
- Parametre skoru: 52/100
- Route: `A6|R3|D2|S4|V2|K1|L4`
- Shelf: `DPLV5_A6_R3_D2_S4_V2_K1_L4`

### Piyasa Özeti

- Rejim metni: Düşük volatilite sıkışma · Üst tepeler · savunmacı
- Spread: 0.11396011%
- RSI 5m/1h: 48.6021368 / 48.21389567
- BTC risk skoru: 70
- Vol persentil: 2.40480962
- Crash hızı: -0.22779043

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %21.17 · USDT %78.83

### Güvenlik

- Max exposure: %None
- Worst exposure: %None
- Aktif alış bütçesi: None USDT
- Fee bad: False
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 52/100. Rejim Düşük volatilite sıkışma. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil, likidite düşük, engeller: likidite çok düşük. Bu koşulda yeni alış veya satış yönetimi önerilmedi.
```

## ASRUSDT — 100.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: ASRUSDT
- Kategori: Fan token / özel yapı
- Girilen bütçe: 100.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: no_trade
- Deployable: hayır
- Final action: NO_TRADE
- Güven: 39/100
- Parametre skoru: 52/100
- Route: `A6|R3|D2|S4|V2|K1|L4`
- Shelf: `DPLV5_A6_R3_D2_S4_V2_K1_L4`

### Piyasa Özeti

- Rejim metni: Düşük volatilite sıkışma · Üst tepeler · savunmacı
- Spread: 0.11396011%
- RSI 5m/1h: 48.6021368 / 48.21389567
- BTC risk skoru: 70
- Vol persentil: 2.40480962
- Crash hızı: -0.22779043

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %21.17 · USDT %78.83

### Güvenlik

- Max exposure: %None
- Worst exposure: %None
- Aktif alış bütçesi: None USDT
- Fee bad: False
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 52/100. Rejim Düşük volatilite sıkışma. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil, likidite düşük, engeller: likidite çok düşük. Bu koşulda yeni alış veya satış yönetimi önerilmedi.
```

## ASRUSDT — 1000.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: ASRUSDT
- Kategori: Fan token / özel yapı
- Girilen bütçe: 1000.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: no_trade
- Deployable: hayır
- Final action: NO_TRADE
- Güven: 39/100
- Parametre skoru: 52/100
- Route: `A6|R3|D2|S4|V2|K1|L4`
- Shelf: `DPLV5_A6_R3_D2_S4_V2_K1_L4`

### Piyasa Özeti

- Rejim metni: Düşük volatilite sıkışma · Üst tepeler · savunmacı
- Spread: 0.11396011%
- RSI 5m/1h: 48.6021368 / 48.21389567
- BTC risk skoru: 70
- Vol persentil: 2.40480962
- Crash hızı: -0.22779043

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %21.17 · USDT %78.83

### Güvenlik

- Max exposure: %None
- Worst exposure: %None
- Aktif alış bütçesi: None USDT
- Fee bad: False
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 52/100. Rejim Düşük volatilite sıkışma. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil, likidite düşük, engeller: likidite çok düşük. Bu koşulda yeni alış veya satış yönetimi önerilmedi.
```

## SFPUSDT — 50.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: SFPUSDT
- Kategori: Low liquidity / risky alt
- Girilen bütçe: 50.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: no_trade
- Deployable: hayır
- Final action: NO_TRADE
- Güven: 39/100
- Parametre skoru: 52/100
- Route: `A6|R5|D1|S4|V3|K1|L4`
- Shelf: `DPLV5_A6_R5_D1_S4_V3_K1_L4`

### Piyasa Özeti

- Rejim metni: Kırılım öncesi sıkışma · Üst tepeler · savunmacı
- Spread: 0.13815335%
- RSI 5m/1h: 67.39778355 / 59.41359747
- BTC risk skoru: 70
- Vol persentil: 33.21643287
- Crash hızı: -0.23030861

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %24.19 · USDT %75.81

### Güvenlik

- Max exposure: %None
- Worst exposure: %None
- Aktif alış bütçesi: None USDT
- Fee bad: False
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 52/100. Rejim Kırılım öncesi sıkışma / kırılım hazırlığı. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil, likidite düşük, engeller: likidite çok düşük. Bu koşulda yeni alış veya satış yönetimi önerilmedi.
```

## SFPUSDT — 100.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: SFPUSDT
- Kategori: Low liquidity / risky alt
- Girilen bütçe: 100.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: no_trade
- Deployable: hayır
- Final action: NO_TRADE
- Güven: 39/100
- Parametre skoru: 52/100
- Route: `A6|R5|D1|S4|V3|K1|L4`
- Shelf: `DPLV5_A6_R5_D1_S4_V3_K1_L4`

### Piyasa Özeti

- Rejim metni: Kırılım öncesi sıkışma · Üst tepeler · savunmacı
- Spread: 0.13815335%
- RSI 5m/1h: 67.39778355 / 59.41359747
- BTC risk skoru: 70
- Vol persentil: 33.21643287
- Crash hızı: -0.23030861

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %24.19 · USDT %75.81

### Güvenlik

- Max exposure: %None
- Worst exposure: %None
- Aktif alış bütçesi: None USDT
- Fee bad: False
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 52/100. Rejim Kırılım öncesi sıkışma / kırılım hazırlığı. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil, likidite düşük, engeller: likidite çok düşük. Bu koşulda yeni alış veya satış yönetimi önerilmedi.
```

## SFPUSDT — 1000.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: SFPUSDT
- Kategori: Low liquidity / risky alt
- Girilen bütçe: 1000.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: no_trade
- Deployable: hayır
- Final action: NO_TRADE
- Güven: 39/100
- Parametre skoru: 52/100
- Route: `A6|R5|D1|S4|V3|K1|L4`
- Shelf: `DPLV5_A6_R5_D1_S4_V3_K1_L4`

### Piyasa Özeti

- Rejim metni: Kırılım öncesi sıkışma · Üst tepeler · savunmacı
- Spread: 0.13815335%
- RSI 5m/1h: 67.39778355 / 59.41359747
- BTC risk skoru: 70
- Vol persentil: 33.21643287
- Crash hızı: -0.23030861

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %24.19 · USDT %75.81

### Güvenlik

- Max exposure: %None
- Worst exposure: %None
- Aktif alış bütçesi: None USDT
- Fee bad: False
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 52/100. Rejim Kırılım öncesi sıkışma / kırılım hazırlığı. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil, likidite düşük, engeller: likidite çok düşük. Bu koşulda yeni alış veya satış yönetimi önerilmedi.
```

## RAREUSDT — 50.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: RAREUSDT
- Kategori: Low liquidity / risky alt
- Girilen bütçe: 50.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: no_trade
- Deployable: hayır
- Final action: NO_TRADE
- Güven: 35/100
- Parametre skoru: 37/100
- Route: `A6|R3|D1|S1|V3|K1|L4`
- Shelf: `DPLV5_A6_R3_D1_S1_V3_K1_L4`

### Piyasa Özeti

- Rejim metni: Düşük volatilite sıkışma · Aralık orta bölge · savunmacı
- Spread: 0.81632653%
- RSI 5m/1h: 59.1065319 / 49.44854684
- BTC risk skoru: 70
- Vol persentil: 0.85170341
- Crash hızı: 0.0

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %21.17 · USDT %78.83

### Güvenlik

- Max exposure: %None
- Worst exposure: %None
- Aktif alış bütçesi: None USDT
- Fee bad: False
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 37/100. Rejim Düşük volatilite sıkışma. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil, spread/fee verimliliği zayıf, likidite düşük, engeller: likidite çok düşük. Bu koşulda yeni alış veya satış yönetimi önerilmedi.
```

## RAREUSDT — 100.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: RAREUSDT
- Kategori: Low liquidity / risky alt
- Girilen bütçe: 100.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: no_trade
- Deployable: hayır
- Final action: NO_TRADE
- Güven: 35/100
- Parametre skoru: 37/100
- Route: `A6|R3|D1|S1|V3|K1|L4`
- Shelf: `DPLV5_A6_R3_D1_S1_V3_K1_L4`

### Piyasa Özeti

- Rejim metni: Düşük volatilite sıkışma · Aralık orta bölge · savunmacı
- Spread: 0.81632653%
- RSI 5m/1h: 59.1065319 / 49.44854684
- BTC risk skoru: 70
- Vol persentil: 0.85170341
- Crash hızı: 0.0

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %21.17 · USDT %78.83

### Güvenlik

- Max exposure: %None
- Worst exposure: %None
- Aktif alış bütçesi: None USDT
- Fee bad: False
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 37/100. Rejim Düşük volatilite sıkışma. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil, spread/fee verimliliği zayıf, likidite düşük, engeller: likidite çok düşük. Bu koşulda yeni alış veya satış yönetimi önerilmedi.
```

## RAREUSDT — 1000.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: RAREUSDT
- Kategori: Low liquidity / risky alt
- Girilen bütçe: 1000.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: no_trade
- Deployable: hayır
- Final action: NO_TRADE
- Güven: 35/100
- Parametre skoru: 37/100
- Route: `A6|R3|D1|S1|V3|K1|L4`
- Shelf: `DPLV5_A6_R3_D1_S1_V3_K1_L4`

### Piyasa Özeti

- Rejim metni: Düşük volatilite sıkışma · Aralık orta bölge · savunmacı
- Spread: 0.81632653%
- RSI 5m/1h: 59.1065319 / 49.44854684
- BTC risk skoru: 70
- Vol persentil: 0.85170341
- Crash hızı: 0.0

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %21.17 · USDT %78.83

### Güvenlik

- Max exposure: %None
- Worst exposure: %None
- Aktif alış bütçesi: None USDT
- Fee bad: False
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 37/100. Rejim Düşük volatilite sıkışma. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil, spread/fee verimliliği zayıf, likidite düşük, engeller: likidite çok düşük. Bu koşulda yeni alış veya satış yönetimi önerilmedi.
```

## PONDUSDT — 50.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: PONDUSDT
- Kategori: Low liquidity / risky alt
- Girilen bütçe: 50.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: no_trade
- Deployable: hayır
- Final action: NO_TRADE
- Güven: 42/100
- Parametre skoru: 49/100
- Route: `A4|R4|D3|S1|V5|K1|L4`
- Shelf: `DPLV5_A4_R4_D3_S1_V5_K1_L4`

### Piyasa Özeti

- Rejim metni: Volatil aralık · Aralık orta bölge · savunmacı
- Spread: 0.90497738%
- RSI 5m/1h: 45.45440783 / 40.08695175
- BTC risk skoru: 70
- Vol persentil: 65.28056112
- Crash hızı: -1.78571429

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %20.98 · USDT %79.02

### Güvenlik

- Max exposure: %None
- Worst exposure: %None
- Aktif alış bütçesi: None USDT
- Fee bad: False
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 49/100. Rejim Volatil aralık. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil, spread/fee verimliliği zayıf, likidite düşük, engeller: spread çok yüksek. Bu koşulda yeni alış veya satış yönetimi önerilmedi.
```

## PONDUSDT — 100.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: PONDUSDT
- Kategori: Low liquidity / risky alt
- Girilen bütçe: 100.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: no_trade
- Deployable: hayır
- Final action: NO_TRADE
- Güven: 42/100
- Parametre skoru: 49/100
- Route: `A4|R4|D3|S1|V5|K1|L4`
- Shelf: `DPLV5_A4_R4_D3_S1_V5_K1_L4`

### Piyasa Özeti

- Rejim metni: Volatil aralık · Aralık orta bölge · savunmacı
- Spread: 0.90497738%
- RSI 5m/1h: 45.45440783 / 40.08695175
- BTC risk skoru: 70
- Vol persentil: 65.28056112
- Crash hızı: -1.78571429

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %20.98 · USDT %79.02

### Güvenlik

- Max exposure: %None
- Worst exposure: %None
- Aktif alış bütçesi: None USDT
- Fee bad: False
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 49/100. Rejim Volatil aralık. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil, spread/fee verimliliği zayıf, likidite düşük, engeller: spread çok yüksek. Bu koşulda yeni alış veya satış yönetimi önerilmedi.
```

## PONDUSDT — 1000.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: PONDUSDT
- Kategori: Low liquidity / risky alt
- Girilen bütçe: 1000.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: no_trade
- Deployable: hayır
- Final action: NO_TRADE
- Güven: 42/100
- Parametre skoru: 49/100
- Route: `A4|R4|D3|S1|V5|K1|L4`
- Shelf: `DPLV5_A4_R4_D3_S1_V5_K1_L4`

### Piyasa Özeti

- Rejim metni: Volatil aralık · Aralık orta bölge · savunmacı
- Spread: 0.90497738%
- RSI 5m/1h: 45.45440783 / 40.08695175
- BTC risk skoru: 70
- Vol persentil: 65.28056112
- Crash hızı: -1.78571429

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %20.98 · USDT %79.02

### Güvenlik

- Max exposure: %None
- Worst exposure: %None
- Aktif alış bütçesi: None USDT
- Fee bad: False
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 49/100. Rejim Volatil aralık. Risk durumu savunmacı. Fee efficiency 15/100 olduğu için dar grid verimli değil, spread/fee verimliliği zayıf, likidite düşük, engeller: spread çok yüksek. Bu koşulda yeni alış veya satış yönetimi önerilmedi.
```

## AGLDUSDT — 50.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: AGLDUSDT
- Kategori: Game/metaverse
- Girilen bütçe: 50.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: min_notional_limited_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 40/100
- Parametre skoru: 66/100
- Route: `A3|R1|D1|S4|V5|K1|L2`
- Shelf: `DPLV5_A3_R1_D1_S4_V5_K1_L2`

### Piyasa Özeti

- Rejim metni: Güçlü yükseliş trendi · Üst tepeler · savunmacı
- Spread: 0.12989825%
- RSI 5m/1h: 62.30093006 / 62.78509352
- BTC risk skoru: 70
- Vol persentil: 92.83567134
- Crash hızı: -2.56410256

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %40.44 · USDT %59.56

### Güvenlik

- Max exposure: %40.44
- Worst exposure: %100.0
- Aktif alış bütçesi: 20.22 USDT
- Fee bad: False
- Güvenlik sonucu: Referans / bekle · Maruziyet sınırı aşılıyor

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 66/100. Rejim Güçlü yükseliş trendi. Risk durumu savunmacı. Engeller: min notional hard fail, no sellable base. Bu yüzden sistem beklemeyi seçti.
```

## AGLDUSDT — 100.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: AGLDUSDT
- Kategori: Game/metaverse
- Girilen bütçe: 100.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: first_start_buy_only
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 60/100
- Parametre skoru: 66/100
- Route: `A3|R1|D1|S4|V5|K1|L2`
- Shelf: `DPLV5_A3_R1_D1_S4_V5_K1_L2`

### Piyasa Özeti

- Rejim metni: Güçlü yükseliş trendi · Üst tepeler · savunmacı
- Spread: 0.12995452%
- RSI 5m/1h: 62.30093006 / 62.78509352
- BTC risk skoru: 70
- Vol persentil: 92.83567134
- Crash hızı: -2.56410256

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %40.44 · USDT %59.56

### Güvenlik

- Max exposure: %40.44
- Worst exposure: %40.44
- Aktif alış bütçesi: 40.44 USDT
- Fee bad: False
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 66/100. Rejim Güçlü yükseliş trendi. Risk durumu savunmacı. Engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## AGLDUSDT — 1000.0 USDT

### Kullanıcı Akışı

- Sayfa: Parametre Asistanı
- Girilen sembol: AGLDUSDT
- Kategori: Game/metaverse
- Girilen bütçe: 1000.0 USDT
- Analiz durumu: Tamamlandı

### Final Karar

- Result type: recommended_grid
- Deployable: hayır
- Final action: WAIT_SAFETY
- Güven: 62/100
- Parametre skoru: 68/100
- Route: `A3|R1|D1|S4|V5|K1|L2`
- Shelf: `DPLV5_A3_R1_D1_S4_V5_K1_L2`

### Piyasa Özeti

- Rejim metni: Güçlü yükseliş trendi · Üst tepeler · savunmacı
- Spread: 0.04344992%
- RSI 5m/1h: 62.30093006 / 62.78509352
- BTC risk skoru: 70
- Vol persentil: 92.83567134
- Crash hızı: -2.56410256

### Grid Özeti

- Alış: 2 kademe · dağılım []
- Satış: 2 kademe · dağılım []
- Hedef: coin %40.44 · USDT %59.56

### Güvenlik

- Max exposure: %40.44
- Worst exposure: %40.44
- Aktif alış bütçesi: 404.4 USDT
- Fee bad: False
- Güvenlik sonucu: Referans / bekle

### Tespit Edilen Mantık Hataları

| Seviye | Kod | Açıklama | Beklenen |
|--------|-----|----------|----------|
| — | — | anomaly yok | — |

### Ham cevap özeti

```
Parametre Skoru 68/100. Rejim Güçlü yükseliş trendi. Risk durumu savunmacı. Engeller: no sellable base, exposure hard cap breach. Bu yüzden sistem beklemeyi seçti.
```

## Sonuç

Bu testte 150 kullanıcı akışı çalıştırıldı. Blocker ve kritik anomaly yok. V5 karar mantığı ve veri tamlığı hedefleri karşılandı.
