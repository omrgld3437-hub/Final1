/**
 * Restore a first-party Ayserose session across tabs, Safari standalone launches,
 * browser restarts and empty sessionStorage instances.
 */
(function (global) {
    'use strict';

    var AUTH_KEYS = ['token', 'user'];
    var restorePromise = null;

    function read(storage, key) {
        try {
            return storage ? storage.getItem(key) : null;
        } catch (_) {
            return null;
        }
    }

    function write(storage, key, value) {
        try {
            if (storage && value != null) storage.setItem(key, value);
        } catch (_) {}
    }

    function remove(storage, key) {
        try {
            if (storage) storage.removeItem(key);
        } catch (_) {}
    }

    function restoreStorage() {
        var state = {};
        AUTH_KEYS.forEach(function (key) {
            var sessionValue = read(global.sessionStorage, key);
            var persistentValue = read(global.localStorage, key);
            var value = sessionValue || persistentValue;
            if (value) {
                write(global.sessionStorage, key, value);
                write(global.localStorage, key, value);
            }
            state[key] = value;
        });
        return state;
    }

    function persistWhoami(data) {
        if (!data || data.user_id == null) return null;
        var user = {
            id: data.user_id,
            username: data.username || '',
            name: data.name || '',
            surname: data.surname || '',
            is_admin: !!data.is_admin,
            account_id: data.account_id != null ? data.account_id : null,
            account_code: data.account_code || null
        };
        var serialized = JSON.stringify(user);
        write(global.sessionStorage, 'user', serialized);
        write(global.localStorage, 'user', serialized);
        return user;
    }

    function clear() {
        AUTH_KEYS.forEach(function (key) {
            remove(global.sessionStorage, key);
            remove(global.localStorage, key);
        });
        remove(global.localStorage, 'boot_id');
        remove(global.localStorage, 'last_route');
    }

    function verifyWithServer(state) {
        if (typeof global.fetch !== 'function') return Promise.resolve(null);
        var headers = {
            'Accept': 'application/json',
            'X-Requested-With': 'XMLHttpRequest'
        };
        if (state && state.token) headers.Authorization = 'Bearer ' + state.token;
        return global.fetch(
            (global.location.origin || '') + '/api/auth/whoami',
            {
                method: 'GET',
                credentials: 'include',
                cache: 'no-store',
                headers: headers
            }
        ).then(function (response) {
            if (response.ok) {
                return response.json().then(function (data) {
                    persistWhoami(data);
                    return true;
                });
            }
            if (response.status === 401) {
                clear();
                return false;
            }
            return null;
        }).catch(function () {
            // A temporary network/server failure must never destroy a valid session.
            return null;
        });
    }

    function restore(options) {
        options = options || {};
        var state = restoreStorage();
        if (!options.verify && state.token && state.user) {
            return Promise.resolve(true);
        }
        if (restorePromise) return restorePromise;
        restorePromise = verifyWithServer(state).finally(function () {
            restorePromise = null;
        });
        return restorePromise;
    }

    global.AyserosePersistentAuth = {
        clear: clear,
        restore: restore,
        restoreStorage: restoreStorage
    };
})(window);
