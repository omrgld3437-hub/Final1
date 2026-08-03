const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const source = fs.readFileSync('ui/assets/core/apiClient.js', 'utf8');

function makeHarness(initialHealthOk) {
    let now = 10_000;
    let healthOk = initialHealthOk;
    let intervalCallback = null;
    const calls = {
        persistent: 0,
        dismiss: 0,
        success: 0,
        events: [],
        health: 0,
    };

    class FakeDate extends Date {
        static now() {
            return now;
        }
    }

    const window = {
        location: {
            origin: 'https://example.test',
            pathname: '/ui/dashboard.html',
            replace: function () {},
        },
        Toast: {
            showPersistent: function () { calls.persistent += 1; },
            dismiss: function () { calls.dismiss += 1; },
            success: function () { calls.success += 1; },
        },
        dispatchEvent: function (event) {
            calls.events.push(event.detail);
        },
    };

    const context = {
        window,
        document: { cookie: '', getElementById: function () { return null; } },
        sessionStorage: {
            getItem: function () { return null; },
            setItem: function () {},
            removeItem: function () {},
        },
        localStorage: { removeItem: function () {} },
        performance: { now: function () { return now; } },
        crypto: { randomUUID: function () { return 'test-request-id'; } },
        CustomEvent: function (_name, options) { this.detail = options.detail; },
        Date: FakeDate,
        Map,
        Promise,
        console,
        setTimeout: function () { return 1; },
        clearTimeout: function () {},
        setInterval: function (callback) {
            intervalCallback = callback;
            return 1;
        },
        clearInterval: function () {
            intervalCallback = null;
        },
        fetch: function (url) {
            assert.ok(String(url).endsWith('/api/health'));
            calls.health += 1;
            if (!healthOk) return Promise.reject(new Error('network down'));
            return Promise.resolve({
                ok: true,
                status: 200,
                json: function () { return Promise.resolve({ ok: true }); },
            });
        },
    };
    vm.createContext(context);
    vm.runInContext(source, context);

    return {
        context,
        calls,
        setNow: function (value) { now = value; },
        setHealthOk: function (value) { healthOk = value; },
        tick: function () {
            assert.equal(typeof intervalCallback, 'function');
            intervalCallback();
        },
    };
}

async function flushPromises() {
    await Promise.resolve();
    await Promise.resolve();
    await new Promise(function (resolve) { setImmediate(resolve); });
}

async function testApplication5xxDoesNotAnnounceOutageWhenHealthIsUp() {
    const harness = makeHarness(true);
    harness.context.startServerBackChecker('Endpoint geçici hata verdi');
    await flushPromises();

    assert.equal(harness.calls.health, 1);
    assert.equal(harness.calls.persistent, 0);
    assert.equal(harness.calls.success, 0);
    assert.deepEqual(harness.calls.events, []);
    assert.equal(harness.context.window.__TT_SERVER_UNREACHABLE__, undefined);
}

async function testRealOutageRequiresHealthConfirmationAndRecoversOnce() {
    const harness = makeHarness(false);
    harness.context.startServerBackChecker('Sunucuya bağlanılamıyor');
    await flushPromises();

    assert.equal(harness.calls.persistent, 0);
    harness.setNow(14_000);
    harness.tick();
    await flushPromises();

    assert.equal(harness.calls.persistent, 1);
    assert.equal(harness.context.window.__TT_SERVER_UNREACHABLE__, true);
    assert.deepEqual(harness.calls.events[0], { unreachable: true });

    harness.setHealthOk(true);
    harness.setNow(15_000);
    harness.tick();
    await flushPromises();

    assert.equal(harness.calls.success, 1);
    assert.equal(harness.calls.dismiss, 1);
    assert.equal(harness.context.window.__TT_SERVER_UNREACHABLE__, false);
    assert.deepEqual(harness.calls.events[1], { unreachable: false });
}

(async function main() {
    await testApplication5xxDoesNotAnnounceOutageWhenHealthIsUp();
    await testRealOutageRequiresHealthConfirmationAndRecoversOnce();
    console.log('apiClient server health gate: 2 checks passed');
})().catch(function (error) {
    console.error(error);
    process.exitCode = 1;
});
