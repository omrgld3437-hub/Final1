"""
Dynamic Mode package.

Architecture (see TRADE_TRAILING_MASTER_SPEC.md and Dynamic Mode design report):

    +------------------+    +--------------+    +--------------+    +----------------+
    | StrategyEngine   | -> | RiskEngine   | -> | CycleManager | -> | Orchestrator   |
    | (suggest params) |    | (clamp+safe) |    | (snapshot)   |    | (apply overlay)|
    +------------------+    +--------------+    +--------------+    +----------------+

Hard rules:
  * Parameters are computed ONCE per cycle (cycle start). Immutable inside the cycle.
  * Risk engine has FINAL say. No suggestion is ever applied unmodified.
  * Manual mode is the default; setting dynamic_mode=False fully bypasses this package.
  * Safety prerequisites (max_buy_levels, daily_loss_limit_usd, stop-loss, emergency
    close) MUST be present before dynamic_mode can be turned on.
"""
