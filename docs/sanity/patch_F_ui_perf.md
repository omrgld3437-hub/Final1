# Patch F: UI resilience + speed

## Summary
- **inFlight:** Snapshot polling resets `State.inFlight` in `finally`; no stuck state.
- **AbortController:** apiClient uses AbortController for timeout so fetch is cancelled; timeout cleared in `finally`.
- **Snapshot fields per tab:** Main view uses `fields=prices,kpis`; bots tab uses `fields=prices,bots,kpis`; wallet modal uses `fields=wallet,prices`.
- **Lazy coin logos:** `ensureLazyLogoObserver()` and `observeLazyLogos(container)`; `window.coinLogoCache` for loaded URLs. Use `img.lazy-coin-logo[data-src]` for deferred loading; existing `loading="lazy"` remains on many logos.

## How to verify
1. **Polling:** Open dashboard; in Network tab confirm snapshot requests use `fields=` and complete; no duplicate in-flight; after timeout (e.g. disconnect) next poll recovers.
2. **Fields:** Switch to Bots tab; snapshot URL should include `fields=prices,bots,kpis`.
3. **Logos:** Bots/list with many coins: logos load as you scroll (native `loading="lazy"` or observer for `data-src`).

## Expected outcomes
- UI snapshot polling never deadlocks due to inFlight stuck; on timeout it recovers.
- Coin logos are lazy-loaded where applied; initial network request count reduced on long lists.
