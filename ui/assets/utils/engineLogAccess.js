/**
 * Bot motor logları — yalnızca admin oturumu görür.
 */
(function (global) {
    'use strict';

    var _resolved = false;
    var _isAdmin = false;

    function applyUi() {
        if (typeof document !== 'undefined' && document.body) {
            document.body.classList.toggle('engine-log-admin', _isAdmin);
        }
        var panel = document.getElementById('engineLogPanel');
        if (panel && !_isAdmin) {
            panel.style.display = 'none';
        }
    }

    function resolve() {
        if (_resolved) return Promise.resolve(_isAdmin);
        if (!global.apiClient || typeof global.apiClient.get !== 'function') {
            _isAdmin = false;
            _resolved = true;
            applyUi();
            return Promise.resolve(false);
        }
        return global.apiClient.get('/api/auth/whoami', {
            timeout: 8000,
            suppressRateLimitToast: true
        }).then(function (data) {
            _isAdmin = !!(data && data.is_admin);
            _resolved = true;
            applyUi();
            return _isAdmin;
        }).catch(function () {
            _isAdmin = false;
            _resolved = true;
            applyUi();
            return false;
        });
    }

    function canView() {
        return _isAdmin === true;
    }

    global.EngineLogAccess = {
        resolve: resolve,
        canView: canView,
        applyUi: applyUi
    };
})(typeof window !== 'undefined' ? window : globalThis);
