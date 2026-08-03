const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const source = fs.readFileSync('ui/assets/core/apiClient.js', 'utf8');

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
    };
}

const localStorage = makeStorage({
    token: 'persisted-token',
    user: '{"id":7}',
});
const sessionStorage = makeStorage();
const window = {
    location: {
        origin: 'https://ayserose.com',
        pathname: '/ui/dashboard.html',
        replace() {},
    },
    localStorage,
    sessionStorage,
    dispatchEvent() {},
};
const context = {
    window,
    localStorage,
    sessionStorage,
    document: { cookie: '', getElementById() { return null; } },
    fetch() {
        return Promise.resolve({
            ok: true,
            json() {
                return Promise.resolve({ auth_cookie_primary: false });
            },
        });
    },
    performance: { now() { return 1; } },
    crypto: { randomUUID() { return 'request-id'; } },
    CustomEvent: function CustomEvent() {},
    AbortController,
    Map,
    Promise,
    console,
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
};
vm.createContext(context);
vm.runInContext(source, context);

assert.equal(window.apiClient.hasToken(), true);
assert.equal(sessionStorage.getItem('token'), 'persisted-token');

window.apiClient.clearAuthAndBroadcast();
assert.equal(sessionStorage.getItem('token'), null);
assert.equal(localStorage.getItem('token'), null);
assert.equal(sessionStorage.getItem('user'), null);
assert.equal(localStorage.getItem('user'), null);

console.log('apiClient persistent storage: passed');
