/**
 * Manager hata/uyarı panelleri — teknik log satırlarını anlaşılır Türkçe özetlere çevirir.
 * Ham kayıt bilgisi korunur; sebep, etki ve öneri eksiksiz yazılır.
 */
(function (global) {
  'use strict';

  var SERVICE_LABELS = {
    web: 'TraderTrailing Web (FastAPI)',
    engine: 'Bot Engine (botengine)',
    manager: 'Yönetici Paneli (manager)',
    html: 'Statik HTML sunucusu'
  };

  var MODULE_LABELS = {
    'app.botengine.execution': 'Bot emir yürütme',
    'app.botengine.worker_main': 'Bot engine worker',
    'app.botengine.orchestrator': 'Bot tick döngüsü',
    'app.services.binance_spot': 'Binance Spot API',
    'app.services.binance_ws': 'Binance canlı fiyat WebSocket',
    'root': 'Web uygulaması (main.py)',
    'app.services.finance_trade_sync': 'Finans işlem senkronu',
    'app.botengine.adapters.binance_adapter': 'Binance adapter',
    'app.botengine.health_watch': 'Bot sağlık izleme',
    'app.botengine.intent_ledger': 'Emir intent defteri',
    'app.api.spot_routes': 'Spot API (Al/Sat modal)',
    'app.api.routes.home': 'Anasayfa cüzdan API (home/fast, wallet/refresh)',
    'app.api.dashboard_stream': 'Dashboard SSE akışı (snapshot push)',
    'app.api._routes_impl': 'Web API (cüzdan, açık emir, snapshot)',
    'app.api.routes': 'Web API (cüzdan, açık emir, snapshot)',
    'app.api.bots_engine': 'Bot API (oluştur/sil/performans)',
    'app.services.spot_engine': 'Spot engine',
    'uvicorn.error': 'Web sunucusu',
    'uvicorn.access': 'Web erişim günlüğü'
  };

  var SKIP_REASON_TR = {
    ORDER_FAILED: 'Emir borsa veya ağ hatasıyla reddedildi',
    LOT_SIZE: 'Emir miktarı lot/step filtresine uymuyor',
    INSUFFICIENT_BALANCE: 'Hesap bakiyesi yetersiz (-2010)',
    ORDER_TIMEOUT: 'Emir gönderimi zaman aşımına uğradı',
    WEIGHT_DENIED: 'Binance istek ağırlık limiti (rate limit)',
    LOCK_LEASE_EXPIRED: 'Sembol kilidi süresi doldu',
    BINANCE_FREE_BASE_INSUFFICIENT: 'Binance serbest coin bakiyesi yetersiz',
    BINANCE_FREE_QUOTE_INSUFFICIENT: 'Binance serbest USDT bakiyesi yetersiz',
    MIN_NOTIONAL: 'Emir tutarı minimum notional altında',
    MIN_NOTIONAL_AFTER_CAP: 'Miktar kısıtlandıktan sonra minimum tutar altında kaldı',
    API_UNAUTHORIZED: 'Binance API yetkilendirme hatası (401)'
  };

  var LEVEL_LABELS = {
    WARNING: 'Uyarı',
    WARN: 'Uyarı',
    ERROR: 'Hata',
    CRITICAL: 'Kritik hata',
    INFO: 'Bilgi',
    DEBUG: 'Debug'
  };

  var RE_PY_LOG = /^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s*-\s*(\S+)\s*-\s*(WARNING|ERROR|CRITICAL|INFO|DEBUG)\s*-\s*(.+)$/i;
  var RE_BRACKET_LOG = /^\[(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\]\s*(WARNING|ERROR|CRITICAL|INFO|DEBUG)\s+(.+)$/i;
  var RE_MANAGER_LOG = /^\[(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\]\s*\[MANAGER\]\s*\[(WARNING|ERROR|CRITICAL|INFO|DEBUG)\]\s*(.+)$/i;
  var RE_HTTP_ACCESS = /\b(GET|POST|PUT|DELETE|PATCH)\s+(\S+)\s+(\d{3})\b/;

  function formatTsTr(ts) {
    if (!ts) return '—';
    var m = String(ts).match(/^(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2}):(\d{2})/);
    if (m) return m[3] + '.' + m[2] + '.' + m[1] + ' ' + m[4] + ':' + m[5] + ':' + m[6];
    return ts;
  }

  function levelTr(level) {
    if (!level) return '—';
    return LEVEL_LABELS[String(level).toUpperCase()] || level;
  }

  function extractParams(text) {
    var params = {};
    if (!text) return params;
    var re = /\b(bot_id|account_id|symbol|order_id|cycle_id|run_id|err_code|error_code|skip_reason|binance_code|reason)=([^\s,;]+)/gi;
    var m;
    while ((m = re.exec(text)) !== null) {
      params[m[1].toLowerCase()] = m[2];
    }
    var acctFor = text.match(/\bfor account\s+(\d+)/i);
    if (acctFor && !params.account_id) params.account_id = acctFor[1];
    var errLong = text.match(/\berr=(\[[^\]]+\][^\n]*|.+)$/i);
    if (errLong) params.err = errLong[1].trim();
    return params;
  }

  function parseLine(raw) {
    var s = String(raw || '').trim();
    var ctx = { raw: s, timestamp: null, module: null, level: null, message: s, params: {} };
    var py = s.match(RE_PY_LOG);
    if (py) {
      ctx.timestamp = py[1];
      ctx.module = py[2];
      ctx.level = py[3].toUpperCase();
      ctx.message = py[4];
      ctx.params = extractParams(ctx.message);
      return ctx;
    }
    var br = s.match(RE_BRACKET_LOG);
    if (br) {
      ctx.timestamp = br[1];
      ctx.level = br[2].toUpperCase();
      var rest = br[3];
      var modMatch = rest.match(/^(\S+(?:\.\S+)+)\s+(.+)$/);
      if (modMatch) {
        ctx.module = modMatch[1];
        ctx.message = modMatch[2];
      } else {
        ctx.message = rest;
      }
      ctx.params = extractParams(rest);
      return ctx;
    }
    var mgr = s.match(RE_MANAGER_LOG);
    if (mgr) {
      ctx.timestamp = mgr[1];
      ctx.level = mgr[2].toUpperCase();
      ctx.message = mgr[3];
      ctx.params = extractParams(mgr[3]);
      return ctx;
    }
    ctx.params = extractParams(s);
    return ctx;
  }

  function sslContext(msg) {
    if (/Balance fetch|get_wallet|get_account_balances|spot_engine/i.test(msg)) {
      return 'Binance hesap bakiyesi çekme';
    }
    if (/reconcile_open_orders/i.test(msg)) {
      return 'Açık emirleri Binance ile eşleme (reconcile)';
    }
    if (/BALANCE_CHECK|balance check/i.test(msg)) {
      return 'Emir öncesi bakiye kontrolü';
    }
    if (/get_price|price_hub|ticker|exchangeInfo/i.test(msg)) {
      return 'Binance piyasa/fiyat verisi çekme';
    }
    return 'Binance veya harici API HTTPS bağlantısı';
  }

  var RULES = [
    {
      test: function (msg) {
        return RE_HTTP_ACCESS.test(msg) && /\b(GET|POST|PUT|DELETE|PATCH)\s+\/api\//i.test(msg);
      },
      apply: function (ctx) {
        var msg = ctx.message || ctx.raw || '';
        var http = msg.match(RE_HTTP_ACCESS);
        if (!http) return null;
        var method = http[1];
        var path = http[2];
        var status = http[3];
        if (/\/api\/server\/manager\/restart/.test(path) && status === '400') {
          return {
            konu: 'Tam yeniden başlatma isteği reddedildi (400)',
            sebep: 'Eski Manager sürümünde «/api/server/manager/restart» yolu yanlış eşleşiyordu; istek geçersiz anahtar olarak işlendi.',
            etki: 'Sistem yeniden başlatılmadı.',
            oneri: 'Manager\'ı güncel kodla yeniden başlatın; «Yeniden başlat» artık /api/stack/restart kullanır.'
          };
        }
        if (/\/api\/stack\/restart/.test(path) && status === '200') {
          return {
            konu: 'Tam sistem yeniden başlatma başlatıldı',
            sebep: 'Panel tüm servisleri (Manager, Web, Engine, HTML) yeniden başlatma komutunu gönderdi.',
            etki: 'Servisler kısa süre durur; panel birkaç saniye yanıt vermeyebilir.',
            oneri: '30–60 sn bekleyin; sayfa otomatik yenilenmezse F5 ile Manager\'a tekrar bağlanın.'
          };
        }
        if (/\/api\/global\/restart/.test(path) && status === '409') {
          return {
            konu: 'Toplu yeniden başlatma zaten sürüyor',
            sebep: '«Tümünü yeniden başlat» isteği gönderildi; önceki toplu işlem (start/stop/restart) henüz bitmedi veya düğmeye tekrar basıldı.',
            etki: 'İkinci istek uygulanmadı; ilk işlem devam ediyor.',
            oneri: '30–60 sn bekleyin; durum kartları güncellenene kadar tekrar basmayın.'
          };
        }
        if (/\/api\/global\/(start|stop)/.test(path) && status === '409') {
          var actTr = /\/stop/.test(path) ? 'durdurma' : 'başlatma';
          return {
            konu: 'Toplu ' + actTr + ' zaten sürüyor',
            sebep: 'Panel toplu işlem gönderdi; önceki start/stop/restart henüz tamamlanmadı.',
            etki: 'İkinci istek uygulanmadı.',
            oneri: 'İşlem bitene kadar bekleyin; üst bildirimde «Başka bir toplu işlem sürüyor» görünebilir.'
          };
        }
        if (/\/api\/global\/(start|stop|restart)/.test(path) && status === '500') {
          return {
            konu: 'Toplu servis işlemi başarısız (500)',
            sebep: '«Tümünü başlat/durdur/yeniden başlat» isteği HTTP 500 döndü. 29.05.2026 öncesi sürümde schedule_global_action içinde UnboundLocalError biliniyordu; güncel kodda global _global_action_running ile düzeltildi.',
            etki: 'O anda toplu işlem uygulanmamış olabilir; servisler çalışıyorsa etki geçicidir.',
            oneri: 'Manager\'ı güncel kodla yeniden başlatın (.venv/bin/python -m manager_server), Ctrl+F5, tekrar deneyin. Eski uyarı için Yönetici → log sıfırla. Yine 500 ise manager.log traceback.'
          };
        }
        if ((/\/api\/stack\/restart/.test(path) || /\/api\/server\/manager\/restart/.test(path)) && status === '404') {
          return {
            konu: 'Tam yeniden başlatma API\'si yok (404)',
            sebep: 'Çalışan Manager süreci güncel kodu yüklemedi; bu endpoint henüz tanımlı değil.',
            etki: '«Yeniden başlat» işlemi yapılmadı.',
            oneri: 'Terminalden güncel kodla başlatın: .venv/bin/python -m manager_server veya ops/start.command — ardından tarayıcıda Ctrl+F5.'
          };
        }
        if (/\/api\/security\//.test(path) && status === '404') {
          return {
            konu: 'Güvenlik API\'si bulunamadı (404)',
            sebep: 'Panel IP engelleme uçlarını sorguladı; çalışan Manager sürümünde bu endpoint henüz yok veya eski.',
            etki: 'IP engelleme paneli çalışmayabilir; diğer servisler etkilenmez.',
            oneri: 'Manager\'ı güncel kodla yeniden başlatın.'
          };
        }
        if (/\/api\/issues\/summary/.test(path) && status === '404') {
          return {
            konu: 'Olay özeti API\'si yok (404)',
            sebep: 'Eski UI sürümü veya probe /api/issues/summary çağırdı; endpoint kaldırılmış veya taşınmış olabilir.',
            etki: 'Olay Merkezi özeti panelde boş kalabilir.',
            oneri: 'Manager ve tarayıcı önbelleğini yenileyin; güncel panelde Olay Merkezi sekmesini kullanın.'
          };
        }
        var stTr = status === '404' ? 'bulunamadı' : (status === '400' ? 'geçersiz istek' : ('HTTP ' + status));
        return {
          konu: 'Manager panel isteği: ' + method + ' ' + path,
          sebep: 'Yerel panel veya tarayıcı Manager API\'sine istek attı; yanıt ' + stTr + ' (' + status + ').',
          etki: Number(status) >= 500 ? 'İlgili panel işlemi başarısız olmuş olabilir.' : 'Genelde bilgi amaçlı; servisler çalışmaya devam eder.',
          oneri: status === '404' ? 'Endpoint adını ve Manager sürümünü kontrol edin.' : 'Tekrarlıyorsa manager.log içinde aynı zaman damgasını arayın.'
        };
      }
    },
    {
      test: function (msg) { return /BOT_EXECUTION_SKIP/i.test(msg); },
      apply: function (ctx) {
        var p = ctx.params || {};
        var skip = String(p.skip_reason || '').toUpperCase();
        var skipTr = SKIP_REASON_TR[skip] || (skip ? ('Emir atlandı: ' + skip) : 'Grid veya kapanış emri gönderilemedi');
        var botHint = p.bot_id ? (' (bot #' + p.bot_id + ')') : '';
        var gridHint = /trail_sell_grid|sell_grid/i.test(String(p.reason || ctx.message || ''))
          ? ' Satış gridi emri.'
          : (/trail_buy_grid|buy_grid/i.test(String(p.reason || ctx.message || '')) ? ' Alış gridi emri.' : '');
        var binHint = '';
        if (p.binance_code && p.binance_code !== 'None' && p.binance_code !== 'null') {
          binHint = ' Binance kodu: ' + p.binance_code + '.';
        }
        return {
          konu: 'Emir gönderilemedi' + botHint,
          sebep: skipTr + gridHint + binHint + (p.err ? (' Detay: ' + String(p.err).slice(0, 160)) : ''),
          etki: 'Bu tick\'te ilgili grid/kapanış emri yapılmadı; bot sonraki tick\'te tekrar dener. Tekrarlayan hatalarda sağlık uyarısı görünebilir.',
          oneri: skip === 'LOT_SIZE' || skip === 'ORDER_FAILED'
            ? 'Grid bütçesini, minimum tutarı (10 USDT) ve ETH serbest bakiyesini kontrol edin. Logdaki Binance mesaj koduna bakın.'
            : (skip === 'INSUFFICIENT_BALANCE' || skip === 'BINANCE_FREE_BASE_INSUFFICIENT'
              ? 'Binance cüzdanındaki serbest bakiyeyi kontrol edin; sanal bot bakiyesi gerçek bakiyeden fazla olabilir.'
              : 'Bot engine logunda aynı zaman damgasındaki teknik detayı inceleyin; gerekirse botu durdurup açık emirleri Binance\'ten kontrol edin.')
        };
      }
    },
    {
      test: function (msg) { return /BINANCE_SIGNED_ERROR/i.test(msg); },
      apply: function (ctx) {
        var m = String(ctx.message || ctx.raw || '');
        var status = (m.match(/\bstatus=(\d+)/) || [])[1] || '';
        var path = (m.match(/\bpath=([^\s]+)/) || [])[1] || '';
        var isOrder = /\/api\/v3\/order/i.test(path);
        return {
          konu: isOrder ? 'Binance emir isteği reddedildi' : 'Binance imzalı API hatası',
          sebep: 'Binance imzalı istek HTTP ' + (status || '?') + ' döndü'
            + (path ? (' (' + path + ').') : '.')
            + (isOrder && status === '400' ? ' Genelde miktar/lot filtresi, minimum tutar veya bakiye uyumsuzluğu.' : ''),
          etki: isOrder ? 'Emir borsaya iletilmedi; bot bir sonraki denemede tekrar dener.' : 'İlgili Binance sorgusu başarısız; senkron veya emir akışı gecikebilir.',
          oneri: status === '401'
            ? 'API anahtarı, IP whitelist ve sunucu saati (NTP) ayarlarını kontrol edin.'
            : (status === '400' && isOrder
              ? 'Emir miktarını, step size ve min notional kurallarını doğrulayın; serbest bakiyeyi Binance\'ten kontrol edin.'
              : 'Ağ bağlantısı ve Binance API durumunu kontrol edin; teknik detaydaki body/hint alanına bakın.')
        };
      }
    },
    {
      test: function (msg) { return /binance_spot signed method=/i.test(msg); },
      apply: function (ctx) {
        var m = String(ctx.message || ctx.raw || '');
        var status = (m.match(/\bstatus=(\S+)/) || [])[1] || '';
        var path = (m.match(/\bpath=([^\s]+)/) || [])[1] || '';
        var attempt = (m.match(/\battempt=(\d+)/) || [])[1] || '';
        var isOrder = /\/order/i.test(path);
        return {
          konu: isOrder ? 'Binance emir isteği başarısız (yeniden denenecek)' : 'Binance API isteği başarısız',
          sebep: 'İmzalı Binance isteği' + (attempt ? (' (deneme ' + attempt + ')') : '') + ' HTTP '
            + (status || '?') + ' ile döndü' + (path ? (' — ' + path) : '') + '.',
          etki: isOrder
            ? 'Emir henüz gönderilmedi; engine kısa süre içinde yeniden dener veya execution katmanında atlanır.'
            : 'Bakiye, emir veya hesap sorgusu gecikebilir.',
          oneri: status === '400' && isOrder
            ? 'Lot boyutu, minimum tutar (10 USDT) ve serbest bakiyeyi kontrol edin.'
            : 'Geçici ağ sorunu olabilir; tekrar ederse API anahtarı ve Binance durumunu kontrol edin.'
        };
      }
    },
    {
      test: function (msg) {
        return /Future exception was never retrieved|Task exception was never retrieved/i.test(msg)
          && /gaierror|nodename nor servname|ConnectError|ConnectTimeout/i.test(msg);
      },
      apply: function () {
        return {
          konu: 'Binance WebSocket DNS geçici hatası',
          sebep: 'Ağ/DNS anlık kesinti; arka planda Binance host adı çözülemedi (asyncio Future).',
          etki: 'Canlı fiyat WebSocket yeniden bağlanır; REST/cache devreye girer.',
          oneri: 'İnternet/DNS stabil ise birkaç dakika içinde düzelir; sürekli tekrarlıyorsa firewall/VPN kontrol edin.'
        };
      }
    },
    {
      test: function (msg) {
        return /binance_spot public_get/i.test(msg) && /status=400/.test(msg);
      },
      apply: function (ctx) {
        var path = (String(ctx.message || '').match(/path=([^\s]+)/) || [])[1] || '';
        var endpoint = path ? (' (' + path + ')') : '';
        return {
          konu: 'Geçersiz grafik sembolü (Binance 400)',
          sebep: 'Kline isteği geçersiz sembolle gitti' + endpoint + '; Binance reddetti (ör. BTC yerine BTCUSDT gerekir).',
          etki: 'Grafik boş kalabilir; doğru sembolle istek tekrarlanır.',
          oneri: 'UI sembol normalizasyonu otomatik; tekrarlıyorsa chart isteğindeki symbol parametresini kontrol edin.'
        };
      }
    },
    {
      test: function (msg) {
        return /binance_spot public_get/i.test(msg) && !/status=400/.test(msg);
      },
      apply: function (ctx) {
        var path = (String(ctx.message || '').match(/path=([^\s]+)/) || [])[1] || '';
        var endpoint = path ? (' (' + path + ')') : '';
        return {
          konu: 'Binance genel API isteği başarısız',
          sebep: 'Fiyat, exchangeInfo veya sunucu saati gibi imzasız Binance isteği hata aldı'
            + endpoint + '; yeniden deneme yapılıyor olabilir.',
          etki: 'Fiyat veya sembol filtresi güncellenemeyebilir; bot tick\'i gecikebilir.',
          oneri: 'Ağ ve SSL ayarlarını kontrol edin; sürekli tekrarlıyorsa Binance erişilebilirliğini doğrulayın.'
        };
      }
    },
    {
      test: function (msg) { return /BOT_EXECUTION_CAP_BASE/i.test(msg); },
      apply: function (ctx) {
        var p = ctx.params || {};
        return {
          konu: 'Satış miktarı gerçek bakiyeye kısıtlandı',
          sebep: 'Bot state\'indeki coin miktarı Binance serbest bakiyesinden fazlaydı; emir gönderilmeden önce miktar otomatik düşürüldü'
            + (p.bot_id ? (' (bot #' + p.bot_id + ').') : '.'),
          etki: 'Emir daha küçük miktarla gönderilir; lot filtresine uymazsa yine reddedilebilir.',
          oneri: 'Komisyon/rounding farkı normal olabilir. Tekrarlayan reddedilmelerde grid bütçesini ve min tutarı gözden geçirin.'
        };
      }
    },
    {
      test: function (msg) { return /run_actions WEIGHT_DENIED|skip_reason=WEIGHT_DENIED/i.test(msg); },
      apply: function (ctx) {
        var p = ctx.params || {};
        return {
          konu: 'Binance istek limiti (weight) aşıldı',
          sebep: 'Emir gönderilmeden önce Binance API weight kotası alınamadı; istek sırası bekletildi veya atlandı'
            + (p.bot_id ? (' (bot #' + p.bot_id + ').') : '.'),
          etki: 'Bu tick\'te emir gönderilmez; weight boşalınca devam eder.',
          oneri: 'Çok sayıda bot veya sık tick varsa weight kullanımını azaltın; geçici ise bekleyin.'
        };
      }
    },
    {
      test: function (msg) { return /run_actions TIMEOUT|ORDER_TIMEOUT|skip_reason=ORDER_TIMEOUT/i.test(msg); },
      apply: function (ctx) {
        var p = ctx.params || {};
        return {
          konu: 'Emir gönderimi zaman aşımı',
          sebep: 'Binance emir isteği belirlenen sürede yanıt vermedi; emir durumu belirsiz (unknown) olarak işaretlendi'
            + (p.bot_id ? (' (bot #' + p.bot_id + ').') : '.'),
          etki: 'Emir borsada açılmış olabilir; reconcile bir sonraki tick\'te durumu netleştirir.',
          oneri: 'Binance açık emirler ve işlem geçmişini kontrol edin; ağ gecikmesi sürerse timeout ayarlarını gözden geçirin.'
        };
      }
    },
    {
      test: function (msg) { return /BOT SLIPPAGE_WARN|SLIPPAGE_WARN/i.test(msg); },
      apply: function (ctx) {
        var slip = (String(ctx.message || '').match(/slip_pct=([\d.]+)/) || [])[1];
        return {
          konu: 'Yüksek kayma (slippage) uyarısı',
          sebep: 'Gerçekleşen fiyat tetik fiyatından beklenenden fazla sapmış'
            + (slip ? (' (kayma %' + slip + ').') : '.'),
          etki: 'Emir yine de gerçekleşmiş olabilir; K/Z ve grid hesabı etkilenebilir.',
          oneri: 'Volatil piyasa veya düşük likidite olabilir; max_slippage_pct ayarını ve grid yüzdelerini gözden geçirin.'
        };
      }
    },
    {
      test: function (msg) { return /write_fill_snapshot|update_virtual_after_fill|record_trade failed|BOT_EXECUTION_REPAIR/i.test(msg); },
      apply: function (ctx) {
        var isRepair = /REPAIR/i.test(ctx.message || '');
        return {
          konu: isRepair ? 'Emir onarımı / kayıt hatası' : 'Fill sonrası state güncelleme hatası',
          sebep: isRepair
            ? 'Borsada bulunan emir bot state\'ine veya işlem tablosuna yazılırken hata oluştu.'
            : 'Emir başarılı olsa da bakiye snapshot\'ı, sanal cüzdan veya işlem kaydı güncellenemedi.',
          etki: 'UI bakiyesi veya işlem geçmişi kısa süre eski kalabilir; strateji state\'i kısmen güncellenmiş olabilir.',
          oneri: 'DB ve disk alanını kontrol edin; bot detay sayfasını yenileyin; hata sürerse botu durdurup state ile Binance\'i karşılaştırın.'
        };
      }
    },
    {
      test: function (msg) { return /Binance server time unavailable|using local timestamp/i.test(msg); },
      apply: function () {
        return {
          konu: 'Binance sunucu saati alınamadı',
          sebep: 'Binance /api/v3/time yanıt vermedi; istek imzalarında yerel saat kullanılıyor.',
          etki: 'Saat farkı büyükse 401 imza hatası ve emir reddi oluşabilir.',
          oneri: 'Sunucu saatini NTP ile senkronize edin (macOS: Sistem Ayarları → Tarih ve Saat).'
        };
      }
    },
    {
      test: function (msg) { return /^\[401\/Binance uyarısı/i.test(msg); },
      apply: function () {
        return {
          konu: 'Binance / 401 yetkilendirme uyarısı (özet)',
          sebep: 'Son 10 dakikada tekrarlayan 401 Unauthorized veya Binance API yetki uyarıları tek satırda özetlendi. Aynı uyarılar paneli doldurmaması için kısaltıldı.',
          etki: 'API anahtarı geçersiz, süresi dolmuş veya IP kısıtlaması varsa emir/bakiye işlemleri başarısız olabilir.',
          oneri: 'Binance API anahtarını (okuma + spot işlem izinleri) ve IP whitelist ayarını kontrol edin. Manager log dosyasında tam satırları arayın: "401 Unauthorized".'
        };
      }
    },
    {
      test: function (msg) { return /CERTIFICATE_VERIFY_FAILED|unable to get local issuer certificate|SSL:.*verify/i.test(msg); },
      apply: function (ctx) {
        var action = sslContext(ctx.message);
        return {
          konu: 'SSL/TLS sertifika doğrulama hatası',
          sebep: action + ' sırasında HTTPS sertifikası doğrulanamadı. Python/istemci, sunucu sertifikasını imzalayan yerel CA (Certificate Authority) zincirini bulamıyor veya güvenmiyor.',
          etki: 'Web katmanında cüzdan/bakiye güncellenmeyebilir; engine tarafında açık emir eşleme (reconcile) atlanabilir. Bot worker kendi state ile çalışmaya devam edebilir; ancak borsa senkronu gecikebilir.',
          oneri: 'macOS geliştirmede: /Applications/Python 3.x/Install Certificates.command çalıştırın. Kalıcı çözüm: pip install certifi ve ortam değişkeni SSL_CERT_FILE=$(python -m certifi) (veya REQUESTS_CA_BUNDLE) tanımlayıp web + engine servislerini yeniden başlatın.'
        };
      }
    },
    {
      test: function (msg) { return /Balance fetch error|get_account_balances failed|write_fill_snapshot get_account_balances/i.test(msg); },
      apply: function (ctx) {
        return {
          konu: 'Hesap bakiyesi alınamadı',
          sebep: 'Binance API üzerinden hesap bakiyesi okunurken istek başarısız oldu.',
          etki: 'UI cüzdan tablosu ve spot_engine bakiye önbelleği güncellenmeyebilir; gösterilen bakiye eski kalabilir.',
          oneri: 'Ağ bağlantısı, API anahtarı ve SSL sertifika ayarlarını kontrol edin. Teknik detaydaki hata koduna göre ilerleyin.'
        };
      }
    },
    {
      test: function (msg) { return /reconcile_open_orders/i.test(msg); },
      apply: function () {
        return {
          konu: 'Açık emir eşleme (reconcile) başarısız',
          sebep: 'Bot engine, veritabanındaki açık emirleri Binance ile karşılaştırırken (intent_ledger reconcile) hata aldı.',
          etki: 'Emir durumu geçici olarak senkron dışı kalabilir; bot bir sonraki tick\'te tekrar dener.',
          oneri: 'SSL/ağ/API anahtarı sorunlarını giderin. Hata sürerse botu durdurup açık emirleri Binance arayüzünden kontrol edin.'
        };
      }
    },
    {
      test: function (msg) { return /401 Unauthorized|BOT_EXECUTION_BALANCE_CHECK_FAIL.*401|BOT_ACCOUNT_KEYS_FAIL/i.test(msg); },
      apply: function () {
        return {
          konu: 'Binance API yetkilendirme hatası (401)',
          sebep: 'Binance API isteği reddedildi: kimlik doğrulama başarısız (401 Unauthorized). API anahtarı, imza veya izinler geçersiz olabilir.',
          etki: 'Bakiye sorgusu, emir gönderme veya emir iptali çalışmayabilir; bot hata durumuna geçebilir.',
          oneri: 'Hesap API anahtarını yenileyin; Spot & Margin Trading + okuma izinlerini açın; IP kısıtlaması varsa sunucu IP\'sini whitelist\'e ekleyin.'
        };
      }
    },
    {
      test: function (msg) { return /BOT_LIVE_NO_KEYS|paused_error.*FAIL FAST/i.test(msg); },
      apply: function () {
        return {
          konu: 'Canlı modda API anahtarı bulunamadı',
          sebep: 'Bot canlı (live) modda çalışıyor ancak hesaba bağlı geçerli Binance API anahtarı yok.',
          etki: 'Bot tick\'leri atlanır veya bot hata durumunda bekler; işlem yapılmaz.',
          oneri: 'Dashboard → Hesaplar bölümünden API anahtarlarını kaydedin ve botu yeniden başlatın.'
        };
      }
    },
    {
      test: function (msg) { return /lease_not_valid/i.test(msg); },
      apply: function () {
        return {
          konu: 'Bot kilit (lease) geçersiz',
          sebep: 'Bu bot için sembol kilidi (lease) süresi dolmuş veya başka bir worker tarafından alınmış.',
          etki: 'Bu tick\'te emir gönderilmez; bir sonraki tick\'te lease yenilenince devam eder.',
          oneri: 'Birden fazla engine instance çalıştırmıyorsanız bekleyin. Sürekli tekrarlıyorsa engine\'i tek instance olacak şekilde yeniden başlatın.'
        };
      }
    },
    {
      test: function (msg) { return /Connection refused|ConnectionError|Name or service not known|ECONNREFUSED/i.test(msg); },
      apply: function () {
        return {
          konu: 'Bağlantı reddedildi / hedefe ulaşılamadı',
          sebep: 'TCP bağlantısı kurulamadı: hedef servis kapalı, yanlış adres/port veya ağ erişimi yok.',
          etki: 'İlgili API veya veritabanı çağrısı başarısız; özellik çalışmaz.',
          oneri: 'Hedef servisin (DB, Redis, Binance, localhost port) ayakta olduğunu ve firewall kurallarını kontrol edin.'
        };
      }
    },
    {
      test: function (msg) { return /timeout|TimeoutError|timed out|Read timed out/i.test(msg); },
      apply: function () {
        return {
          konu: 'İstek zaman aşımı (timeout)',
          sebep: 'Karşı taraf belirlenen sürede yanıt vermedi; ağ gecikmesi veya sunucu yükü olabilir.',
          etki: 'İşlem yarım kalabilir; bot/engine bir sonraki denemede tekrar dener.',
          oneri: 'Ağ kalitesini ve Binance API durumunu kontrol edin; sık tekrarlıyorsa timeout sürelerini ve rate limit ayarlarını gözden geçirin.'
        };
      }
    },
    {
      test: function (msg) { return /ModuleNotFoundError|No module named/i.test(msg); },
      apply: function () {
        return {
          konu: 'Eksik Python modülü',
          sebep: 'Gerekli Python paketi yüklü değil veya yanlış sanal ortam (venv) kullanılıyor.',
          etki: 'Servis veya ilgili özellik başlamayabilir / import hatası verir.',
          oneri: 'Proje kökünde pip install -r requirements.txt çalıştırın; servisi doğru venv ile başlatın.'
        };
      }
    },
    {
      test: function (msg) {
        return /home_wallet_refresh/i.test(msg) && /\berror=/i.test(msg) && /get_price_map_flat|cannot import name/i.test(msg);
      },
      apply: function (ctx) {
        var m = (ctx.message || ctx.raw || '').match(/\berror=([^\s]+(?:\s+[^\s]+){0,12})/i);
        var detail = m ? m[1].trim() : 'cüzdan yenileme başarısız';
        return {
          konu: 'Cüzdan yenileme başarısız (önbellek kullanılır)',
          sebep: 'Canlı Binance cüzdan çekimi tamamlanamadı: ' + detail,
          etki: 'Dashboard önbellekli cüzdan gösterir; K/Z kartları etkilenmez.',
          oneri: 'Web servisini yeniden başlatın (market_data güncellemesi yüklensin).'
        };
      }
    },
    {
      test: function (msg) { return /wallet_refresh_attempt error_code=BINANCE_TIMEOUT/i.test(msg); },
      apply: function (ctx) {
        var acct = (ctx.params && ctx.params.account_id) || (ctx.message || '').match(/account_id=(\d+)/i);
        return {
          konu: 'Cüzdan yenileme — Binance zaman aşımı',
          sebep: 'Canlı cüzdan çekimi ' + (acct ? ('(hesap ' + (acct[1] || acct) + ') ') : '') + 'süre içinde tamamlanamadı. İnternet kesintisi, yavaş ağ veya Binance yanıt gecikmesi olabilir.',
          etki: 'Dashboard «Güncel değil» gösterir; önbellekli bakiye ($) görünür ama canlı değildir.',
          oneri: 'Ayarlar → Sunucu dış IP\'yi Binance API beyaz listesine ekleyin (kendi PC IP\'si değil). Ağ düzeldikten sonra sayfayı yenileyin veya Portföy → Yenile.'
        };
      }
    },
    {
      test: function (msg) { return /wallet_refresh_attempt error_code=BINANCE_IP_BANNED/i.test(msg); },
      apply: function () {
        return {
          konu: 'Cüzdan yenileme — Binance IP ban (418)',
          sebep: 'Binance bu sunucu IP\'sinden gelen istekleri geçici olarak engelledi (rate limit / ban).',
          etki: 'Cüzdan canlı yenilenmez; cooldown sonrası tekrar denenecek.',
          oneri: '15–30 dk bekleyin; istek sıklığını azaltın. Kalıcıysa Binance destek veya farklı çıkış IP.'
        };
      }
    },
    {
      test: function (msg) { return /wallet_refresh_attempt error_code=BINANCE_RATE_LIMIT/i.test(msg); },
      apply: function () {
        return {
          konu: 'Cüzdan yenileme — Binance istek limiti',
          sebep: 'Çok sık cüzdan/API isteği; Binance 429 veya ağırlık limiti döndü.',
          etki: 'Kısa cooldown; önbellekli cüzdan gösterilir.',
          oneri: 'Birkaç dakika bekleyin; eşzamanlı sekme/poll sayısını azaltın.'
        };
      }
    },
    {
      test: function (msg) {
        return /(?:open_orders|wallet)\s+upstream_error/i.test(msg);
      },
      apply: function (ctx) {
        var msg = ctx.message || ctx.raw || '';
        var isOpenOrders = /open_orders/i.test(msg);
        var reasonM = msg.match(/reason=([^\s]+)/i);
        var reason = reasonM ? reasonM[1] : '';
        var errM = msg.match(/error=([^\s(]+)/i);
        var errType = errM ? errM[1] : '';
        var statusM = msg.match(/status=([^\s]+)/i);
        var status = statusM ? statusM[1] : '?';
        var acct = ctx.params.account_id || (msg.match(/account_id=(\d+)/i) || [])[1];
        var acctTxt = acct ? (' (hesap #' + acct + ')') : '';
        if (reason === 'invalid_api_key') {
          return {
            konu: isOpenOrders ? 'Açık emirler — Binance API anahtarı geçersiz' : 'Cüzdan — Binance API anahtarı geçersiz',
            sebep: 'Binance isteği reddedildi: API anahtarı yok, süresi dolmuş veya IP izni eksik (401 / -2015).',
            etki: isOpenOrders
              ? 'Açık emir listesi boş dönebilir; bot engine kendi emirlerini ayrı kanaldan yönetir.'
              : 'Cüzdan tablosu boş veya eski bakiye gösterebilir.',
            oneri: 'Dashboard → Ayarlar: API Key + Secret kaydedin; Binance’te Spot izinleri ve sunucu IP whitelist açık olsun.'
          };
        }
        var sebep = (isOpenOrders
          ? 'Binance açık emir listesi alınamadı'
          : 'Binance cüzdan bakiyesi alınamadı') + acctTxt + '. ';
        if (/DependencyFailure/i.test(errType) || /circuit breaker|retry budget/i.test(msg)) {
          sebep += 'İstek koruması devreye girdi: çok sık Binance çağrısı, devre kesici açık veya yeniden deneme kotası doldu.';
        } else if (status === '429') {
          sebep += 'Binance istek limiti (429) aşıldı.';
        } else {
          sebep += 'Binance geçici yanıt vermedi (HTTP ' + status + (errType ? ', ' + errType : '') + ').';
        }
        if (/cache_empty=true/i.test(msg)) {
          sebep += ' Önbellek boş olduğu için arayüze boş liste ve «güncel değil» bilgisi döndürüldü (HTTP 200, hata ekranı yok).';
        } else if (/serve_stale|cache_hit=true/i.test(msg)) {
          sebep += ' Önbellekteki son bilinen veri «güncel değil» olarak sunuldu.';
        }
        return {
          konu: isOpenOrders ? 'Açık emirler — Binance geçici hata' : 'Cüzdan — Binance geçici hata',
          sebep: sebep,
          etki: isOpenOrders
            ? 'Dashboard açık emir paneli boş veya eski görünebilir; bot işlemleri engine tarafında devam eder.'
            : 'Dashboard cüzdanı boş veya eski bakiye gösterebilir; ~10 sn sonra otomatik yeniden denenecek.',
          oneri: 'Birkaç dakika bekleyin. Sık tekrarlıyorsa açık sekme/poll sayısını azaltın; Binance API limiti ve sunucu bağlantısını kontrol edin.'
        };
      }
    },
    {
      test: function (msg) { return /\[snapshot\]\s+\w+\s+timeout/i.test(msg); },
      apply: function (ctx) {
        var nameM = (ctx.message || ctx.raw || '').match(/\[snapshot\]\s+(\w+)\s+timeout/i);
        var part = nameM ? nameM[1] : 'bileşen';
        return {
          konu: 'Dashboard snapshot — ' + part + ' zaman aşımı',
          sebep: 'Anlık dashboard snapshot isteğinde «' + part + '» parçası belirlenen sürede tamamlanamadı.',
          etki: 'Push ile gelen veri eksik olabilir; sayfa bir sonraki güncellemede tamamlanır.',
          oneri: 'Tek seferlik ise yok sayın. Sık tekrarlıyorsa veritabanı yükü ve Binance bağlantısını kontrol edin.'
        };
      }
    },
    {
      test: function (msg) { return /\[snapshot\]\s+\w+\s+error:/i.test(msg); },
      apply: function (ctx) {
        var m = (ctx.message || ctx.raw || '').match(/\[snapshot\]\s+(\w+)\s+error:\s*(.+)/i);
        var part = m ? m[1] : 'bileşen';
        var fullDetail = m ? m[2].trim().slice(0, 220) : 'bilinmeyen hata';
        var sebep = 'Anlık snapshot «' + part + '» yüklenirken hata: ' + fullDetail;
        if (/401|Unauthorized|Invalid API-key/i.test(fullDetail) && part === 'wallet') {
          sebep = 'Snapshot cüzdan bileşeni Binance yetkilendirme hatası aldı (401). API anahtarı veya IP whitelist kontrol edin.';
        }
        return {
          konu: 'Dashboard snapshot — ' + part + ' hatası',
          sebep: sebep,
          etki: 'İlgili dashboard alanı güncellenmeyebilir; diğer snapshot parçaları gelmiş olabilir.',
          oneri: part === 'wallet'
            ? 'API anahtarı ve IP iznini doğrulayın.'
            : 'Ağ/Binance durumunu kontrol edin; sayfayı yenileyin.'
        };
      }
    },
    {
      test: function (msg) { return /wallet_refresh_attempt error_code=CLOCK_DRIFT/i.test(msg); },
      apply: function () {
        return {
          konu: 'Cüzdan yenileme — sunucu saati sapması (-1021)',
          sebep: 'Sunucu saati Binance ile uyuşmuyor; imzalı API istekleri reddedilir.',
          etki: 'Canlı cüzdan ve emirler başarısız olabilir.',
          oneri: 'Sunucuda NTP/chrony ile saat senkronu; macOS/Linux: sudo sntp -sS time.apple.com veya systemctl restart chronyd.'
        };
      }
    },
    {
      test: function (msg) {
        return /wallet_refresh_attempt error_code=/i.test(msg)
          && (/API_UNAUTHORIZED|ACCOUNT_KEYS|401|2015|invalid.api/i.test(msg) || /err=.*(?:401|Unauthorized|Invalid API)/i.test(msg));
      },
      apply: function (ctx) {
        var acct = (ctx.params && ctx.params.account_id) || (ctx.message || '').match(/account_id=(\d+)/i);
        return {
          konu: 'Cüzdan yenileme — API anahtarı veya IP beyaz liste',
          sebep: 'Binance 401/-2015 veya hesapta API anahtarı eksik/geçersiz. Binance kısıtı varsa yalnızca sunucunun dış IP\'si whitelist\'te olmalı (tarayıcı/PC IP\'si yetmez).',
          etki: '«Güncel değil»; bot sayfasında bağlantı hatası görülebilir.',
          oneri: (acct ? 'Hesap ' + (acct[1] || acct) + ': ' : '') + 'Dashboard Ayarlar → Sunucu dış IP\'yi Binance\'e ekleyin; API key Spot+Read; secret doğru.'
        };
      }
    },
    {
      test: function (msg) { return /wallet_refresh_attempt error_code=/i.test(msg); },
      apply: function (ctx) {
        var codeM = (ctx.message || ctx.raw || '').match(/error_code=([^\s]+)/i);
        var code = codeM ? codeM[1] : 'bilinmeyen';
        var errM = (ctx.message || ctx.raw || '').match(/err=([^\n]{0,200})/i);
        var detail = errM ? errM[1].trim() : '';
        return {
          konu: 'Cüzdan yenileme başarısız (' + code + ')',
          sebep: 'Canlı Binance cüzdan snapshot alınamadı.' + (detail ? ' ' + detail : ''),
          etki: 'Dashboard önbellek kullanır; KPI «Güncel değil» kalabilir.',
          oneri: 'Sunucu dış IP + API anahtarı kontrolü; web servisini yeniden başlatın; ağ düzelince sayfayı yenileyin.'
        };
      }
    },
    {
      test: function (msg) {
        return /home_wallet_refresh/i.test(msg) && /\berror=/i.test(msg) && !/error=api_key_invalid/i.test(msg);
      },
      apply: function (ctx) {
        var errM = (ctx.message || ctx.raw || '').match(/\berror=([^\s]+(?:\s+[^\s]+){0,8})/i);
        var detail = errM ? errM[1].trim() : 'bağlantı hatası';
        return {
          konu: 'Anasayfa cüzdan yenileme tamamlanamadı',
          sebep: 'POST /api/home/wallet/refresh başarısız: ' + detail,
          etki: 'Önbellekli bakiye gösterilir; canlı rozeti «Güncel değil».',
          oneri: 'Binance beyaz listeye sunucu IP ekleyin; birkaç dakika sonra dashboard yenileyin.'
        };
      }
    },
    {
      test: function (msg) { return /\[home\]\s*home_fast\s+payload_bytes=/i.test(msg); },
      apply: function (ctx) {
        var m = (ctx.message || ctx.raw || '').match(/payload_bytes=(\d+).*warn=(\d+)/i);
        return {
          konu: 'Anasayfa hızlı yükleme — büyük yanıt',
          sebep: 'home/fast JSON yanıtı uyarı eşiğini aştı' + (m ? (' (' + m[1] + ' bayt, eşik ' + m[2] + ')') : '') + '.',
          etki: 'Yavaş yükleme; işlev bozulmaz.',
          oneri: 'Gerekirse home_fast_max_assets veya fiyat sembol sayısını düşürün; kritik değil.'
        };
      }
    },
    {
      test: function (msg) {
        return /wallet_refresh_attempt error_code=(?:ImportError|WALLET_MODULE_MISSING)/i.test(msg);
      },
      apply: function (ctx) {
        var m = (ctx.message || ctx.raw || '').match(/err=([^\n]+)/i);
        var detail = m ? m[1].trim() : 'market_data / wallet_pricing içe aktarımı';
        return {
          konu: 'Cüzdan yenileme — eksik kod modülü',
          sebep: 'Binance cüzdan snapshot\'ı fiyat haritası yüklerken içe aktarım başarısız: ' + detail,
          etki: 'Anasayfa cüzdan canlı yenilemesi çalışmaz; önbellekli snapshot kullanılır.',
          oneri: 'Web servisini yeniden başlatın; app/services/market_data.py güncel mi kontrol edin.'
        };
      }
    },
    {
      test: function (msg) {
        return /ImportError/i.test(msg)
          && !/error_code=ImportError/i.test(msg)
          && !/cannot import name/i.test(msg);
      },
      apply: function () {
        return {
          konu: 'Python import hatası',
          sebep: 'Modül içe aktarılırken hata oluştu (eksik bağımlılık, döngüsel import veya sözdizimi).',
          etki: 'İlgili kod yolu çalışmaz; servis kısmen veya tamamen etkilenebilir.',
          oneri: 'Teknik detaydaki modül adını kontrol edin; requirements.txt ve Python sürümünü doğrulayın.'
        };
      }
    },
    {
      test: function (msg) { return /sqlalchemy|OperationalError|database is locked|could not connect.*database/i.test(msg); },
      apply: function () {
        return {
          konu: 'Veritabanı hatası',
          sebep: 'SQLite/veritabanı sorgusu veya bağlantısı başarısız oldu.',
          etki: 'Bot state, işlem kaydı veya API yanıtları etkilenebilir.',
          oneri: 'DB dosyası izinlerini, disk doluluğunu ve eşzamanlı yazma kilidini kontrol edin; gerekirse servisleri sırayla yeniden başlatın.'
        };
      }
    },
    {
      test: function (msg) { return /Permission denied|PermissionError|EACCES/i.test(msg); },
      apply: function () {
        return {
          konu: 'Dosya / izin hatası',
          sebep: 'İşletim sistemi dosya veya kaynağa erişimi reddetti (yetki yetersiz).',
          etki: 'Log yazma, config okuma veya DB erişimi başarısız olabilir.',
          oneri: 'Proje dizini ve log/DB dosyalarının çalışan kullanıcı tarafından okunup yazılabildiğini doğrulayın.'
        };
      }
    },
    {
      test: function (msg) { return /ADMIN_ACCOUNTS_LIST/i.test(msg); },
      apply: function (ctx) {
        var raw = ctx.message || ctx.raw || '';
        var durM = raw.match(/duration_ms=(\d+)/);
        var dur = durM ? durM[1] + ' ms' : '—';
        var liteM = raw.match(/lite=(True|False|true|false)/);
        var lite = liteM ? liteM[1] : '—';
        var walletM = raw.match(/wallet_errors=(\[[^\]]*\]|None)/);
        var slowM = raw.match(/slow_wallets=(\[[^\]]*\]|None)/);
        var reqM = raw.match(/request_id=([^\s]+)/);
        return {
          konu: 'Admin hesap listesi yavaş / hatalı',
          sebep: 'GET /api/admin/accounts toplam ' + dur + ' sürdü (lite=' + lite + '). '
            + 'Her hesap için Binance cüzdan + bot KPI çekilir; çok hesapta veya API gecikmesinde 12sn+ olabilir. '
            + 'wallet_errors=' + (walletM ? walletM[1] : '—') + ' slow_wallets=' + (slowM ? slowM[1] : '—')
            + (reqM ? ' request_id=' + reqM[1] : ''),
          etki: 'Admin paneli Hesaplar sekmesi geç açılır veya "Yükleniyor…" uzun kalır; geçici ağ hatası toast\'u görülebilir.',
          oneri: 'Manager log\'da ADMIN_ACCOUNTS_LIST satırını request_id ile arayın; slow_wallets hesapları Binance API gecikmesi olabilir. '
            + 'İlk yükleme lite=1 ile hızlandırılır; tam veri arka planda gelir. Sorun sürerse hesap sayısını ve Binance rate limit\'i kontrol edin.'
        };
      }
    },
    {
      test: function (msg) { return /ADMIN_ACCOUNTS_(LOAD|FULL_REFRESH)_FAIL|ADMIN_PANEL_CLIENT_ERROR.*ADMIN_ACCOUNTS/i.test(msg); },
      apply: function (ctx) {
        var raw = ctx.message || ctx.raw || '';
        var ctxStr = typeof ctx.context === 'string' ? ctx.context : (ctx.context ? JSON.stringify(ctx.context) : raw);
        return {
          konu: 'Admin hesaplar istemci/sunucu yükleme hatası',
          sebep: 'Tarayıcı /api/admin/accounts isteğini tamamlayamadı veya HTTP hata döndü. Ham: ' + (raw.slice(0, 400) || ctxStr.slice(0, 400)),
          etki: 'Hesaplar sekmesi boş kalır veya eski önbellek gösterilir; "geçici ağ hatası" uyarısı çıkabilir.',
          oneri: 'context içindeki http_status, duration_ms, request_id ve fetch_url ile web.log\'da eşleşen ADMIN_ACCOUNTS_LIST veya SLOW_REQUEST satırını bulun. '
            + '502/503/504 ise web servisi yeniden başlatın; 499 ise istek zaman aşımı — admin accounts endpoint\'i ağır olabilir.'
        };
      }
    },
    {
      test: function (msg) { return /SLOW_REQUEST/i.test(msg); },
      apply: function () {
        return {
          konu: 'Yavaş HTTP isteği',
          sebep: 'Bir API isteği beklenenden uzun sürdü (SLOW_REQUEST eşiği aşıldı).',
          etki: 'Kullanıcı arayüzü gecikebilir; işlem tamamlanmış olabilir.',
          oneri: 'Yük altında mı bakın; yavaş sorguları ve dış API gecikmelerini profil edin.'
        };
      }
    },
    {
      test: function (msg) { return /ConnectionClosedOK|1001 \(going away\)|received 1001/i.test(msg); },
      apply: function () {
        return {
          konu: 'WebSocket normal kapanış',
          sebep: 'İstemci sayfadan ayrılırken WebSocket bağlantısı normal şekilde kapandı (1001 going away).',
          etki: 'Beklenen davranış; genelde sorun değildir.',
          oneri: 'Sürekli tekrar etmiyorsa müdahale gerekmez.'
        };
      }
    },
    {
      test: function (msg) { return /Traceback \(most recent call last\)/i.test(msg); },
      apply: function () {
        return {
          konu: 'Python istisna (Traceback)',
          sebep: 'Beklenmeyen Python hatası oluştu; stack trace log dosyasında devam eder.',
          etki: 'İlgili istek veya bot tick\'i başarısız olmuş olabilir.',
          oneri: 'Ana log akışında Traceback satırlarının devamını okuyun; exception tipi ve dosya/satır bilgisine göre düzeltin.'
        };
      }
    },
    {
      test: function (msg) { return /BOT_STRATEGY_PRICE_INVALID|price invalid/i.test(msg); },
      apply: function () {
        return {
          konu: 'Geçersiz fiyat verisi',
          sebep: 'Strateji tick\'i sıfır, negatif veya eksik fiyat aldı; grid hesaplanamadı.',
          etki: 'Bu tick\'te emir üretilmez; fiyat normale dönünce devam eder.',
          oneri: 'Binance bağlantısı ve price_hub/datahub akışını kontrol edin.'
        };
      }
    },
    {
      test: function (msg) { return /kill_switch/i.test(msg); },
      apply: function () {
        return {
          konu: 'Kill switch uyarısı',
          sebep: 'Bot kill switch kontrolü sırasında uyarı loglandı.',
          etki: 'Acil durdurma veya emir iptali tetiklenmiş olabilir.',
          oneri: 'Bot durumunu ve açık emirleri kontrol edin; kill switch nedenini inceleyin.'
        };
      }
    },
    {
      test: function (msg) { return /EADDRINUSE|Address already in use|port.*in use|error while attempting to bind/i.test(msg); },
      apply: function (ctx) {
        var msg = ctx.message || ctx.raw || '';
        var is7999 = /7999|127\.0\.0\.1['\u2019]?\s*,\s*7999/i.test(msg);
        if (is7999) {
          return {
            konu: 'Manager portu geçici çakışma (7999)',
            sebep: 'Tam yeniden başlat sırasında eski Manager süreci portu henüz bırakmadan yeni süreç başlatılmaya çalışıldı.',
            etki: 'Bu satır genelde zararsızdır; birkaç saniye sonra tek Manager ayakta kalır.',
            oneri: 'Panel yanıt veriyorsa yok sayın. Yanıt yoksa: lsof -i :7999 ile çift süreç var mı bakın; gerekirse ops/start.command veya tek python -m manager_server.'
          };
        }
        return {
          konu: 'Port kullanımda',
          sebep: 'Servis hedef porta bağlanamadı; port başka bir süreç tarafından kullanılıyor.',
          etki: 'Web (8000), Manager (7999) veya ilgili servis başlamaz.',
          oneri: 'Portu kullanan süreci bulun (macOS/Linux: lsof -i :PORT) ve kapatın veya servis portunu değiştirin; ardından yeniden başlatın.'
        };
      }
    },
    {
      test: function (msg) { return /Missing required environment|KeyError:|ValidationError|\.env.*not found/i.test(msg); },
      apply: function () {
        return {
          konu: 'Eksik ayar veya yapılandırma hatası',
          sebep: 'Gerekli ortam değişkeni (.env) veya config alanı eksik veya hatalı.',
          etki: 'Servis başlamaz veya ilgili özellik çalışmaz.',
          oneri: 'Proje kökündeki .env dosyasını ve start script ayarlarını kontrol edin; logdaki eksik alan adını ekleyin.'
        };
      }
    },
    {
      test: function (msg) { return /Killed|OOM|out of memory|MemoryError|exit.*137/i.test(msg); },
      apply: function () {
        return {
          konu: 'Bellek yetersizliği (OOM)',
          sebep: 'Süreç bellek limitini aştı ve işletim sistemi tarafından sonlandırıldı.',
          etki: 'Servis aniden kapanır; bot tick\'leri ve API yanıtları kesilir.',
          oneri: 'RAM kullanımını izleyin; gereksiz süreçleri kapatın; bot sayısını veya log retention ayarlarını düşürün.'
        };
      }
    },
    {
      test: function (msg) { return /429|rate limit|too many requests|IP banned|WAF/i.test(msg); },
      apply: function () {
        return {
          konu: 'Binance / API rate limit',
          sebep: 'Çok sık API isteği gönderildi veya geçici IP/API limitine takıldınız.',
          etki: 'Fiyat, bakiye ve emir istekleri reddedilebilir; bot tick\'leri gecikebilir.',
          oneri: 'İstek sıklığını düşürün; bir süre bekleyin; Binance IP kısıtı varsa sunucu IP\'sini whitelist\'e ekleyin.'
        };
      }
    },
    {
      test: function (msg) { return /\b500\b|Internal Server Error|HTTPException|status_code=500/i.test(msg); },
      apply: function () {
        return {
          konu: 'Sunucu iç hatası (HTTP 500)',
          sebep: 'API isteği işlenirken beklenmeyen sunucu hatası oluştu.',
          etki: 'İlgili sayfa veya endpoint yanıt vermez; kullanıcı işlemi tamamlanmaz.',
          oneri: 'Web/engine loglarında aynı zaman damgasındaki Traceback satırlarını inceleyin; hatayı düzelttikten sonra servisi yeniden başlatın.'
        };
      }
    },
    {
      test: function (msg) { return /CSRF double-submit mismatch/i.test(msg); },
      apply: function (ctx) {
        var m = (ctx.message || ctx.raw || '').match(/path=([^\s]+)/);
        var path = m ? m[1] : '—';
        return {
          konu: 'CSRF token uyuşmazlığı (403)',
          sebep: 'Cookie oturumu var ama istekte X-CSRF-Token başlığı eksik veya csrf_token çerezi ile eşleşmiyor. Yol: ' + path,
          etki: 'POST/PATCH/DELETE isteği reddedildi; ilgili işlem (ayar kaydı, çıkış, hata raporu vb.) tamamlanmadı.',
          oneri: 'Sayfayı tam yenileyin (Cmd+Shift+R), tekrar giriş yapın. AUTH_CSRF_DOUBLE_SUBMIT=1 ise apiClient/errorReporter CSRF başlığı göndermeli; sorun sürerse .env içinde geçici olarak AUTH_CSRF_DOUBLE_SUBMIT=0 deneyin.'
        };
      }
    },
    {
      test: function (msg) { return /CSRF Origin mismatch|CSRF Referer mismatch/i.test(msg); },
      apply: function (ctx) {
        var m = (ctx.message || ctx.raw || '').match(/path=([^\s]+)/);
        var path = m ? m[1] : '—';
        return {
          konu: 'CSRF Origin/Referer engeli (403)',
          sebep: 'İstek kaynağı (Origin/Referer) izinli host listesinde değil. Yol: ' + path,
          etki: 'Tarayıcıdan gelen değiştirici istek reddedildi.',
          oneri: 'Siteye kayıtlı PUBLIC_BASE_URL veya localhost/127.0.0.1 üzerinden erişin; farklı IP/hostname ile açıyorsanız AUTH_CSRF_ALLOWED_ORIGINS veya PUBLIC_BASE_URL güncelleyin.'
        };
      }
    },
    {
      test: function (msg) { return /\b403\b|Forbidden|MANAGER_ALLOW_REMOTE|Erişim engellendi/i.test(msg) && !/CSRF/i.test(msg); },
      apply: function (ctx) {
        var msg = ctx.message || ctx.raw || '';
        if (/IP engellendi/i.test(msg)) {
          return {
            konu: 'IP engellendi (403)',
            sebep: 'İstemci IP adresi Manager güvenlik panelindeki engel listesinde.',
            etki: 'Web API istekleri bu IP\'den reddedilir.',
            oneri: 'Manager → Güvenlik sekmesinden IP engelini kaldırın veya farklı ağdan erişin.'
          };
        }
        if (/spot_order_403|Bu hesaba erişim|FORBIDDEN|ACCOUNT_ISOLATED/i.test(msg)) {
          return {
            konu: 'Hesap veya yetki reddi (403)',
            sebep: 'Oturum bu hesaba veya işleme erişim yetkisine sahip değil.',
            etki: 'İlgili API isteği reddedildi.',
            oneri: 'Doğru hesapla giriş yapın; oturumu yenileyin; admin yetkisi gerekiyorsa admin hesabı kullanın.'
          };
        }
        return {
          konu: 'Erişim engellendi (403)',
          sebep: 'İstek yetkilendirme veya erişim kuralı nedeniyle reddedildi.',
          etki: 'İlgili API veya panel özelliği kullanılamaz.',
          oneri: 'Ham satırdaki path ve request_id ile web.log\'da ayrıntıyı arayın; Manager uzaktan erişim için MANAGER_ALLOW_REMOTE=1 gerekir (yalnızca Manager 7999).'
        };
      }
    },
    {
      test: function (msg) { return RE_HTTP_ACCESS.test(msg) && /\s404\b/.test(msg); },
      apply: function (ctx) {
        var m = ctx.message || ctx.raw || '';
        var hit = m.match(RE_HTTP_ACCESS);
        var method = hit ? hit[1] : 'GET';
        var path = hit ? hit[2] : '—';
        return {
          konu: 'Manager API bulunamadı (404)',
          sebep: method + ' ' + path + ' endpoint\'i yok veya Manager eski sürümle çalışıyor.',
          etki: 'Panel özelliği devre dışı kalır; uyarı Manager loguna düşer.',
          oneri: 'Manager Server\'ı yeniden başlatın: python -m manager_server · ardından Ctrl+Shift+R ile sayfayı yenileyin.'
        };
      }
    },
    {
      test: function (msg) { return /\b404\b|Not Found|NOT_FOUND/i.test(msg); },
      apply: function () {
        return {
          konu: 'Kaynak bulunamadı (404)',
          sebep: 'İstenen API endpoint, bot veya dosya mevcut değil.',
          etki: 'İlgili işlem tamamlanmaz; UI boş veya hata gösterebilir.',
          oneri: 'URL/bot_id/account_id doğru mu kontrol edin; silinmiş bot veya yanlış route olabilir.'
        };
      }
    },
    {
      test: function (msg) { return /FileNotFoundError|No such file or directory/i.test(msg); },
      apply: function () {
        return {
          konu: 'Dosya bulunamadı',
          sebep: 'Kod veya config belirtilen dosya yoluna erişemedi.',
          etki: 'Servis başlamayabilir veya DB/log/config okunamaz.',
          oneri: 'Logdaki dosya yolunun var olduğunu, izinlerin yeterli olduğunu ve çalışma dizininin proje kökü olduğunu doğrulayın.'
        };
      }
    },
    {
      test: function (msg) { return /JSONDecodeError|Expecting value|invalid json/i.test(msg); },
      apply: function () {
        return {
          konu: 'JSON ayrıştırma hatası',
          sebep: 'Beklenen JSON yanıtı bozuk, boş veya geçersiz formatta geldi.',
          etki: 'Config, state veya API yanıtı işlenemez.',
          oneri: 'İlgili dosya veya API yanıtını kontrol edin; bozuk config_json/state kaydını düzeltin.'
        };
      }
    },
    {
      test: function (msg) { return /record_trade failed|Ledger\.|intent_ledger.*fail|BOT_EXECUTION_REPAIR/i.test(msg); },
      apply: function () {
        return {
          konu: 'İşlem kaydı / ledger hatası',
          sebep: 'Emir dolumu veritabanına veya bot ledger\'ına yazılırken hata oluştu.',
          etki: 'UI işlem geçmişi eksik kalabilir; muhasebe/PnL yanlış görünebilir.',
          oneri: 'DB kilidi ve disk alanını kontrol edin; bot state ile Binance emir geçmişini karşılaştırın.'
        };
      }
    },
    {
      test: function (msg) { return /BOT_START_SKIPPED_ALREADY_RUNNING/i.test(msg); },
      apply: function () {
        return {
          konu: 'Bot zaten çalışıyor (yeni döngü açılmadı)',
          sebep: 'START komutu geldi ancak asyncio döngüsü zaten aktifti; bağlantı devamı veya çift START sonrası normal.',
          etki: 'Yok — mevcut bot çalışmaya devam eder.',
          oneri: 'Manager uyarısı değil; gerekirse yok sayın.'
        };
      }
    },
    {
      test: function (msg) {
        return /BOT_LOOP_TRDCA_EXCEPTION|BOT_LOOP_TOPLEVEL_EXCEPTION|BOT_TICK_EXCEPTION|RUN_ACTION_EXCEPTION error_code=/i.test(msg);
      },
      apply: function (ctx) {
        var msg = ctx.message || ctx.raw || '';
        var m = msg.match(/error_id=([0-9a-f-]{36})/i);
        return {
          konu: 'Bot tick hatası emildi — bot çalışmaya devam ediyor',
          sebep: 'Tick veya emir adımında istisna oluştu; worker döngüyü durdurmadı. Detay bot engine logunda (HEALTH_CRITICAL / BOT_RESILIENCE).',
          etki: 'Tek tick atlanmış olabilir; bot durumu running kalır.',
          oneri: (m ? 'error_id=' + m[1] + ' ile ' : '') + 'bot sayfası engine log ve aynı saniyedeki worker.log satırını karşılaştırın.'
        };
      }
    },
    {
      test: function (msg) {
        if (/BOT_START_SKIPPED|lease_not_valid.*skip submit|BOT_TICK_PRICE_MISSING.*skip_trade|WORKER_FIRST_TICK_FAILED|BOT_ACCOUNT_KEYS_FAIL|bot_engine release_symbol_lock|sync_virtual_wallet_from_state failed/i.test(msg)) {
          return false;
        }
        if (/BOT_LOOP_|RUN_ACTION_EXCEPTION|BOT_TICK_EXCEPTION/i.test(msg)) return false;
        return /BOT_TICK|bot_engine loop|BOT_START|BOT_ACCOUNT|BOT_EXECUTION|BOT_STRATEGY/i.test(msg) && /fail|err|error|invalid|skip/i.test(msg);
      },
      apply: function () {
        return {
          konu: 'Bot engine tick / çalışma hatası',
          sebep: 'Bot tick döngüsünde veya bot başlatma/yürütme aşamasında hata loglandı.',
          etki: 'İlgili bot tick\'i atlanabilir; emir üretilmez veya bot duraklatılır.',
          oneri: 'bot_id ve account_id parametrelerini kontrol edin; aynı tick\'teki önceki/sonraki log satırlarına bakın.'
        };
      }
    },
    {
      test: function (msg) { return /leaderboard|LEADERBOARD_REFRESH/i.test(msg) && /fail|err|error/i.test(msg); },
      apply: function () {
        return {
          konu: 'Leaderboard güncelleme hatası',
          sebep: 'En iyi bot listesi (leaderboard) yenilenirken hata oluştu.',
          etki: 'Dashboard sıralama tablosu güncellenmeyebilir veya eski veri gösterilir.',
          oneri: 'DB bağlantısı ve ilgili bot kayıtlarını kontrol edin; web servis loglarında detayı arayın.'
        };
      }
    },
    {
      test: function (msg) { return /IncompleteReadError|ConnectionClosedError|Connection reset|Broken pipe/i.test(msg); },
      apply: function () {
        return {
          konu: 'Bağlantı aniden kapandı',
          sebep: 'Ağ bağlantısı karşı tarafça veya ağ kesintisiyle yarıda kesildi.',
          etki: 'WebSocket veya HTTP isteği tamamlanmamış olabilir; istemci yeniden bağlanır.',
          oneri: 'Geçici ağ sorunuysa bekleyin; sürekli tekrarlıyorsa proxy/firewall ve sunucu timeout ayarlarını inceleyin.'
        };
      }
    },
    {
      test: function (msg) { return /uvicorn|ASGI|Application startup failed|startup failed/i.test(msg); },
      apply: function () {
        return {
          konu: 'Web sunucusu (uvicorn) başlatma hatası',
          sebep: 'FastAPI/uvicorn uygulaması ayağa kalkarken hata oluştu.',
          etki: 'TraderTrailing web API çalışmaz; dashboard erişilemez.',
          oneri: 'Hemen önceki log satırlarındaki import/config/port hatasını düzeltin; web servisini yeniden başlatın.'
        };
      }
    },
    {
      test: function (msg) { return /\[TradeSync\]\s*Symbol cache empty/i.test(msg); },
      apply: function () {
        return {
          konu: 'Finans senkron — sembol listesi yedek modda',
          sebep: 'Piyasa sembol önbelleği henüz dolu değil; bot + yaygın USDT çiftleri ile myTrades çekiliyor.',
          etki: 'İşlem senkronu devam eder; panelde uyarı gerekmez.',
          oneri: 'Yok — beklenen davranış. Önbellek dolunca otomatik genişler.'
        };
      }
    },
    {
      test: function (msg) { return /\[TradeSync\].*429|Binance rate limit for account/i.test(msg); },
      apply: function (ctx) {
        var acct = (ctx.params && ctx.params.account_id) || (ctx.message || '').match(/account\s+(\d+)/i);
        return {
          konu: 'Finans senkron — Binance istek limiti',
          sebep: 'myTrades çekerken Binance 429 (ağırlık limiti) döndü; o ana kadar toplanan işlemler kaydedildi.',
          etki: 'Bu turda kalan semboller atlanmış olabilir; sonraki senkron tamamlar.',
          oneri: acct ? ('Hesap ' + (acct[1] || acct) + ': tekrarlıysa senkron aralığını artırın.') : 'Tekrarlıysa senkron sıklığını azaltın.'
        };
      }
    },
    {
      test: function (msg) { return /\[TradeSync\].*Invalid API-key|401\/-2015/i.test(msg); },
      apply: function () {
        return {
          konu: 'Finans senkron — API anahtarı geçersiz',
          sebep: 'Binance myTrades bu hesap için 401 veya -2015 (yetki/IP) döndü.',
          etki: 'Bu hesabın işlem geçmişi senkron edilmez.',
          oneri: 'Hesap API anahtarını ve IP kısıtını kontrol edin.'
        };
      }
    },
    {
      test: function (msg) { return /CYCLE_LEDGER fee_asset=.*could not convert to USDT/i.test(msg); },
      apply: function (ctx) {
        var m = (ctx.message || ctx.raw || '').match(/fee_asset=(\w+).*amount=([\d.]+)/i);
        var asset = m ? m[1] : '—';
        var amt = m ? m[2] : '';
        return {
          konu: 'Tur defteri — komisyon USDT\'ye çevrilemedi',
          sebep: 'Binance komisyonu ' + asset + (amt ? ' (' + amt + ')' : '') + ' olarak geldi; USDT fiyatı bulunamadığı için tur K/Z komisyonu 0 yazıldı.',
          etki: 'Tur kar/zarar hesabında komisyon eksik kalabilir.',
          oneri: 'Sembol fiyat önbelleğinin (price hub) çalıştığını doğrulayın; tekrarlıysa worker.log içinde aynı zaman damgasını inceleyin.'
        };
      }
    },
    {
      test: function (msg) { return /deque mutated during iteration/i.test(msg); },
      apply: function () {
        return {
          konu: 'Yönetici paneli — eski log ring uyarısı (gürültü)',
          sebep: 'Log halkası okunurken eşzamanlı yazma (eski sürüm). Güncel kodda kilit var; panel bu satırı artık listelemez.',
          etki: 'Yok — servisler etkilenmez.',
          oneri: 'Yok. Manager yeniden başlatılırsa halka temizlenir.'
        };
      }
    },
    {
      test: function (msg) { return /bots_delete skip convert \(test\/paper account\)/i.test(msg); },
      apply: function (ctx) {
        var bid = (ctx.params && ctx.params.bot_id) || (ctx.message || '').match(/bot_id=(\d+)/i);
        bid = bid ? (bid[1] || bid) : '—';
        return {
          konu: 'Bot silme — test hesabı (dönüştürme yok)',
          sebep: 'Test/paper hesabında Binance\'e base satışı yapılmaz; bot doğrudan silinir.',
          etki: 'Sanal bakiye değişmez; bot kaydı ve state temizlenir.',
          oneri: 'Beklenen davranış — ek işlem gerekmez.'
        };
      }
    },
    {
      test: function (msg) { return /bots_delete convert skip bot_id=/i.test(msg); },
      apply: function (ctx) {
        var m = (ctx.message || '').match(/symbol=(\S+).*notional=([\d.]+).*min=([\d.]+)/i);
        return {
          konu: 'Bot silme — base USDT\'ye çevrilmedi (min tutar)',
          sebep: m
            ? (m[1] + ' bakiyesi minimum işlem tutarının (' + m[3] + ' USDT) altında (' + m[2] + ' USDT).')
            : 'Kalan coin tutarı borsa minimum notional altında.',
          etki: 'Coin hesapta kalır; bot yine de silinir.',
          oneri: 'Küçük bakiyeyi manuel kapatabilir veya «bakiye olduğu gibi kalsın» ile silin.'
        };
      }
    },
    {
      test: function (msg) { return /bots_delete convert_base_to_quote.*failed bot_id=/i.test(msg); },
      apply: function (ctx) {
        var msg = ctx.message || ctx.raw || '';
        var bid = (ctx.params && ctx.params.bot_id) || (msg.match(/bot_id=(\d+)/i) || [])[1] || '—';
        var detail = technicalDetail(ctx);
        var workerOnly = /only allowed on worker|web\/api cannot place/i.test(detail);
        var noKeys = /api anahtar/i.test(detail);
        return {
          konu: 'Bot silme — base → USDT dönüşümü başarısız',
          sebep: workerOnly
            ? 'Piyasa satışı yalnızca bot worker sürecinde yapılabilir; web silme isteği convert denedi.'
            : (noKeys
              ? 'Hesapta Binance API anahtarı yok (test/paper hesap olabilir).'
              : ('Dönüştürme hatası: ' + detail.slice(0, 180))),
          etki: workerOnly || noKeys
            ? 'Uyarı kaydedildi; bot silme işlemi genelde devam eder.'
            : 'Bot silinmemiş olabilir; kullanıcıya hata dönmüş olabilir.',
          oneri: workerOnly || noKeys
            ? 'Test hesabında «bakiye olduğu gibi kalsın» ile silin veya canlı hesapta worker çalıştığından emin olun.'
            : 'API anahtarı, bakiye ve sembolü kontrol edin; gerekirse convert olmadan silin.'
        };
      }
    },
    {
      test: function (msg) { return /bots_delete convert cancel_order|bots_delete convert list_orders/i.test(msg); },
      apply: function (ctx) {
        var sym = (ctx.params && ctx.params.symbol) || (ctx.message || '').match(/symbol=(\S+)/i);
        sym = sym ? (sym[1] || sym) : '—';
        return {
          konu: 'Bot silme — açık emir iptali uyarısı',
          sebep: sym + ' için silme öncesi emir iptali veya emir listesi alınamadı: ' + technicalDetail(ctx).slice(0, 160),
          etki: 'Dönüştürme veya silme kısmen gecikebilir; bot silme süreci devam edebilir.',
          oneri: 'Binance’te manuel açık emir var mı bakın; tekrarlıysa API erişimini kontrol edin.'
        };
      }
    },
    {
      test: function (msg) { return /delete_bot_fully archive bot_id=/i.test(msg); },
      apply: function (ctx) {
        var bid = (ctx.params && ctx.params.bot_id) || (ctx.message || '').match(/bot_id=(\d+)/i);
        bid = bid ? (bid[1] || bid) : '—';
        return {
          konu: 'Bot silme — performans arşivi yazılamadı',
          sebep: 'Bot silinirken günlük performans arşivi güncellenemedi: ' + technicalDetail(ctx).slice(0, 160),
          etki: 'Bot ve state silinir; performans dosyası eksik kalabilir.',
          oneri: 'Tek seferlik uyarıysa yok sayılabilir. Tekrarlıysa disk izinleri ve .run/bot_cycles yolunu kontrol edin.'
        };
      }
    },
    {
      test: function (msg) { return /Spot quick_data error for/i.test(msg); },
      apply: function (ctx) {
        var m = (ctx.message || ctx.raw || '').match(/Spot quick_data error for\s+(\S+):\s*(.+)$/i);
        var sym = m ? m[1] : (ctx.params.symbol || '—');
        var detail = m ? m[2].trim() : technicalDetail(ctx);
        var transient = /timeout|timed out|ConnectError|Connection refused|circuit breaker|retry budget|nodename nor servname/i.test(detail);
        return {
          konu: 'Al/Sat modal verisi alınamadı',
          sebep: sym + ' için quick_data (fiyat, filtre, bakiye) hatası: ' + detail.slice(0, 200),
          etki: 'Modal sıfırlı/varsayılan değer döner; sayfa veya modal yenilenince tekrar denenir.',
          oneri: transient
            ? 'Geçici ağ veya Binance erişim sorunu; birkaç dakika bekleyin. Sürekli tekrarlıyorsa API anahtarı ve IP whitelist kontrol edin.'
            : 'Hesap API anahtarı, Binance bağlantısı ve sembol adını kontrol edin; aynı anda binance_spot uyarıları varsa onlara bakın.'
        };
      }
    },
    {
      test: function (msg) { return /get_quick_data error for/i.test(msg); },
      apply: function (ctx) {
        var m = (ctx.message || ctx.raw || '').match(/get_quick_data error for\s+(\S+):\s*(.+)$/i);
        var sym = m ? m[1] : '—';
        var detail = m ? m[2].trim() : technicalDetail(ctx);
        return {
          konu: 'Spot engine — quick_data hatası',
          sebep: sym + ' için iç spot veri toplama başarısız: ' + detail.slice(0, 200),
          etki: 'Fiyat veya bakiye 0 gösterilebilir; spot_routes varsayılan yanıt döner.',
          oneri: 'Binance public/signed erişimini ve hesap anahtarlarını kontrol edin; geçici ağ hatasıysa kısa süre sonra düzelir.'
        };
      }
    },
    {
      test: function (msg) { return /spot_order_403/i.test(msg); },
      apply: function (ctx) {
        var p = ctx.params || {};
        var acct = p.account_id || '—';
        return {
          konu: 'Spot emir — hesap erişimi reddedildi (403)',
          sebep: 'Oturumdaki kullanıcı account_id=' + acct + ' hesabına spot emir gönderemiyor (yetki veya hesap uyuşmazlığı).',
          etki: 'Emir borsaya iletilmedi.',
          oneri: 'Doğru hesapla giriş yaptığınızı doğrulayın; oturumu yenileyin (çıkış/giriş); paylaşımlı hesap ve admin yetkilerini kontrol edin.'
        };
      }
    },
    {
      test: function (msg) { return /Spot order validation error/i.test(msg); },
      apply: function (ctx) {
        var detail = technicalDetail(ctx);
        return {
          konu: 'Spot emir doğrulama hatası',
          sebep: 'Gönderilen emir parametreleri geçersiz: ' + (detail ? detail.slice(0, 160) : 'doğrulama kuralı ihlali'),
          etki: 'Emir borsaya iletilmedi.',
          oneri: 'Minimum tutar (notional), lot/step size ve kullanılabilir bakiyeyi kontrol edin; miktarı düzeltip tekrar deneyin.'
        };
      }
    },
    {
      test: function (msg) { return /ValueError|TypeError|AttributeError|KeyError|IndexError|RuntimeError/i.test(msg); },
      apply: function (ctx) {
        var msg = ctx.message || ctx.raw || '';
        var m = msg.match(/(\w+Error|\w+Exception)/);
        return {
          konu: 'Python program hatası' + (m ? ' (' + m[1] + ')' : ''),
          sebep: 'Kod çalışırken beklenmeyen Python istisnası oluştu.',
          etki: 'İlgili istek, bot tick\'i veya servis işlemi başarısız olmuş olabilir.',
          oneri: 'Traceback devamını ana log akışında okuyun; belirtilen dosya ve satır numarasına göre düzeltin.'
        };
      }
    },
    {
      test: function (msg) { return /Unhandled exception:/i.test(msg); },
      apply: function (ctx) {
        var detail = technicalDetail(ctx);
        var msg = ctx.message || ctx.raw || '';
        if (/cannot import name '_fetch_server_public_ip'/.test(msg)) {
          return {
            konu: 'Bağlantı kontrolü API hatası (import)',
            sebep: 'GET /api/home/connectivity-check, app.api.routes paketi _fetch_server_public_ip dışa aktarmıyordu.',
            etki: 'Dashboard bağlantı testi ve ilgili istekler HTTP 500 döner.',
            oneri: 'routes/__init__.py içinde _fetch_server_public_ip export edildi; Web API yeniden başlatın.'
          };
        }
        if (/referenced before assignment/.test(msg) && /get_bot_locked_balances/.test(msg)) {
          return {
            konu: 'Spot quick_data kod hatası',
            sebep: 'Al/Sat modal verisi: get_bot_locked_balances_for_account yerel import çakışması (düzeltildi).',
            etki: 'ETHUSDT vb. için fiyat/bakiye quick_data boş veya hatalı dönebilirdi.',
            oneri: 'Web API yeniden başlatın; tekrarlıyorsa spot_routes.py güncel sürümde mi kontrol edin.'
          };
        }
        return {
          konu: 'İşlenmeyen HTTP isteği hatası (500)',
          sebep: 'FastAPI yakalanmamış istisna: ' + (detail ? detail.slice(0, 220) : 'detay Ham satırda'),
          etki: 'İstek 500 döner; kullanıcı işlemi tamamlanmamış olabilir. Aynı hata error_logs tablosuna da yazılır.',
          oneri: 'Ham satırdan hemen sonra gelen Traceback satırlarını web.log içinde okuyun; path ve request_id ile tekrarlayın.'
        };
      }
    },
    {
      test: function (msg, ctx) {
        if (/dashboard_sse tick error/i.test(msg)) return true;
        return !!(ctx && ctx.module === 'app.api.dashboard_stream');
      },
      apply: function (ctx) {
        var detail = technicalDetail(ctx);
        var msg = ctx.message || ctx.raw || '';
        var isImport = /ImportError|cannot import name/i.test(detail || msg);
        return {
          konu: 'Dashboard SSE anlık güncelleme hatası',
          sebep: isImport
            ? 'SSE tick içinde snapshot yardımcı modülü yüklenemedi; routes export düzeltmesi sonrası Web API yeniden başlatılmalı.'
            : (/dashboard_sse tick error/i.test(msg)
                ? ('Dashboard SSE tick başarısız: ' + (detail ? detail.slice(0, 200) : 'veritabanı veya snapshot okuma hatası'))
                : 'Dashboard SSE kanalında uyarı (cüzdan/snapshot okuma); tick atlandı, akış devam eder.'),
          etki: 'Dashboard canlı akışı o tick için atlanır; tarayıcı snapshot/yenileme ile devam eder. Cüzdan rozeti «Güncel değil» geçici kalabilir.',
          oneri: isImport
            ? 'stop.command → start.command ile Web API yeniden başlatın.'
            : 'Sayfayı yenileyin; Ayarlar → Binance bağlantı testi. Tek seferlik ise yok sayın.'
        };
      }
    },
    {
      test: function (msg) { return /\[BinanceWS\]\s*Açılış el sıkışması zaman aşımı/i.test(msg); },
      apply: function () {
        return {
          konu: 'Binance WebSocket bağlantı gecikmesi',
          sebep: 'Canlı fiyat akışı (!miniTicker) açılış el sıkışması zaman aşımına uğradı (ağ/firewall yavaş).',
          etki: 'DataHub REST/cache ile devam eder; WS birkaç dakikada bir kez uyarı verip yeniden bağlanır.',
          oneri: 'Sunucu çıkış IP ve firewall; sürekli tekrarlıyorsa Binance erişimini test edin. Genelde geçicidir.'
        };
      }
    },
    {
      test: function (msg) { return /\[BinanceWS\]\s*Ağ\/DNS erişilemiyor/i.test(msg); },
      apply: function () {
        return {
          konu: 'Binance WebSocket DNS / ağ hatası',
          sebep: 'stream.binance.com çözülemedi veya ağ erişilemiyor (offline/DNS).',
          etki: 'Canlı mini ticker akışı kesilir; REST fiyat güncellemesi devreye girer.',
          oneri: 'Sunucu internet/DNS; birkaç dakika sonra otomatik yeniden deneme. Sürekli ise ağ yöneticisine bildirin.'
        };
      }
    },
    {
      test: function (msg) {
        return /Binance WebSocket (bağlantı koptu|beklenmedik kapanma)/i.test(msg)
          || (/\[BinanceWS\]\s*Connection closed/i.test(msg) && !/keepalive ping timeout/i.test(msg));
      },
      apply: function (ctx) {
        var detail = technicalDetail(ctx);
        return {
          konu: 'Binance WebSocket bağlantısı koptu',
          sebep: detail || 'WS bağlantısı beklenmedik kapandı; istemci yeniden bağlanıyor.',
          etki: 'Kısa süre canlı fiyat gecikmesi; otomatik reconnect.',
          oneri: 'Tek seferlik ise yok sayın. Sık tekrarlıyorsa ağ stabilitesi ve Binance durumunu kontrol edin.'
        };
      }
    },
    {
      test: function (msg) { return /\[BinanceWS\]\s*Reconnecting in/i.test(msg); },
      apply: function () {
        return {
          konu: 'Binance WebSocket yeniden bağlanıyor',
          sebep: 'Önceki WS oturumu kapandı; üstel geri çekilme ile yeniden bağlantı planlandı.',
          etki: 'Bilgi seviyesi; canlı fiyat birkaç saniye gecikebilir.',
          oneri: 'Hata panelinde değil, ana logda kalabilir. Sürekli döngü varsa ağ/Binance erişimini inceleyin.'
        };
      }
    },
    {
      test: function (msg) { return /\[BinanceWS\]/i.test(msg); },
      apply: function (ctx) {
        var detail = technicalDetail(ctx);
        return {
          konu: 'Binance canlı fiyat WebSocket uyarısı',
          sebep: detail || 'miniTicker WebSocket döngüsünde geçici hata; yeniden bağlanma sürüyor.',
          etki: 'Emir gönderimini doğrudan etkilemez; dashboard fiyatları REST/cache ile sürebilir.',
          oneri: 'Ham satırdaki hata metnini okuyun. Emir reddi değilse Binance API anahtarı gerekmez (public stream).'
        };
      }
    },
    // USER_STREAM handler — genel Binance handler'ından ÖNCE gelmeli
    {
      test: function (msg) {
        return /user_stream|USER_STREAM/i.test(msg);
      },
      apply: function (ctx) {
        var detail = technicalDetail(ctx) || '';
        var _msg = ctx.message || ctx.raw || '';
        var is410 = /410|Gone|listenKey/i.test(detail) || /410|Gone/i.test(_msg);
        var isConnected = /USER_STREAM_CONNECTED/i.test(_msg);
        var isKeyExpired = /USER_STREAM_KEY_EXPIRED|listenKey/i.test(_msg);
        var isReconnect = /USER_STREAM_RECONNECT/i.test(_msg);

        if (isConnected) {
          return {
            konu: 'Binance veri akışı bağlandı',
            sebep: 'Hesap user data stream başarıyla açıldı; ORDER_TRADE_UPDATE eventleri alınıyor.',
            etki: 'Emir doldurma bildirimleri artık gerçek zamanlı.',
            oneri: 'İşlem gerekmez.'
          };
        }
        if (isKeyExpired || (is410 && isReconnect)) {
          return {
            konu: 'Binance veri akışı yeniden bağlanıyor',
            sebep: 'listenKey süresi doldu (Binance 410). Sistem otomatik olarak yeni anahtar alıp yeniden bağlanıyor.',
            etki: 'Yeniden bağlanma sırasında (~5 sn) ORDER_TRADE_UPDATE eventleri alınamaz; bot REST reconcile ile telafi eder.',
            oneri: 'Otomatik işlem; müdahale gerekmez. Sorun devam ederse API anahtarı izinlerini kontrol edin.'
          };
        }
        if (is410) {
          return {
            konu: 'Binance veri akışı kesintisi (410)',
            sebep: 'Binance user data stream listenKey geçersiz oldu (410 Gone). Sistem yeniden bağlanıyor.',
            etki: 'Kısa süreliğine ORDER_TRADE_UPDATE eventleri alınamaz; bot otomatik telafi eder.',
            oneri: 'Otomatik yeniden bağlanma başladı. Sorun sürekli tekrarlanıyorsa API anahtarı süresi ve izinleri kontrol edin.'
          };
        }
        return {
          konu: 'Binance veri akışı bağlantı sorunu',
          sebep: 'User data stream geçici olarak bağlantısını kesti; bot otomatik yeniden bağlanacak.',
          etki: 'Geçici: yeniden bağlanana kadar anlık emir dolum bildirimleri REST polling ile sağlanır.',
          oneri: 'Birkaç saniye bekleyin. Tekrar bağlandığında USER_STREAM_CONNECTED logu görünür.'
        };
      }
    },
    {
      test: function (msg) {
        if (/\[BinanceWS\]|binance_ws|user_stream|USER_STREAM/i.test(msg)) return false;
        return /Binance|binance_spot|APIError|-\d{4}\s|MIN_NOTIONAL|LOT_SIZE|insufficient balance|Account has insufficient/i.test(msg);
      },
      apply: function () {
        return {
          konu: 'Binance API / emir hatası',
          sebep: 'Binance borsası isteği reddetti (miktar, notional, bakiye veya sembol kuralı).',
          etki: 'Emir gönderilmez veya kısmen dolabilir; bot stratejisi bu tick\'te işlem yapmaz.',
          oneri: 'Teknik detaydaki Binance hata kodunu kontrol edin; min notional, step size ve hesap bakiyesini doğrulayın.'
        };
      }
    }
  ];

  function technicalDetail(ctx) {
    if (ctx.params.err) return ctx.params.err;
    var msg = ctx.message || ctx.raw;
    var http = msg.match(RE_HTTP_ACCESS);
    if (http) return http[1] + ' ' + http[2] + ' → ' + http[3];
    var colon = msg.indexOf(':');
    if (colon >= 0 && colon < msg.length - 1) {
      var tail = msg.slice(colon + 1).trim();
      if (tail.length > 10 && !/^\d{2}:\d{2}/.test(tail)) return tail;
    }
    return msg;
  }

  function moduleLabel(module) {
    if (!module) return null;
    return MODULE_LABELS[module] || null;
  }

  function genericFallback(ctx) {
    var level = ctx.level ? String(ctx.level).toUpperCase() : '';
    var isErr = level
      ? (level === 'ERROR' || level === 'CRITICAL')
      : (/ERROR|CRITICAL|Traceback/i.test(ctx.raw) && !/WARNING/i.test(ctx.raw));
    var mod = ctx.module || '';
    var msg = ctx.message || ctx.raw || '';
    var konu = isErr ? 'Sistem hatası' : 'Sistem uyarısı';
    if (/app\.botengine\.execution/i.test(mod)) {
      konu = isErr ? 'Bot emir yürütme hatası' : 'Bot emir yürütme uyarısı';
    } else if (/app\.api\.spot_routes/i.test(mod)) {
      konu = isErr ? 'Spot API hatası' : 'Spot API uyarısı';
    } else if (/binance_spot|binance_adapter/i.test(mod)) {
      konu = 'Binance API uyarısı';
    } else if (/bots_engine/i.test(mod)) {
      konu = isErr ? 'Bot API hatası' : 'Bot API uyarısı';
    } else if (/botengine/i.test(mod)) {
      konu = isErr ? 'Bot engine hatası' : 'Bot engine uyarısı';
    } else if (/app\.api\.routes\.home|routes\.home/i.test(mod)) {
      konu = isErr ? 'Anasayfa cüzdan API hatası' : 'Anasayfa cüzdan uyarısı';
    } else if (/app\.api\.dashboard_stream/i.test(mod)) {
      konu = isErr ? 'Dashboard SSE akış hatası' : 'Dashboard SSE uyarısı';
    } else if (/app\.api\._routes_impl|app\.api\.routes/i.test(mod)) {
      konu = isErr ? 'Web API hatası' : 'Web API uyarısı';
    } else if (mod === 'root') {
      konu = isErr ? 'Web uygulaması (main) hatası' : 'Web uygulaması (main) uyarısı';
    } else if (/app\.middleware\.csrf/i.test(mod)) {
      konu = isErr ? 'CSRF güvenlik hatası' : 'CSRF güvenlik uyarısı';
    }
    var sebep = 'Bu log satırı için özel Türkçe şablon yok; tam kaynak metin en altta (Ham satır).';
    if (/app\.middleware\.csrf/i.test(mod)) {
      sebep = 'Çerez oturumlu istek CSRF korumasından geçemedi (token veya Origin/Referer).';
    } else if (/main\.py:\d+.*Unhandled exception/i.test(msg)) {
      sebep = 'Yakalanmamış istisna (HTTP 500); Traceback satırları web.log akışında bu satırdan hemen sonra gelir.';
    } else if (/LEADERBOARD_REFRESH_FAIL/i.test(msg)) {
      sebep = 'En iyi botlar listesi arka plan yenilemesi başarısız oldu.';
    } else if (/Lockdown:\s*blocking path/i.test(msg)) {
      sebep = 'Bakım kilidi açık; istek beyaz listede olmayan bir yola gitti.';
    } else if (/global_exception_handler|persist_error|error_log middleware/i.test(msg)) {
      sebep = 'Hata kaydı veya global exception işleyicisi ile ilgili kayıt.';
    } else if (/Traceback \(most recent call last\)/i.test(msg)) {
      sebep = 'Python Traceback başlığı; asıl hata tipi bir sonraki satırlarda.';
    }
    if (/wallet_refresh|home_wallet_refresh|home_fast/i.test(msg)) {
      sebep = 'Anasayfa canlı cüzdan yenilemesi (Binance) ile ilgili kayıt; çoğunlukla IP beyaz liste, API anahtarı veya ağ kesintisi.';
    }
    if (/bots_delete|delete_bot_fully/i.test(msg)) {
      sebep = 'Bot silme veya silme öncesi dönüştürme aşamasında uyarı kaydedildi.';
    }
    if (/BOT_EXECUTION|run_actions|EXEC_ORDER/i.test(msg)) {
      sebep = 'Bot emir yürütme aşamasında uyarı veya hata kaydedildi.';
    } else if (/binance_spot|BINANCE_/i.test(msg)) {
      sebep = 'Binance API çağrısı sırasında uyarı kaydedildi.';
    }
    return {
      konu: konu,
      sebep: sebep,
      etki: isErr ? 'İlgili işlem başarısız olmuş olabilir.' : 'İşlem devam edebilir; bot davranışını izleyin.',
      oneri: 'Tekrarlıyorsa bot engine worker.log dosyasında aynı zaman damgasını arayın.',
      _isGenericFallback: true
    };
  }

  function rawLogLine(ctx) {
    return String(ctx.raw || ctx.message || '').trim() || '—';
  }

  function buildBlock(ctx, tr, serviceKey) {
    var lines = [];
    var isFallback = tr && tr._isGenericFallback === true;
    lines.push('Konu: ' + (tr.konu || '—'));
    if (ctx.timestamp) lines.push('Tarih: ' + formatTsTr(ctx.timestamp));
    if (serviceKey && SERVICE_LABELS[serviceKey]) lines.push('Servis: ' + SERVICE_LABELS[serviceKey]);
    if (ctx.module) {
      var modLbl = moduleLabel(ctx.module);
      lines.push('Modül: ' + (modLbl ? modLbl + ' (' + ctx.module + ')' : ctx.module));
    }
    if (ctx.level) lines.push('Seviye: ' + levelTr(ctx.level));
    lines.push('Sebep: ' + (tr.sebep || '—'));
    if (tr.etki) lines.push('Etki: ' + tr.etki);
    var paramKeys = Object.keys(ctx.params || {});
    if (paramKeys.length) {
      var paramParts = paramKeys.map(function (k) {
        if (k === 'err') return null;
        return k + '=' + ctx.params[k];
      }).filter(Boolean);
      if (paramParts.length) lines.push('Parametreler: ' + paramParts.join(', '));
    }
    if (!isFallback) {
      var tech = technicalDetail(ctx);
      if (tech) lines.push('Teknik detay: ' + tech);
    }
    if (tr.oneri) lines.push('Ne yapmalı: ' + tr.oneri);
    lines.push('Ham satır: ' + rawLogLine(ctx));
    return lines.join('\n');
  }

  function extractHamLine(raw) {
    var m = String(raw || '').match(/(?:^|\n)Ham satır:\s*(.+)$/m);
    return m ? m[1].trim() : null;
  }

  function humanize(rawLine, serviceKey) {
    var ham = extractHamLine(rawLine);
    if (ham) rawLine = ham;
    var ctx = parseLine(rawLine);
    var msg = ctx.message || ctx.raw;
    var tr = null;
    for (var i = 0; i < RULES.length; i++) {
      if (RULES[i].test(msg, ctx) || RULES[i].test(ctx.raw)) {
        tr = RULES[i].apply(ctx);
        break;
      }
    }
    if (!tr) tr = genericFallback(ctx);
    return buildBlock(ctx, tr, serviceKey);
  }

  function formatLine(rawLine, serviceKey) {
    if (!rawLine || typeof rawLine !== 'string') {
      rawLine = rawLine == null ? '' : String(rawLine);
    }
    var trimmed = rawLine.trim();
    if (!trimmed) return '';
    return humanize(trimmed, serviceKey);
  }

  function formatLogEntry(entry, serviceKey) {
    if (typeof entry === 'string') return formatLine(entry, serviceKey);
    var ts = (entry && entry.ts) || '';
    var text = (entry && (entry.text || entry.line)) || '';
    if (typeof entry === 'object' && !text && entry.message) text = entry.message;
    var combined = (ts ? ts + ' ' : '') + (text || '').trim();
    if (!combined.trim()) return formatLine(String(entry), serviceKey);
    return formatLine(combined, serviceKey);
  }

  function formatLines(entries, serviceKey) {
    return (entries || []).map(function (e) { return formatLogEntry(e, serviceKey); }).filter(Boolean);
  }

  global.LogHumanize = {
    format: formatLine,
    formatEntry: formatLogEntry,
    formatLines: formatLines,
    humanize: humanize
  };
})(typeof window !== 'undefined' ? window : globalThis);
