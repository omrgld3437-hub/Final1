# Changelog: Auth Fix (Login Redirect Loop)

## Root cause

- **Sessions were validated with a per-process `boot_id`.** With `uvicorn --workers 2`, each worker has its own `boot_id`. Login on worker A wrote the session to the DB with worker A’s `boot_id`. The next request (e.g. `GET /api/accounts/by-code/<code>`) often hit worker B, which looked up the session with `WHERE token_hash = ? AND boot_id = ?` using worker B’s `boot_id`. No row matched, so the API returned 401 and the UI redirected to login → **login redirect loop**.
- **Cookie was not required for API.** The UI sends `Authorization: Bearer <token>` from `sessionStorage`; the backend also accepts `auth_token` cookie. Cookies were not sent because `fetch` did not use `credentials: 'include'`, so cookie-only flows (e.g. after refresh before JS runs) could fail.
- **401 handling could cause repeated redirects.** On 401 the UI always cleared auth and redirected to `/login` without checking if already on the login page or distinguishing error codes, which could contribute to loops or bad UX.

## Fix (summary)

1. **Shared session store, no `boot_id` in lookup**  
   Session validation uses the **DB only** for the shared store and **no longer filters by `boot_id`**. So any worker can validate any token stored in `auth_sessions`. `boot_id` is still stored for diagnostics but is not used for acceptance. Sessions survive restarts and work across workers.

2. **Sliding TTL**  
   `auth_sessions` has optional `last_seen_at`. On each successful validation, `expires_at` is extended (sliding TTL). Session TTL remains 7 days (configurable via `SESSION_TTL_DAYS`).

3. **Logout invalidates session**  
   Logout now deletes the current session from the shared store (by token from cookie or `Authorization` header) and clears the cookie.

4. **Cookie and auth behavior**  
   - Login sets `auth_token` cookie with `Path=/`, `HttpOnly`, `SameSite=Lax`, and `Secure` when `request.url.scheme == "https"` or `AUTH_COOKIE_SECURE=1`.
   - Frontend `apiClient` uses `credentials: 'include'` so the cookie is sent with API calls.

5. **401 handling and diagnostics**  
   - `require_auth` returns explicit `error_code`: `UNAUTHORIZED` (missing token) or `SESSION_NOT_FOUND` (invalid/expired session).
   - Logging on auth failure includes `reason` and `request_id`.
   - New `GET /api/auth/whoami` returns `{ user_id, account_id, username }` for quick session checks.

6. **UI**  
   - On 401, if `error_code` is `BOOT_ID_MISMATCH`, `SESSION_NOT_FOUND`, or `UNAUTHORIZED`, the UI clears auth and redirects to `/ui/login.html` **once**, with a guard so it does not redirect again when already on the login page.

## Deployment

- **SQLite:** `auth_sessions` is ensured by `schema_guard`; if the table already exists, a migration adds `last_seen_at` if missing. No extra env vars required.
- **Redis:** Not used in this fix; session store remains SQLite (`auth_sessions`). If you later switch to Redis, document `REDIS_URL` and session TTL in env and docker-compose.

## Verification

- After login, `GET /api/accounts/by-code/<code>` returns 200 when the account belongs to the user.
- UI stays logged in across page refresh and with `uvicorn --workers 2`.
- Tests: `tests/test_auth_session_shared.py` (run with `TEST_LOGIN_USERNAME` and `TEST_LOGIN_PASSWORD` set for full login tests).
