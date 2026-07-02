# Dynamic Param V6 Regression Lock

Fast V6-only command:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/final1-pycache-v6lock python3 -m pytest tests/dynamic_param_score/test_v6_* -q
```

Focused lock command:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/final1-pycache-v6lock python3 -m pytest tests/dynamic_param_score/test_v6_regression_lock.py -q
```

The lock covers TLM parabolic pump, DYDX deep drawdown, SOL pullback, ETH/BTC momentum, DOGE liquid fragile range, ARPA restricted unstable low-liquidity, true R2, true R3, and true R7 cases.
