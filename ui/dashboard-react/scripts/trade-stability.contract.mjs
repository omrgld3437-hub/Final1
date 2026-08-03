import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const trade = readFileSync(resolve(root, "src/components/TradeTab.tsx"), "utf8");
const css = readFileSync(resolve(root, "src/index.css"), "utf8");
const liveCss = css.match(/\.live-value \{[\s\S]*?@keyframes live-value-down \{[\s\S]*?\n\}/)?.[0] || "";

assert.match(trade, /function mergePriceMaps/, "Eksik anlık veriler son başarılı piyasa değerini korumalı.");
assert.match(trade, /setFavoritePrices\(\(current\) => mergePriceMaps/);
assert.match(trade, /setSearchPrices\(\(current\) => mergePriceMaps/);
assert.match(trade, /window\.setInterval\(loadSearchedPrices, 1_000\)/);
assert.match(trade, /contentVisibility: "auto"/);
assert.match(trade, /function PendingOrdersCard/);
assert.match(trade, /\/api\/binance\/open-orders\?account_id=/);
assert.match(trade, /method: "DELETE"/);
assert.match(trade, /openOrders\.length > 0/);
assert.match(trade, /emptyOpenOrderPollsRef/);
assert.match(trade, /emptyOpenOrderPollsRef\.current < 3/);
assert.match(trade, /pendingCancellationRef/);
assert.match(trade, /window\.setTimeout\(resolve, 1_000\)/);
assert.match(liveCss, /font-variant-numeric: tabular-nums/);
assert.doesNotMatch(liveCss, /translateY/, "Canlı değer blink efekti rakamları hareket ettirmemeli.");

console.log("Trade stability and stationary blink contract: OK");
