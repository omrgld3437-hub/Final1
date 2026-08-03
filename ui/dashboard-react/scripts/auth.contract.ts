import assert from "node:assert/strict";
import { passwordIssue } from "../src/features/auth/passwordPolicy.ts";

assert.equal(passwordIssue("Kuvvetli1!"), null);
assert.match(passwordIssue("kisa1A!") || "", /10 karakter/);
assert.match(passwordIssue("buyukharf1!") || "", /büyük harf/);
assert.match(passwordIssue("KUCUKHARF1!") || "", /küçük harf/);
assert.match(passwordIssue("RakamYok!!") || "", /rakam/);
assert.match(passwordIssue("Noktalama1") || "", /noktalama/);
assert.match(passwordIssue("OmerGuclu1!", "Omer") || "", /adınızı/);

console.log("Auth/password contracts: OK");
