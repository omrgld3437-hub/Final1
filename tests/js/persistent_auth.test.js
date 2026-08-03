const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const source = fs.readFileSync('ui/assets/core/persistentAuth.js', 'utf8');

function makeStorage(initial) {
    const values = new Map(Object.entries(initial || {}));
    return {
        getItem(key) {
            return values.has(key) ? values.get(key) : null;
        },
        setItem(key, value) {
            values.set(key, String(value));
        },
        removeItem(key) {
            values.delete(key);
        },
        snapshot() {
            return Object.fromEntries(values);
        },
    };
}

function makeHarness(options) {
    options = options || {};
    const localStorage = makeStorage(options.local);
    const sessionStorage = makeStorage(options.session);
    let fetchCalls = 0;
    const window = {
        localStorage,
        sessionStorage,
        location: { origin: 'https://ayserose.com' },
        fetch() {
            fetchCalls += 1;
            if (options.networkError) return Promise.reject(new Error('offline'));
            const status = options.status == null ? 200 : options.status;
            return Promise.resolve({
                ok: status >= 200 && status < 300,
                status,
                json() {
                    return Promise.resolve(options.whoami || {
                        user_id: 7,
                        username: 'ayse',
                        name: 'Ayse',
                        surname: 'Rose',
                        account_id: 11,
                        account_code: '123456',
                        is_admin: false,
                    });
                },
            });
        },
    };
    const context = { window, Promise, console };
    vm.createContext(context);
    vm.runInContext(source, context);
    return {
        auth: window.AyserosePersistentAuth,
        localStorage,
        sessionStorage,
        fetchCalls: () => fetchCalls,
    };
}

async function testRestoresLocalStorageIntoNewSafariSession() {
    const harness = makeHarness({
        local: { token: 'persistent-token', user: '{"id":7}' },
    });
    const valid = await harness.auth.restore();
    assert.equal(valid, true);
    assert.equal(harness.fetchCalls(), 0);
    assert.equal(harness.sessionStorage.getItem('token'), 'persistent-token');
    assert.equal(harness.sessionStorage.getItem('user'), '{"id":7}');
}

async function testRestoresCookieOnlySessionWithWhoami() {
    const harness = makeHarness();
    const valid = await harness.auth.restore();
    assert.equal(valid, true);
    assert.equal(harness.fetchCalls(), 1);
    const user = JSON.parse(harness.localStorage.getItem('user'));
    assert.equal(user.id, 7);
    assert.equal(user.account_id, 11);
}

async function testTemporaryNetworkFailureNeverClearsStoredIdentity() {
    const harness = makeHarness({
        local: { user: '{"id":7}' },
        networkError: true,
    });
    const valid = await harness.auth.restore({ verify: true });
    assert.equal(valid, null);
    assert.equal(harness.localStorage.getItem('user'), '{"id":7}');
}

async function testConfirmedUnauthorizedClearsPersistentSession() {
    const harness = makeHarness({
        local: { token: 'expired-token', user: '{"id":7}' },
        status: 401,
    });
    const valid = await harness.auth.restore({ verify: true });
    assert.equal(valid, false);
    assert.equal(harness.localStorage.getItem('token'), null);
    assert.equal(harness.localStorage.getItem('user'), null);
    assert.equal(harness.sessionStorage.getItem('token'), null);
    assert.equal(harness.sessionStorage.getItem('user'), null);
}

(async function main() {
    await testRestoresLocalStorageIntoNewSafariSession();
    await testRestoresCookieOnlySessionWithWhoami();
    await testTemporaryNetworkFailureNeverClearsStoredIdentity();
    await testConfirmedUnauthorizedClearsPersistentSession();
    console.log('persistentAuth: 4 checks passed');
})().catch(function (error) {
    console.error(error);
    process.exitCode = 1;
});
