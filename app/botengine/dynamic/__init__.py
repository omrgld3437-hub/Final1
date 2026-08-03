"""
Dynamic Mode package (production path).

Architecture (see TRADE_TRAILING_MASTER_SPEC.md):

    +------------------+    +-------------------+    +----------------+
    | DPS V6 engine    | -> | absolute PA plan  | -> | Orchestrator   |
    | (same as Param   |    | (grids/alloc/     |    | (apply overlay)|
    |  Assistant)      |    |  profit/rebalance)|    |                |
    +------------------+    +-------------------+    +----------------+

Hard rules:
  * Parameters are computed ONCE per cycle (cycle start), including Tur 1.
  * Manual mode is the default; setting dynamic_mode=False fully bypasses this package.
  * When dynamic_mode_v2=True, this package's orchestrator hook is skipped
    (mutual exclusion with app/botengine/dynamic_v2/).
  * Non-deployable / R8 Kapalı → round is not started; fixed 30-minute rescan.
  * regime_multiplier is no longer on the live path (absolute V6 plan only).
"""
