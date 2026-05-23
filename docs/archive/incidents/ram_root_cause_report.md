# RAM ROOT CAUSE REPORT

**Oluşturulma:** Ölçüm tamamlandıktan sonra bu dosya doldurulacak. Tahmin yok, sadece kanıt.

---

## 1. Toplam RAM kullanımı zaman çizelgesi

| Zaman (ts) | RSS (MB) | Heap (MB) | Label |
|------------|----------|-----------|-------|
| _(logs/ram_snapshots.log satırlarından doldur)_ | | | |

_Grafik: RSS ve heap_mb zamanla çiz. (Excel/gnuplot veya logs/ram_snapshots.log parse.)_

---

## 2. En çok RAM tüketen modüller (sıralı)

| Sıra | Dosya:satır | size_mb | Açıklama |
|-----|-------------|---------|----------|
| 1 | | | _(top_allocations ve top_types sonuçlarından)_ |
| 2 | | | |
| ... | | | |

---

## 3. Leak var mı? (EVET / HAYIR)

- **Cevap:** _EVET_ / _HAYIR_
- **Kanıt:** _(gc.collect() sonrası obje sayısı düşüyor mu? Stop sonrası asyncio.Task sayısı azalıyor mu?)_

---

## 4. Eğer leak varsa

- **Obje tipi:** _(hangi tip tutuluyor)_
- **Referans zinciri:** _(objgraph backref chain veya tracemalloc)_
- **Neden GC temizleyemiyor:** _(cyclic ref, global ref, task ref)_
- **Dosya:satır:** _(kök neden konumu)_

---

## 5. Bot başına RAM maliyeti

| Bot sayısı | RSS (MB) | RSS artışı (MB/bot) |
|------------|----------|---------------------|
| 0 | | — |
| 1 | | |
| 10 | | |
| _(ram_snapshots.log + probe_bot_event start/stop)_ | | |

---

## 6. Bu şekilde devam ederse X saat/gün sonra OOM olur mu?

- **Mevcut RSS:** _ MB
- **Büyüme hızı:** _ MB/saat (veya MB/gün)
- **Hesaplanan süre (OOM’a):** _ saat/gün _(veya “sabit / düşüyor, OOM riski yok”)_

---

## 7. NET KÖK NEDEN (tek cümle)

_(Ölçüm ve loglarla desteklenmiş tek cümle. Örn: “DataHub.prices 2000+ sembol tutuyordu; cap 600’e düşürüldü.” veya “Bot stop sonrası asyncio.Task iptal edilmiyor; task leak.”)_

---

## Stres senaryoları özeti

| Senaryo | Açıklama | RAM başlangıç | RAM son | Sonuç |
|---------|----------|---------------|---------|-------|
| A — Idle | 0 bot, 10 dk | | | |
| B — 1 Bot | 1 bot, 30 dk | | | |
| C — 10 Bot | 10 bot 30 dk, sonra stop | | | |
| D — Web Down | Worker açık, web kapalı | | | |

_(Senaryoları sırayla çalıştır; logs/ram_snapshots.log ve probe etiketleriyle doldur.)_
