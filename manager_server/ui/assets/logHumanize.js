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
    'app.services.finance_trade_sync': 'Finans işlem senkronu',
    'app.botengine.adapters.binance_adapter': 'Binance adapter',
    'app.botengine.health_watch': 'Bot sağlık izleme',
    'app.botengine.intent_ledger': 'Emir intent defteri',
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
      test: function (msg) { return /binance_spot public_get/i.test(msg); },
      apply: function () {
        return {
          konu: 'Binance genel API isteği başarısız',
          sebep: 'Fiyat, exchangeInfo veya sunucu saati gibi imzasız Binance isteği hata aldı; yeniden deneme yapılıyor olabilir.',
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
      test: function (msg) { return /\b403\b|Forbidden|MANAGER_ALLOW_REMOTE|Erişim engellendi/i.test(msg); },
      apply: function () {
        return {
          konu: 'Erişim engellendi (403)',
          sebep: 'İstek yetkilendirme veya uzaktan erişim kuralı nedeniyle reddedildi.',
          etki: 'Manager paneli veya API uzaktan erişilemez; localhost dışından bağlantı kopar.',
          oneri: 'Manager için MANAGER_ALLOW_REMOTE=1 ile başlatın veya localhost/VPN üzerinden erişin; API token/cookie kontrol edin.'
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
      test: function (msg) { return /BOT_TICK|bot_engine loop|BOT_START|BOT_ACCOUNT|BOT_EXECUTION|BOT_STRATEGY/i.test(msg) && /fail|err|error|invalid|skip/i.test(msg); },
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
      test: function (msg) { return /Binance|binance_spot|APIError|-\d{4}\s|MIN_NOTIONAL|LOT_SIZE|insufficient balance|Account has insufficient/i.test(msg); },
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
    var isErr = /ERROR|CRITICAL|Exception|Traceback/i.test(ctx.raw);
    var mod = ctx.module || '';
    var msg = ctx.message || ctx.raw || '';
    var konu = isErr ? 'Sistem hatası' : 'Sistem uyarısı';
    if (/app\.botengine\.execution/i.test(mod)) {
      konu = isErr ? 'Bot emir yürütme hatası' : 'Bot emir yürütme uyarısı';
    } else if (/binance_spot|binance_adapter/i.test(mod)) {
      konu = 'Binance API uyarısı';
    } else if (/botengine/i.test(mod)) {
      konu = isErr ? 'Bot engine hatası' : 'Bot engine uyarısı';
    }
    var sebep = 'Bu log satırı için özel Türkçe şablon yok; tam kaynak metin en altta (Ham satır).';
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

  function alreadyHumanized(raw) {
    return /^\s*Konu:\s/m.test(String(raw || ''));
  }

  function humanize(rawLine, serviceKey) {
    if (alreadyHumanized(rawLine)) return String(rawLine).trim();
    var ctx = parseLine(rawLine);
    var msg = ctx.message || ctx.raw;
    var tr = null;
    for (var i = 0; i < RULES.length; i++) {
      if (RULES[i].test(msg) || RULES[i].test(ctx.raw)) {
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
