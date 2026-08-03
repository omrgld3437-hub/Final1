import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { dirname, extname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const projectDir = resolve(scriptDir, "..");
const buildDir = process.env.V2_BUILD_DIR
  ? resolve(projectDir, process.env.V2_BUILD_DIR)
  : resolve(projectDir, "../assets/v2/dashboard");
const sharedPwaDir = resolve(projectDir, "../assets/pwa");
const publicDir = resolve(projectDir, "public");
const publicBase = "/ui/assets/v2/dashboard/";
const sourceDir = resolve(projectDir, "src");

const budgets = Object.freeze({
  htmlGzipBytes: 20 * 1024,
  initialJsGzipBytes: 180 * 1024,
  initialCssGzipBytes: 35 * 1024,
  initialAssetRequests: 8,
});

function read(path) {
  return readFileSync(path, "utf8");
}

function gzipBytes(path) {
  return gzipSync(readFileSync(path), { level: 9 }).byteLength;
}

function walk(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    return entry.isDirectory() ? walk(path) : [path];
  });
}

function buildPathFromUrl(url) {
  const parsed = new URL(url, "https://ayserose.invalid");
  assert.equal(parsed.origin, "https://ayserose.invalid", `Harici build asset'i yasak: ${url}`);
  assert.ok(
    parsed.pathname.startsWith(publicBase),
    `Asset V2 public base dışında: ${parsed.pathname}`,
  );
  return resolve(buildDir, parsed.pathname.slice(publicBase.length));
}

assert.ok(existsSync(buildDir), `Build dizini bulunamadı: ${buildDir}`);

const indexPath = join(buildDir, "index.html");
const manifestPath = join(buildDir, "manifest.webmanifest");
const swPath = join(buildDir, "sw.js");
const registerSourcePath = join(projectDir, "scripts/register-sw.js");

for (const path of [indexPath, manifestPath, swPath]) {
  assert.ok(existsSync(path), `Zorunlu build dosyası eksik: ${relative(buildDir, path)}`);
}
assert.ok(existsSync(registerSourcePath), "Service worker kayıt kaynağı eksik.");

const html = read(indexPath);
assert.ok(!html.includes("/ui/dist/dashboard/"), "Eski ve sunulmayan /ui/dist/dashboard yolu bulundu.");
assert.ok(html.includes(`${publicBase}manifest.webmanifest`), "V2 manifest bağlantısı eksik.");
assert.ok(
  html.includes("/ui/assets/pwa/ayserose-plain-v4-180.png"),
  "Sürümlü Ayserose Apple touch ikonu eksik.",
);
assert.ok(!/https:\/\/fonts\.(?:googleapis|gstatic)\.com/i.test(html), "CSP dışı Google font kaynağı bulundu.");

const assetUrls = [
  ...html.matchAll(/<(?:script|link)\b[^>]+?(?:src|href)="([^"]+)"/g),
]
  .map((match) => match[1])
  .filter((url) => url.startsWith(publicBase) && /\.(?:js|css)(?:\?|$)/.test(url));

assert.ok(assetUrls.length > 0, "Build giriş dosyasında JS/CSS asset bulunamadı.");
assert.ok(assetUrls.length <= budgets.initialAssetRequests, "İlk asset istek sayısı bütçeyi aşıyor.");

const initialAssets = assetUrls.map((url) => {
  const path = buildPathFromUrl(url);
  assert.ok(existsSync(path), `HTML'in referans verdiği asset eksik: ${url}`);
  return path;
});

const jsGzip = initialAssets
  .filter((path) => extname(path) === ".js")
  .reduce((sum, path) => sum + gzipBytes(path), 0);
const cssGzip = initialAssets
  .filter((path) => extname(path) === ".css")
  .reduce((sum, path) => sum + gzipBytes(path), 0);
const htmlGzip = gzipBytes(indexPath);
const initialJsSource = initialAssets
  .filter((path) => extname(path) === ".js")
  .map(read)
  .join("\n");

assert.ok(
  initialJsSource.includes("serviceWorker.register") && initialJsSource.includes("sw.js"),
  "Service worker kayıt kodu ilk JS grafiğine dahil değil.",
);

assert.ok(
  jsGzip <= budgets.initialJsGzipBytes,
  `İlk JS gzip bütçesi aşıldı: ${jsGzip} > ${budgets.initialJsGzipBytes}`,
);
assert.ok(
  cssGzip <= budgets.initialCssGzipBytes,
  `İlk CSS gzip bütçesi aşıldı: ${cssGzip} > ${budgets.initialCssGzipBytes}`,
);
assert.ok(
  htmlGzip <= budgets.htmlGzipBytes,
  `HTML gzip bütçesi aşıldı: ${htmlGzip} > ${budgets.htmlGzipBytes}`,
);

