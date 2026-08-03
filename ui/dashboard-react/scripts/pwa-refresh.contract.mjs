import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const read = (path) => readFileSync(resolve(root, path), "utf8");
const context = read("src/core/state/DashboardDataContext.tsx");
const transport = read("src/core/realtime/dashboardTransport.ts");
const app = read("src/App.tsx");
const home = read("src/components/HomeTab.tsx");
const trade = read("src/components/TradeTab.tsx");
const bots = read("src/components/BotsTab.tsx");

assert.match(context, /\/api\/home\/wallet\/refresh/);
assert.match(context, /force:\s*1/);
assert.match(context, /method:\s*"POST"/);
assert.match(context, /dedupe:\s*false/);
assert.match(context, /ayserose:manual-refresh/);
assert.match(transport, /refresh\(\): Promise<void> \{\s*return this\.snapshot\(true\)/s);
assert.match(transport, /refresh_at=\$\{Date\.now\(\)\}/);
assert.match(app, /Veriler güncellendi/);
assert.match(app, /Yenileme tamamlanamadı/);
for (const source of [home, trade, bots]) {
  assert.match(source, /ayserose:manual-refresh/);
}

console.log("PWA pull-to-refresh contract: OK");
