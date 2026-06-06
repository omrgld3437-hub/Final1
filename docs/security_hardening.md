# Auth Security Hardening — Rollout & Migration

**Goal:** Harden auth (cookie-first, CSRF, CSP, rate limit) without breaking existing flows. All changes are feature-flagged.

---

## 1. Feature flags (env)

| Env | Default | Description |
|-----|--------|-------------|
| AUTH_COOKIE_PRIMARY | 0 | When 1, backend may omit token from login JSON; UI must not persist token |
| AUTH_ALLOW_BEARER | 1 | Keep legacy Bearer auth |
| AUTH_CSRF_ENABLED | 1 | Enable CSRF for cookie-authenticated state-changing requests |
| AUTH_CSRF_ORIGIN_CHECK | 1 | Enforce Origin/Referer when present |
| AUTH_CSRF_DOUBLE_SUBMIT | 0 | Require X-CSRF-Token header matching csrf_token cookie |
| AUTH_COOKIE_SECURE_AUTO | 1 | Set Secure cookie when request is HTTPS |
| AUTH_COOKIE_SAMESITE | Lax | SameSite value |
| AUTH_COOKIE_MAX_AGE_SEC | 604800 | 7 days |
| AUTH_RATE_LIMIT_ENABLED | 1 | Rate limit login |
| AUTH_RATE_LIMIT_LOGIN_PER_IP_5MIN | 20 | Max login attempts per IP per 5 min |
| AUTH_RATE_LIMIT_LOGIN_PER_USER_5MIN | 10 | Max per user/phone per 5 min |
| SECURITY_HEADERS_ENABLED | 1 | X-Content-Type-Options, X-Frame-Options, etc. |
| CSP_ENABLED | 1 | Content-Security-Policy |
| CSP_REPORT_ONLY | 1 | Use Report-Only CSP first |
| CSP_ALLOW_INLINE_SCRIPTS | 1 | Allow 'unsafe-inline' for scripts initially |
| HSTS_ENABLED | 1 | Strict-Transport-Security when HTTPS |

---

## 2. Public config (UI)

**GET /api/config/public** (no auth) returns:

- `auth_cookie_primary`: boolean — if true, UI should not persist token; use cookie only.
- `csrf_double_submit`: boolean — if true, UI must send `X-CSRF-Token` header (value from `csrf_token` cookie) on POST/PUT/PATCH/DELETE.

UI loads this once (apiClient triggers fetch on first use) and adjusts behavior.

---

## 3. Rollout phases

### Phase 1 (safe, no breakage)

- Enable **SECURITY_HEADERS_ENABLED=1**
- Enable **CSP_ENABLED=1**, **CSP_REPORT_ONLY=1**, **CSP_ALLOW_INLINE_SCRIPTS=1**
- Enable **AUTH_CSRF_ENABLED=1** (Origin/Referer check; missing Origin allowed with warning when not strict)
- Enable **AUTH_RATE_LIMIT_ENABLED=1**

Verify: login works, refresh stays logged in, no CSP violations in console, no false CSRF blocks.

### Phase 2 (cookie-first, optional double-submit)

- Set **AUTH_COOKIE_PRIMARY=1**; keep **AUTH_ALLOW_BEARER=1**
- Optionally set **AUTH_CSRF_DOUBLE_SUBMIT=1** and ensure UI sends `X-CSRF-Token` (apiClient does this when config says so)
- Later: set **CSP_ALLOW_INLINE_SCRIPTS=0** after moving inline scripts to external files
- Then set **CSP_REPORT_ONLY=0** to enforce CSP

### Rollback

- **CSRF blocks legitimate traffic:** set **AUTH_CSRF_ENABLED=0** temporarily
- **CSP breaks UI:** keep **CSP_REPORT_ONLY=1** or set **CSP_ENABLED=0**
- **Session stability:** do not re-enable boot_id in session validation (that fix stays)

---

## 4. Backend behaviour summary

- **Token source:** `get_token_from_request()`: Bearer first if AUTH_ALLOW_BEARER=1, else cookie. `request.state.auth_source` set to `bearer` or `cookie`.
- **CSRF:** Applied only when method is POST/PUT/PATCH/DELETE and auth source is cookie. `/api/auth/login` and `/api/auth/register` exempt. Origin/Referer validated against allowed hosts. Optional double-submit: cookie `csrf_token` + header `X-CSRF-Token`.
- **Login:** Same 401 message and **INVALID_CREDENTIALS** for both “user not found” and “wrong password” (no enumeration). Rate limit returns 429 RATE_LIMITED with Retry-After.
- **Cookies:** auth_token HttpOnly, SameSite, Secure when HTTPS; optional csrf_token (not HttpOnly) when AUTH_CSRF_DOUBLE_SUBMIT=1.

---

## 5. Manual checklist

- [ ] Login works (Bearer and cookie).
- [ ] Refresh keeps user logged in.
- [ ] POST/PUT/PATCH/DELETE with cookie auth work (Origin/Referer sent by browser).
- [ ] With AUTH_CSRF_DOUBLE_SUBMIT=1, requests without X-CSRF-Token get 403 CSRF_BLOCKED; with header they succeed.
- [ ] With AUTH_COOKIE_PRIMARY=1, login response has token: null; UI does not store token; subsequent requests use cookie.
- [ ] Rate limit: many login attempts from same IP → 429 with Retry-After.
- [ ] No infinite redirects; 401 redirect only once and not on login page.
