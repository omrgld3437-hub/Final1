#!/usr/bin/env python3
"""
Her proje klasörüne README.md yazar — içerik, işlev, dosya listesi.
Usage: python3 scripts/devops/generate_folder_readmes.py
"""

from __future__ import annotations
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKIP = {
    ".git",
    ".venv",
    "__pycache__",
    "_meta",
    ".pytest_cache",
    "node_modules",
    ".cursor",
    ".run",
    "logs",
    ".well-known",
}
SKIP_PREFIX = ("ui/assets/coins/", "ui/assets/binance2/", "marketing/.git")

DOCS: dict[str, dict[str, str]] = {
    ".": {
        "title": "final1 — Proje kökü",
        "purpose": (
            "ayserose platformunun ana dizini. Binance Spot üzerinde DCA, grid ve trailing "
            "botları çalıştıran FastAPI backend, web paneli, manager paneli ve Bot Engine worker "
            "buradan başlatılır."
        ),
        "role": (
            "Dışarıdan bakan biri için: bu klasör **uygulamanın kendisi**. Alt klasörler kod, arayüz, "
            "operasyon scriptleri ve dokümantasyonu içerir. Çalıştırma: `./start.command` veya `make start`."
        ),
        "key_files": (
            "`README.md` giriş · `TRADE_TRAILING_MASTER_SPEC.md` tek kaynak spec · "
            "`requirements.txt` Python bağımlılıkları · `.env` yerel yapılandırma (gitignore) · "
            "`Makefile` kısa komutlar · `start.command` / `stop.command` servis başlat/durdur"
        ),
        "related": "docs/STRUCTURE.md · docs/INDEX.md",
    },
    "app": {
        "title": "app — Backend (Python paketi)",
        "purpose": (
            "Tüm sunucu tarafı mantık burada. FastAPI uygulaması (`main.py`), REST/WebSocket API, "
            "veritabanı modelleri, Binance entegrasyonu ve Bot Engine paketi `app` adıyla import edilir."
        ),
        "role": (
            "Web süreci: `uvicorn app.main:app`. Worker süreci: `python -m app.botengine.worker_main`. "
            "Bu paket adı değiştirilmez — deploy ve import yolları buna bağlıdır."
        ),
        "key_files": "`main.py` FastAPI giriş · `boot_id.py` sunucu örneği kimliği · `server_state.py` runtime bayrakları",
        "related": "app/_meta/MODULE.md · TRADE_TRAILING_MASTER_SPEC.md",
    },
    "app/api": {
        "title": "app/api — HTTP ve WebSocket API",
        "purpose": "Tarayıcı ve dış istemcilerin konuştuğu REST endpoint'leri ve WS kanalları.",
        "role": (
            "Dashboard verisi (`routes.py`), bot start/stop (`bots_engine.py`), kimlik doğrulama (`auth.py`), "
            "admin, finans, spot, fiyat ve piyasa verisi route'ları. Alt router'lar `routes/` altında."
        ),
        "key_files": "bots_engine.py · auth.py · routes.py · admin.py · ws.py",
        "related": "app/api/_meta/MODULE.md · docs/api/",
    },
    "app/api/routes": {
        "title": "app/api/routes — Alt API router'ları",
        "purpose": "Ana `routes.py` modülünden ayrılmış, odaklı FastAPI router dosyaları.",
        "role": "Flash home (`home.py` — hızlı dashboard bootstrap), dashboard bootstrap endpoint'i.",
        "key_files": "home.py · dashboard_bootstrap.py",
        "related": "docs/api/home_fast_contract.md",
    },
    "app/api/utils": {
        "title": "app/api/utils — API yardımcıları",
        "purpose": "Route'lar arası paylaşılan küçük yardımcı modüller.",
        "role": "Alan normalizasyonu, ortak response alanları (`fields.py`).",
        "key_files": "fields.py",
        "related": "app/api/routes.py",
    },
    "app/botengine": {
        "title": "app/botengine — Bot Engine v5",
        "purpose": "Canlı bot motoru: emir gönderimi, strateji tick'leri, scheduler, reconcile, intent ledger.",
        "role": (
            "Worker ayrı proses olarak çalışır. UI bot START komutu → DB kuyruk → worker → execution → Binance. "
            "Legacy orchestrator da burada (v5 scheduler kapalıysa)."
        ),
        "key_files": "worker_main.py · bot_run.py · execution.py · scheduler.py · orchestrator.py",
        "related": "docs/engine/BOTENGINE_RUNBOOK.md · app/botengine/_meta/MODULE.md",
    },
    "app/botengine/adapters": {
        "title": "app/botengine/adapters — Borsa adaptörleri",
        "purpose": "Bot Engine ile borsa API'si arasındaki ince katman.",
        "role": "Binance spot emirleri, bakiye sorguları — strateji kodundan ayrı tutulur.",
        "key_files": "binance_adapter.py",
        "related": "app/services/binance_client.py",
    },
    "app/botengine/strategies": {
        "title": "app/botengine/strategies — Bot stratejileri",
        "purpose": "Her bot tipinin tick mantığı: DCA grid trailing, TRDCA, multi-asset rebalance vb.",
        "role": "Yeni strateji eklerken buraya modül + registry kaydı. Worker tick başına strateji `run()` çağrılır.",
        "key_files": "dca_grid_trailing.py · trdca_pro.py · registry.py · base.py",
        "related": "TRADE_TRAILING_MASTER_SPEC.md strateji bölümleri",
    },
    "app/services": {
        "title": "app/services — İş servisleri",
        "purpose": "Binance client, fiyat hub, PnL hesabı, DataHub, audit, şifreleme — API ve Engine'in ortak iş katmanı.",
        "role": "Route'lar ince kalır; ağır iş burada. Binance çağrıları, cache, snapshot birleştirme.",
        "key_files": "binance_client.py · pnl_service.py · data_hub.py · pricing.py · audit.py",
        "related": "app/services/_meta/MODULE.md",
    },
    "app/db": {
        "title": "app/db — Veritabanı katmanı",
        "purpose": "SQLAlchemy modelleri, oturum fabrikası, şema koruma (schema_guard).",
        "role": "Varsayılan SQLite: `~/.trader/dca.db`. Web ve worker aynı DB'yi kullanmalı (.env DATABASE_URL).",
        "key_files": "models.py · session.py · base.py · schema_guard.py",
        "related": "docs/runtime.md · scripts/migrations/",
    },
    "app/core": {
        "title": "app/core — Çekirdek yapılandırma",
        "purpose": "Uygulama config, sabitler, hata sınıfları, auth token yardımcıları, rate limit.",
        "role": "Ortam değişkenleri, limitler, güvenlik eşikleri — spec ile uyumlu tutulur.",
        "key_files": "config.py · constants.py · errors.py · anomaly_codes.py",
        "related": "TRADE_TRAILING_MASTER_SPEC.md System limits",
    },
    "app/core/auth": {
        "title": "app/core/auth — Auth yardımcıları",
        "purpose": "Token üretimi/doğrulama gibi auth alt modülleri.",
        "role": "Ana login akışı `app/api/auth.py` içinde; burada düşük seviye token utils.",
        "key_files": "token_utils.py",
        "related": "app/api/auth.py · docs/security_hardening.md",
    },
    "app/core/security": {
        "title": "app/core/security — Güvenlik",
        "purpose": "Rate limiting ve güvenlik yardımcıları.",
        "role": "Brute-force ve istek hızı sınırları.",
        "key_files": "rate_limiter.py",
        "related": "docs/security_hardening.md",
    },
    "app/middleware": {
        "title": "app/middleware — HTTP middleware",
        "purpose": "FastAPI middleware zinciri: CSRF, güvenlik başlıkları, istek metrikleri.",
        "role": "Her HTTP isteğinden önce/sonra çalışır; main.py'de kayıtlıdır.",
        "key_files": "csrf.py · security_headers.py · request_metrics.py",
        "related": "app/main.py",
    },
    "app/observability": {
        "title": "app/observability — Gözlemlenebilirlik",
        "purpose": "RAM probe, metrik stub'ları — prod debug ve kapasite izleme.",
        "role": "RAM_PROBE=1 ile snapshot loglama; manager panelinde izlenebilir.",
        "key_files": "ram_probe.py · metrics_stubs.py",
        "related": "scripts/perf/ram_analyze.py",
    },
    "app/bot": {
        "title": "app/bot — Legacy bot motoru",
        "purpose": "Eski DCA/trailing worker sürümü (v3/v2).",
        "role": "**Yeni kod eklenmez.** Canlı motor `app/botengine/`. Geriye dönük referans ve nadir legacy yollar.",
        "key_files": "dca_engine_v3.py · dca_worker_v3.py · engine_v2.py",
        "related": "app/botengine/",
    },
    "app/utils": {
        "title": "app/utils — Genel yardımcılar",
        "purpose": "Küçük, paket geneli utility fonksiyonları.",
        "role": "Hesap kodu normalizasyonu, timezone yardımcıları.",
        "key_files": "account_code.py · tz_utils.py",
        "related": "app/core/",
    },
    "ui": {
        "title": "ui — Web paneli (statik)",
        "purpose": "Kullanıcı arayüzü: dashboard, bot detay, admin, login, grafik sayfaları.",
        "role": "FastAPI `/ui` altında mount edilir. Vanilla JS; build adımı yok. Ana mantık `assets/dashboard.js`.",
        "key_files": "dashboard.html · bot.html · login.html · assets/dashboard.js",
        "related": "ui/_meta/MODULE.md",
    },
    "ui/assets": {
        "title": "ui/assets — Panel JavaScript ve CSS",
        "purpose": "Tüm etkileşimli frontend kodu, store'lar, API client, coin görselleri.",
        "role": "Sayfa HTML'leri ince; iş mantığı burada. `core/` API client, `stores/` state, `services/` domain.",
        "key_files": "dashboard.js · api.js · appBoot.js · core/ · stores/",
        "related": "ui/_meta/MODULE.md",
    },
    "ui/assets/core": {
        "title": "ui/assets/core — Frontend çekirdek",
        "purpose": "API client, interval registry, paylaşılan boot yardımcıları.",
        "role": "Tüm sayfaların ortak altyapısı; fetch sarmalayıcıları ve timer yönetimi.",
        "key_files": "apiClient.js · intervalRegistry.js",
        "related": "ui/assets/api.js",
    },
    "ui/assets/stores": {
        "title": "ui/assets/stores — İstemci state",
        "purpose": "Dashboard ve finans ekranı için hafif state store'ları.",
        "role": "Sunucu snapshot + UI state birleşimi; sayfa yenilemeden güncelleme.",
        "key_files": "dashboardStore.js · financeStore.js",
        "related": "ui/assets/dashboard.js",
    },
    "ui/assets/services": {
        "title": "ui/assets/services — Frontend servis katmanı",
        "purpose": "Piyasa verisi, finans API çağrılarını gruplayan modüller.",
        "role": "HTML/JS ile backend arasında domain odaklı fonksiyonlar.",
        "key_files": "marketData.js · finance.js (varsa)",
        "related": "app/api/routes.py",
    },
    "ui/assets/utils": {
        "title": "ui/assets/utils — UI yardımcıları",
        "purpose": "Formatlama, DOM, küçük paylaşılan JS fonksiyonları.",
        "role": "Tekrarlayan UI işlerini merkezileştirir.",
        "key_files": "(modül dosyaları)",
        "related": "ui/assets/dashboard.js",
    },
    "ui/assets/js": {
        "title": "ui/assets/js — Ek script dosyaları",
        "purpose": "Ana bundle dışında kalan küçük script'ler (ör. bakım overlay).",
        "role": "Eski `/ui/js/` yolu geriye uyumluluk için `main.py`'de buraya yönlendirilir.",
        "key_files": "maintenanceOverlay.js",
        "related": "app/main.py static mount",
    },
    "ui/vendor": {
        "title": "ui/vendor — Üçüncü parti kütüphaneler",
        "purpose": "Grafik ve UI kütüphaneleri (Lightweight Charts vb.).",
        "role": "CDN yerine yerel kopya; chart sayfaları buradan yükler.",
        "key_files": "lightweight-charts*.js (eklenmeli)",
        "related": "ui/chart.html",
    },
    "manager_server": {
        "title": "manager_server — Ops paneli (:7999)",
        "purpose": "Sunucu operasyon paneli: process start/stop, log tail, metrik, servis durumu.",
        "role": "Ayrı FastAPI uygulaması. Web/worker/helper script'leri buradan tetiklenebilir. Sadece localhost.",
        "key_files": "app.py · state.py · reason_engine.py · ui/",
        "related": "manager_server/_meta/MODULE.md · docs/runtime.md",
    },
    "manager_server/ui": {
        "title": "manager_server/ui — Manager arayüzü",
        "purpose": "Manager panel HTML ve statik JS/CSS.",
        "role": "http://127.0.0.1:7999/ui — operatör ekranı.",
        "key_files": "index.html · assets/manager.js · assets/manager.css",
        "related": "manager_server/app.py",
    },
    "ops": {
        "title": "ops — Çalıştırma scriptleri",
        "purpose": "Manager, Web, Worker ve marketing sitesini başlatma/durdurma/deploy.",
        "role": "Kökteki `start.command` / `stop.command` doğrudan çalıştırılabilir; `ops/` altında aynı mantığın kopyaları da vardır.",
        "key_files": "start.command · stop.command · deploy.sh · run.sh · *.bat",
        "related": "docs/runtime.md · Makefile",
    },
    "scripts": {
        "title": "scripts — Araçlar ve yardımcı scriptler",
        "purpose": "Migration, audit, performans testi, meta dokümantasyon üretimi, runtime helper'lar.",
        "role": "Uygulama çalışması için zorunlu değil; operasyon ve geliştirme aracı. Alt klasörlere ayrılmıştır.",
        "key_files": "README.md · runtime/ · devops/ · audit/ · migrations/",
        "related": "scripts/_meta/MODULE.md",
    },
    "scripts/runtime": {
        "title": "scripts/runtime — Süreç yaşam döngüsü",
        "purpose": "Web/worker başlat-durdur, restart helper, Windows launcher.",
        "role": "Manager `local_web_worker_helper.py` ve admin restart bu script'leri kullanır.",
        "key_files": "run.sh · local_web_worker_helper.py · restart_server.py · win_launcher.py",
        "related": "ops/run.sh · manager_server/state.py",
    },
    "scripts/devops": {
        "title": "scripts/devops — Dokümantasyon ve env araçları",
        "purpose": "Klasör README üretimi, modül envanter sync, dosya başlık annotasyonu, master key kurulumu.",
        "role": "`make meta` bu klasördeki script'leri çalıştırır.",
        "key_files": "sync_module_meta.py · sync_ana_basliklar.py · generate_folder_readmes.py · annotate_file_headers.py",
        "related": "docs/ANA_BASLIKLAR.md",
    },
    "scripts/audit": {
        "title": "scripts/audit — Denetim ve reconcile",
        "purpose": "Intent ledger audit, Binance reconcile, auth doğrulama script'leri.",
        "role": "Prod olay analizi ve 'DB ile borsa uyumlu mu?' kontrolleri.",
        "key_files": "intent_audit.py · reconcile_now.py · binance_verify_order.py",
        "related": "docs/engine/BOTENGINE_RUNBOOK.md",
    },
    "scripts/perf": {
        "title": "scripts/perf — Performans ve RAM testleri",
        "purpose": "Snapshot perf simülasyonu, RAM stress, bot yük simülasyonu.",
        "role": "Kapasite planlama ve regresyon ölçümü; prod'da dikkatli çalıştırın.",
        "key_files": "perf_snapshot_test.py · ram_analyze.py · perf_300_bots_sim.py",
        "related": "app/observability/",
    },
    "scripts/maintenance": {
        "title": "scripts/maintenance — Bakım scriptleri",
        "purpose": "Coin logo indirme, CRLF düzeltme, CGI/manager tek seferlik fix'ler.",
        "role": "Nadiren ihtiyaç duyulan operasyon görevleri.",
        "key_files": "fetch_binance_coin_logos.py · fix_bat_crlf.ps1",
        "related": "ui/assets/coins/",
    },
    "scripts/migrations": {
        "title": "scripts/migrations — Veritabanı migration",
        "purpose": "Tablo oluşturma, admin kullanıcı, tek seferlik şema güncellemeleri.",
        "role": "İlk kurulum: `init_db.py`, `create_first_admin.py`. Canlı DB'de dikkatli kullanın.",
        "key_files": "init_db.py · create_first_admin.py · set_admin_password_once.py",
        "related": "app/db/schema_guard.py",
    },
    "deploy": {
        "title": "deploy — Sunucu kurulum",
        "purpose": "Production deploy: rsync, nginx config, sabit/değişken dosya listeleri.",
        "role": "Geliştirme makinesinden sunucuya kod aktarımı; systemd/nginx örnekleri.",
        "key_files": "DEPLOY.md · deploy.sh · nginx-tradertrailing-server.conf",
        "related": "ops/deploy.sh · docs/runtime.md",
    },
    "tests": {
        "title": "tests — Otomatik testler (pytest)",
        "purpose": "Auth, lock TTL, intent idempotency, reconcile, PnL, snapshot sözleşmeleri.",
        "role": "Regresyon güvencesi. Çalıştırma: `make test` veya `pytest tests/`.",
        "key_files": "test_locks_ttl.py · test_intent_idempotency.py · test_home_fast_no_binance.py",
        "related": "tests/_meta/MODULE.md",
    },
    "docs": {
        "title": "docs — Dokümantasyon",
        "purpose": "Runbook, yapı rehberi, API sözleşmeleri, engine dokümanları, arşiv.",
        "role": "Spec dışı operasyonel bilgi. Yeni geliştirici buradan başlamalı: STRUCTURE.md → INDEX.md.",
        "key_files": "STRUCTURE.md · INDEX.md · runtime.md · security_hardening.md",
        "related": "TRADE_TRAILING_MASTER_SPEC.md (kök)",
    },
    "docs/api": {
        "title": "docs/api — API sözleşmeleri",
        "purpose": "Home fast, snapshot gibi endpoint payload sözleşmeleri.",
        "role": "Frontend ve backend uyumu için referans; breaking change'de güncellenir.",
        "key_files": "home_fast_contract.md · snapshot_contract.md",
        "related": "app/api/routes/home.py",
    },
    "docs/engine": {
        "title": "docs/engine — Bot Engine dokümantasyonu",
        "purpose": "Engine runbook, durum modeli, operasyon prosedürleri.",
        "role": "Bot tick, intent, reconcile sorunlarında ilk bakılacak yer.",
        "key_files": "BOTENGINE_RUNBOOK.md · BOTENGINE_STATE_MODEL.md",
        "related": "app/botengine/",
    },
    "docs/archive": {
        "title": "docs/archive — Arşiv",
        "purpose": "Eski incident raporları, perf patch notları, birleştirilmiş/kaldırılmış dokümanlar.",
        "role": "Aktif runbook değil; tarihsel referans. Yeni bilgi aktif docs'a yazılır.",
        "key_files": "incidents/ · sanity-patches/ · misc/",
        "related": "docs/INDEX.md",
    },
    "docs/archive/incidents": {
        "title": "docs/archive/incidents — Olay raporları",
        "purpose": "Geçmiş production olayları, kök neden analizleri, forensic raporlar.",
        "role": "Benzer bir sorun yaşandığında arşiv aranır; aktif runbook yerine geçmez.",
        "key_files": "INCIDENT_ROOTCAUSE_REPORT.md · LIVE_TRADING_EXECUTION_FORENSIC_ANALYSIS_v1.md · …",
        "related": "docs/engine/BOTENGINE_RUNBOOK.md",
    },
    "docs/archive/misc": {
        "title": "docs/archive/misc — Birleştirilmiş eski dokümanlar",
        "purpose": "README_WINDOWS, perf raporları, CHANGELOG gibi aktif docs'a taşınmış/kaldırılmış dosyalar.",
        "role": "Referans için saklanır; güncel bilgi için docs/runtime.md ve README kullanın.",
        "key_files": "README.md (indeks) · GÜNCEL_README.md · perf_hardening_*.md",
        "related": "docs/archive/misc/README.md",
    },
    "docs/archive/sanity-patches": {
        "title": "docs/archive/sanity-patches — Patch notları",
        "purpose": "Geçmiş sanity patch A–H uygulama notları (lock TTL, worker-only, snapshot perf vb.).",
        "role": "Tarihsel; güncel davranış TRADE_TRAILING_MASTER_SPEC.md ve kodda.",
        "key_files": "patch_A_lock_ttl.md · patch_B_worker_only_trading.md · …",
        "related": "TRADE_TRAILING_MASTER_SPEC.md",
    },
    "ui/assets/coins": {
        "title": "ui/assets/coins — Coin logoları",
        "purpose": "USDT parite coin'lerinin PNG logo dosyaları (dashboard listelerinde).",
        "role": "Statik asset; `scripts/maintenance/fetch_binance_coin_logos.py` ile güncellenir.",
        "key_files": "BTCUSDT.png · ETHUSDT.png · … (yüzlerce PNG)",
        "related": "app/main.py serve_coin_logo",
    },
    "ui/assets/binance2": {
        "title": "ui/assets/binance2 — Binance UI asset'leri",
        "purpose": "Panelde kullanılan ek Binance görsel/stil dosyaları.",
        "role": "Statik frontend asset klasörü.",
        "key_files": "(görsel dosyalar)",
        "related": "ui/assets/",
    },
    "manager_server/ui/assets": {
        "title": "manager_server/ui/assets — Manager JS/CSS",
        "purpose": "Operasyon panelinin JavaScript ve stil dosyaları.",
        "role": "Manager HTML ile birlikte sunulur.",
        "key_files": "manager.js · manager.css",
        "related": "manager_server/ui/index.html",
    },
    "marketing": {
        "title": "marketing — Tanıtım sitesi (opsiyonel)",
        "purpose": "omeraltin.com statik içeriği; port 8080.",
        "role": "Trading uygulamasından bağımsız. `start.command` ile birlikte açılabilir.",
        "key_files": "index.html · start.py · style.css · script.js",
        "related": "ops/start.command",
    },
    "shared": {
        "title": "shared — Legacy opsiyonel dizin",
        "purpose": "Eski Windows kurulumlarında .env junction veya paylaşımlı log için kullanılmış olabilir.",
        "role": "Yeni kurulumda gerekmez; proje kökündeki `.env` ve `logs/` yeterlidir.",
        "key_files": "data/ · logs/ (.gitkeep)",
        "related": "docs/runtime.md",
    },
}


