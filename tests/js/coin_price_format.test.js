const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const source = fs.readFileSync('ui/assets/utils/coinPriceFormat.js', 'utf8');
const window = {};
const context = { window, global: window, console };
vm.createContext(context);
vm.runInContext(source, context);

const parse = window.CoinPriceFormat.parseLocalizedNumber;

assert.equal(parse('75,2200'), 75.22);
assert.equal(parse('1.234,56'), 1234.56);
assert.equal(parse('1,234.56'), 1234.56);
assert.equal(parse('$0.00001234'), 0.00001234);
assert.equal(parse('0,33200000 SOL'), 0.332);
assert.equal(parse(75.22), 75.22);
assert.equal(parse('—'), null);

console.log('coinPriceFormat: 7 checks passed');
