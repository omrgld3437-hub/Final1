import assert from "node:assert/strict";
import {
  compareDecimal,
  divideAndQuantize,
  multiplyByRatio,
  multiplyDecimal,
  normalizeDecimal,
  quantizeDown,
} from "../src/features/trade/decimal.ts";

assert.equal(normalizeDecimal("1e-8"), "0.00000001");
assert.equal(normalizeDecimal("00042.1200"), "42.12");
assert.equal(quantizeDown("0.123456789", "0.00001"), "0.12345");
assert.equal(multiplyDecimal("0.1", "0.2"), "0.02");
assert.equal(multiplyByRatio("123.456789", 25), "30.864197");
assert.equal(divideAndQuantize("25", "66973.12", "0.000001"), "0.000373");
assert.equal(compareDecimal("9007199254740993.01", "9007199254740993"), 1);
assert.equal(quantizeDown("1", "0"), null);

console.log("Decimal/order contracts: OK");