const allBuildFiles = walk(buildDir);
assert.equal(
  allBuildFiles.some((path) => path.endsWith(".map")),
  false,
  "Production source map yayınlanmamalı.",
);

const hashedAssets = allBuildFiles.filter((path) => path.includes(`${join(buildDir, "assets")}/`));
for (const path of hashedAssets) {
  assert.match(
    relative(buildDir, path),
    /^assets\/.+-[A-Za-z0-9_-]{8,}\.[a-z0-9]+$/i,
    `Immutable asset hash taşımıyor: ${relative(buildDir, path)}`,
  );
}

const manifest = JSON.parse(read(manifestPath));
assert.equal(manifest.id, "/ui/dashboard.html");
assert.ok(
  String(manifest.start_url).startsWith(`${publicBase}index.html`),
  "PWA başlangıcı service worker kapsamındaki V2 index olmalı.",
);
assert.equal(manifest.scope, "/ui/");
assert.equal(manifest.display, "standalone");
assert.ok(Array.isArray(manifest.icons) && manifest.icons.length >= 3, "PWA ikon seti eksik.");

for (const icon of manifest.icons) {
  assert.match(icon.src, /^\/ui\/assets\/pwa\/[^/]+\.png$/, `Geçersiz ikon URL'i: ${icon.src}`);
  const iconPath = resolve(sharedPwaDir, icon.src.slice("/ui/assets/pwa/".length));
  assert.ok(existsSync(iconPath), `Manifest ikon dosyası eksik: ${icon.src}`);
}

const sw = read(swPath);
assert.ok(sw.includes('request.mode === "navigate"'), "Service worker navigation bypass etmiyor.");
assert.ok(sw.includes('url.pathname.startsWith("/api/")'), "Service worker API bypass etmiyor.");
assert.ok(sw.includes("HASHED_ASSET_PATTERN"), "Service worker yalnız hashli asset sözleşmesini uygulamıyor.");
assert.ok(!/\bcache\.put\([^,]*(?:html|document|navigate|\/api\/)/i.test(sw), "Hassas HTML/API cache riski bulundu.");

for (const file of ["manifest.webmanifest", "sw.js"]) {
  assert.ok(existsSync(join(publicDir, file)), `Kaynak PWA dosyası eksik: public/${file}`);
}

const sourceText = walk(sourceDir)
  .filter((path) => [".ts", ".tsx", ".css"].includes(extname(path)))
  .map(read)
  .join("\n");
const forbiddenSourceFragments = [
  "/api/bots/create",
  "wallet.total_usd * 0.0082",
  "+$42.10",
  "has_binance_keys: false",
  "185.112.14.92",
  'localStorage.setItem("token"',
  "setInterval(fetchStatus, 1000)",
  "/ui/dist/dashboard/",
  'window.location.assign("/ui/admin.html")',
  'window.location.replace("/ui/login.html")',
  "/ui/login.html?legacy=1",
  "/api/admin/server/lockdown",
  "/api/admin/error-logs/clear",
];
for (const fragment of forbiddenSourceFragments) {
  assert.equal(
    sourceText.includes(fragment),
    false,
    `V2 kaynakta yasak legacy/mock davranış bulundu: ${fragment}`,
  );
}
for (const requiredFragment of [
  "/api/auth/whoami",
  "/api/dashboard/bootstrap",
  "/api/dashboard/stream",
  "/api/bots-engine",
  "/api/spot/order",
  "must_change_password",
  "trimmed_fields",
  "admin_isolated",
]) {
  assert.ok(
    sourceText.includes(requiredFragment),
    `V2 zorunlu API sözleşmesi kaynakta bulunamadı: ${requiredFragment}`,
  );
}

assert.ok(
  read(registerSourcePath).includes("navigator.serviceWorker.register"),
  "Service worker kayıt çağrısı eksik.",
);
assert.ok(!sw.includes("self.skipWaiting"), "Yeni service worker açık sekmeyi zorla devralmamalı.");
assert.ok(!sw.includes("self.clients.claim"), "Yeni worker eski açık sekmeleri zorla devralmamalı.");

const formatKb = (bytes) => `${(bytes / 1024).toFixed(1)} KiB`;
console.log(
  [
    "V2 build contract: OK",
    `HTML gzip ${formatKb(htmlGzip)}/${formatKb(budgets.htmlGzipBytes)}`,
    `JS gzip ${formatKb(jsGzip)}/${formatKb(budgets.initialJsGzipBytes)}`,
    `CSS gzip ${formatKb(cssGzip)}/${formatKb(budgets.initialCssGzipBytes)}`,
    `İlk JS/CSS istekleri ${assetUrls.length}/${budgets.initialAssetRequests}`,
  ].join("\n"),
);
