import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const read = (path) => readFileSync(resolve(root, path), "utf8");

const trade = read("src/components/TradeTab.tsx");
const app = read("src/App.tsx");
const context = read("src/context/DashboardContext.tsx");
const splash = read("src/app/mobileSplash.ts");
const html = read("index.html");

assert.match(trade, /setFeaturedFavorite/);
assert.match(trade, /\(current\.currentIndex \+ 1\) % favorites\.length/);
assert.match(trade, /setFeaturedFavorite\(\(current\)[\s\S]*\}, 1_500\)/);
assert.match(trade, /document\.visibilityState !== "visible"/);
assert.match(trade, /trade-favorite-enter/);
assert.match(trade, /trade-favorite-exit/);
assert.match(trade, /for \(const symbol of favorites\)/);
assert.match(trade, /for \(const rawSymbol of Object\.keys\(effectivePrices\)\)/);
assert.match(trade, /loadError && visibleCoins\.length === 0/);
assert.match(trade, /favorilerin canlı[\s\S]*gösterilmeye devam ediyor/);
assert.doesNotMatch(trade, /const topFavorite[\s\S]*\.sort\(/);
assert.doesNotMatch(trade, /trade-favorite-progress/);

assert.match(html, /id="mobile-app-splash"/);
assert.match(html, /Ayserose açılıyor/);
assert.match(html, /ayserose-plain-v4-192\.png/);
assert.match(html, /@media \(max-width:639px\)/);
assert.match(html, /apple-mobile-web-app-status-bar-style" content="black"/);
assert.match(html, /mobile-splash-pending/);
assert.match(html, /var shouldShow = window\.matchMedia/);
assert.match(html, /navigator\.standalone === true/);
assert.match(html, /mobile-pwa-standalone/);
assert.match(
  html,
  /translateY\(calc\(env\(safe-area-inset-top,0px\)\/-2\)\)/,
);
assert.match(html, /safe-area-inset-bottom/);
assert.match(html, /safe-area-inset-top/);
assert.doesNotMatch(html, /navigationType/);
assert.doesNotMatch(html, /ayserose:startup-ready-at/);
assert.match(splash, /SPLASH_HOLD_MS = 640/);
assert.match(splash, /SPLASH_EXIT_MS = 160/);
assert.doesNotMatch(splash, /localStorage/);
assert.match(app, /lastUpdatedAt !== null/);
assert.match(app, /dismissMobileAppSplash/);
assert.match(context, /authRequired[\s\S]*dismissMobileAppSplash/);

console.log("Trade carousel and mobile startup experience contracts: OK");