def _list_files(rel: str) -> list[str]:
    base = ROOT / rel if rel != "." else ROOT
    if not base.is_dir():
        return []
    out: list[str] = []
    try:
        for p in sorted(base.iterdir()):
            if p.name.startswith(".") and p.name not in (".env.example",):
                continue
            if p.name in SKIP or p.name == "README.md":
                continue
            if p.is_file():
                out.append(p.name)
            elif p.is_dir() and p.name not in SKIP:
                out.append(f"{p.name}/")
    except OSError:
        pass
    return out[:40]


def _render(rel: str, meta: dict[str, str]) -> str:
    files = _list_files(rel)
    rel_path = "proje kökü" if rel == "." else f"`{rel}/`"
    lines = [
        f"# {meta['title']}",
        "",
        f"**Konum:** {rel_path}  ",
        f"**Güncelleme:** {date.today().isoformat()} (otomatik: `python3 scripts/devops/generate_folder_readmes.py`)",
        "",
        "## Ne işe yarar?",
        "",
        meta["purpose"],
        "",
        "## Bu klasörde ne bulursunuz?",
        "",
        meta["role"],
        "",
        "## Önemli dosyalar",
        "",
        meta["key_files"],
        "",
        "## İçerik özeti",
        "",
    ]
    if files:
        lines.append("```")
        lines.extend(files)
        if len(files) >= 40:
            lines.append("... (daha fazla dosya olabilir)")
        lines.append("```")
    else:
        lines.append("_Boş veya yalnızca alt klasörler._")
    lines.extend(
        [
            "",
            "## İlgili dokümanlar",
            "",
            meta.get("related", "docs/INDEX.md"),
            "",
            "---",
            "",
            "Üst rehber: [docs/STRUCTURE.md](../docs/STRUCTURE.md)"
            if rel != "." and not rel.startswith("docs/")
            else "Üst rehber: [docs/STRUCTURE.md](STRUCTURE.md)"
            if rel.startswith("docs/")
            else "Üst rehber: [docs/STRUCTURE.md](docs/STRUCTURE.md)",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    count = 0
    for rel, meta in DOCS.items():
        out = ROOT / rel / "README.md" if rel != "." else ROOT / "README.md"
        # Kök README.md elle zengin tutuluyor; sadece alt klasörler ve ops/shared/marketing
        if rel == ".":
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(_render(rel, meta), encoding="utf-8")
        count += 1
        print(f"ok  {out.relative_to(ROOT)}")
    print(f"wrote {count} README.md files")


if __name__ == "__main__":
    main()
