import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const projectDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const uiDir = resolve(projectDir, "..");

for (const filename of ["login.html", "dashboard.html", "admin.html"]) {
  const html = readFileSync(resolve(uiDir, filename), "utf8");
  const cutoverIndex = html.indexOf("/ui/assets/v2/dashboard/index.html");
  assert.ok(cutoverIndex > -1, `${filename}: V2 yönlendirmesi eksik.`);
  assert.ok(
    cutoverIndex < html.indexOf("/ui/assets/core/persistentAuth.js"),
    `${filename}: yönlendirme eski çalışma zamanı yüklenmeden önce yapılmalı.`,
  );
  assert.ok(html.includes("ayserose-ui-version"), `${filename}: sürüm tercihi eksik.`);
  assert.ok(html.includes("params.get('legacy') === '1'"), `${filename}: legacy kaçışı eksik.`);
  assert.ok(html.includes("params.get('v2') === '1'"), `${filename}: V2 dönüşü eksik.`);
}

const login = readFileSync(resolve(uiDir, "login.html"), "utf8");
assert.ok(
  login.includes("target.searchParams.set('auth', 'login')"),
  "Login girişi V2 kimlik ekranını zorlamalı.",
);

const bridge = readFileSync(resolve(uiDir, "dashboard-v2.html"), "utf8");
assert.ok(
  bridge.includes("/ui/assets/v2/dashboard/index.html"),
  "V2 uyumluluk girişi üretim paketine bağlanmıyor.",
);

console.log("Live cutover contracts: OK");
