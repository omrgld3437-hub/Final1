import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const page = readFileSync(resolve(root, "src/features/admin/AdminPage.tsx"), "utf8");
const api = readFileSync(resolve(root, "src/features/admin/api.ts"), "utf8");
const backend = readFileSync(resolve(root, "../../app/api/admin.py"), "utf8");

assert.match(page, /Yeni hesap/);
assert.match(page, /Hesap şifresi/);
assert.match(page, /Askıdan çıkar/);
assert.match(page, /Kalıcı hesap silme/);
assert.match(page, /<Settings/);
assert.match(api, /\/api\/admin\/accounts\?lite=0/);
assert.match(api, /\/api\/admin\/accounts\?lite=1/);
assert.match(page, /fetchAccountSummary/);
assert.match(page, /Bot \$\{formatUsd\(account\.bots_balance_usd\)\}/);
assert.match(backend, /wallet_equity = max\(/);
assert.match(backend, /total_wallet_equity_usd/);
assert.match(api, /\/api\/admin\/generate-and-set-user-password/);
assert.match(api, /\/api\/admin\/set-user-password/);
assert.match(api, /\/api\/admin\/suspend-user/);
assert.match(backend, /suspended: Optional\[bool\]/);
assert.match(backend, /if suspended is True/);
assert.match(backend, /elif suspended is False/);

console.log("Admin account management contract: OK");
