# Patch B: Worker-only order placement (web never places orders)

## Summary
Runtime guard at order placement: `binance_spot.place_order` and `spot_engine.place_order` check `DATABASE_ROLE` / `PROCESS_ROLE`. If not worker, raise `AppError(WORKER_ONLY_OPERATION)` with 403. Response includes `error_code`, `error_id`, `request_id`.

## How to verify
1. **Unit tests**
   ```bash
   pytest tests/test_worker_only_order_guard.py -v
   ```

2. **Role test (manual)**
   - Start web with `DATABASE_ROLE=web` (or leave default).
   - Call `POST /api/binance/order` or spot order endpoint with valid auth.
   - Expected: **403** with body:
     ```json
     { "ok": false, "error": { "error_code": "WORKER_ONLY_OPERATION", "error_id": "...", "request_id": "...", "message": "..." } }
     ```

## Expected outcomes
- Any attempt to place an order when `DATABASE_ROLE!=worker` returns standardized error JSON with `WORKER_ONLY_OPERATION`.
- Worker process (e.g. `DATABASE_ROLE=worker` in worker_main) can place orders as before.
