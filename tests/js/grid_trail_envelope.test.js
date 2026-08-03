const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const source = fs.readFileSync('ui/assets/utils/gridTrailEnvelope.js', 'utf8');

function makeStorage(initial) {
    const values = new Map(Object.entries(initial || {}));
    return {
        getItem(key) {
            return values.has(key) ? values.get(key) : null;
        },
        setItem(key, value) {
            values.set(key, String(value));
        },
    };
}

function makeHarness(storedEnvelope) {
    const sessionStorage = makeStorage({
        gridTrailFloor_1_1: JSON.stringify(storedEnvelope),
    });
    const window = { sessionStorage };
    const context = { window, sessionStorage, globalThis: window, console };
    vm.createContext(context);
    vm.runInContext(source, context);
    return window.GridTrailEnvelope;
}

{
    const envelope = makeHarness({ sell: { 0: 752200 } });
    const point = {
        i: 0,
        fired: false,
        anchor: 75.22,
        trigger_hit_price: 75.20,
        trigger_price: 76.70,
    };
    envelope.syncGridTrailEnvelope(1, 1, [point], [], 75.21, true);
    const display = envelope.trailDisplayFromEnvelope(point, 'sell', 0.3);
    assert.equal(display.anchor, 75.22);
}

{
    const envelope = makeHarness({ buy: { 0: 0.007522 } });
    const point = {
        i: 0,
        fired: false,
        anchor: 75.16,
        trigger_hit_price: 75.20,
        trigger_price: 73.70,
    };
    envelope.syncGridTrailEnvelope(1, 1, [], [point], 75.18, true);
    const display = envelope.trailDisplayFromEnvelope(point, 'buy', 0.3);
    assert.equal(display.anchor, 75.16);
}

console.log('gridTrailEnvelope: 2 poisoned-cache checks passed');
