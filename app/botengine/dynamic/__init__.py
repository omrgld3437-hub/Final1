"""
Dynamic Mode package (production path).

Architecture (see TRADE_TRAILING_MASTER_SPEC.md):

    +------------------+    +-------------------+    +----------------+
    | DPS V6 engine    | -> | regime_multiplier | -> | Orchestrator   |
    | (cycle snapshot) |    | (apply to frozen  |    | (apply overlay)|
    | via cycle_manager|    |  reference)       |    |                |
    +------------------+    +-------------------+    +----------------+

Hard rules:
  * Parameters are computed ONCE per cycle (cycle start). Immutable inside the cycle.
  * Manual mode is the default; setting dynamic_mode=False fully bypasses this package.
  * When dynamic_mode_v2=True, this package's orchestrator hook is skipped
    (mutual exclusion with app/botengine/dynamic_v2/).
  * Current operator policy keeps max_buy_levels as the only structural
    prerequisite. daily_loss_limit, stop-loss and emergency-close brakes are
    disabled behind flags.

Legacy StrategyEngine / RiskEngine / cycle_duration have been removed; the live
decision path is DPS V6 + regime_multiplier only.
"""
