# ayserose Frontend V2 Architecture

Frontend V2 is an independently deployable client for the existing FastAPI
backend. The backend and the production legacy HTML surfaces remain untouched
until the final, reversible cut-over.

## Design goals

1. One source of truth for session, account scope, live dashboard data and
   request errors.
2. Streaming first: dashboard SSE is the primary transport, with a single
   adaptive snapshot fallback.
3. Feature isolation: screens own presentation and actions; infrastructure
   lives under `core/`.
4. Safe mutations: timeout, CSRF, account scope and duplicate-submit protection
   are shared behavior.
5. Fast delivery: route-level lazy loading, no global polling fan-out, stable
   cached data during reconnects and small static assets.
6. Reversible rollout: production assets are emitted below
   `/ui/assets/v2/dashboard/`, which is already served by FastAPI.

## Source tree

```text
src/
  app/                 application shell, navigation and global boundaries
  core/
    api/               HTTP client, endpoint contracts and error normalization
    realtime/          SSE lifecycle and snapshot fallback
    state/             shared live dashboard state
  components/
    brand/             single ayserose brand mark
    coin/              local-logo registry, aliases and zero-request fallback
    *.tsx              current visual feature surfaces (migration boundary)
  context/             application providers
  lib/                 cookie session and compatibility exports
  features/
    assistant/         account/symbol/budget-scoped parameter decisions
    bots/              create studio, detail workspace and engine contracts
    trade/             decimal-safe order ticket
    ...                isolated product capabilities
  types.ts             backend-facing domain types
```

`components/` is deliberately a migration boundary: its visual implementations
can be preserved where they are already useful, while all networking and
runtime behavior moves to `core/`. New capabilities belong under `features/`.

## Runtime flow

```text
session resolve
  -> account scope
  -> immediate dashboard snapshot
  -> SSE live stream
  -> adaptive snapshot fallback only when the stream is unavailable
  -> normalized shared state
  -> feature views
```

## Rollout

1. Build and test V2 at `/ui/assets/v2/dashboard/index.html`.
2. Run legacy and V2 against the same backend during parity testing.
3. Existing login, dashboard and admin entries redirect directly to the V2
   production entry before legacy assets load. `/ui/dashboard-v2.html` remains
   a separate staging/compatibility entry.
4. Append `?legacy=1` to any legacy entry to keep the old UI active for the
   current tab. Append `?v2=1` to clear that preference and resume V2.
5. Backend services are never changed by the frontend rollout.

## Bot safety invariants

- The create studio emits the canonical engine payload and keeps every grid
  trigger and quantity explicit.
- Parameter Assistant provenance is stored only while the form still matches
  the applied recommendation; a manual edit returns the form to manual mode.
- Allocation and grid quantity totals, balance, numeric bounds and the
  backend's strict per-order minimum notional are checked again at submit.
- Start/stop responses are treated as queued commands, not immediate final
  states.
- Delete always requires an explicit base-asset decision: convert to quote or
  preserve the asset.
- Unknown mutation outcomes lock duplicate actions until the engine list is
  verified again.

## Detail data policy

The detail workspace renders high-value fields as human-readable status and
metrics while retaining complete nested config, health, grid, cycle, trade and
performance records in expandable inspectors. DCA, TRB, dynamic and multi-asset
records are not flattened away at the API boundary.
