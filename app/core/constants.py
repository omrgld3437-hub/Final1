"""
Single source of truth for lock and snapshot constants (TRADE_TRAILING_MASTER_SPEC v5).
All TTL/lease values must be imported from here; no duplicated literals (e.g. 60s) elsewhere.
"""

import os

# Lock lease: 10s align with heartbeat 3s + quick failover (spec: DEFAULT_LEASE_TTL = 10)
DEFAULT_LEASE_TTL_SEC = int(os.environ.get("DEFAULT_LEASE_TTL_SEC", "10"))
# Alias for botengine/locks: heartbeat renewal interval
LOCK_HEARTBEAT_SEC = int(os.environ.get("LOCK_HEARTBEAT_SEC", "3"))
# Blocking lock acquire timeout (0 = non-blocking try only)
LOCK_BLOCKING_TIMEOUT_SEC = int(os.environ.get("LOCK_BLOCKING_TIMEOUT_SEC", "0"))

# One Binance account = one wallet: serialize order submits per account_id (multi-bot same account).
ACCOUNT_TRADE_LOCK_SYMBOL = "__ACCOUNT__"

# Snapshot payload cap (500KB default; env override)
MAX_SNAPSHOT_BYTES = int(os.environ.get("MAX_SNAPSHOT_BYTES", "500000"))
# Snapshot fields feature flag
SNAPSHOT_FIELDS_ENABLED = os.environ.get(
    "SNAPSHOT_FIELDS_ENABLED", "1"
).strip().lower() in ("1", "true", "yes")
SNAPSHOT_TRIM_ENABLED = os.environ.get(
    "SNAPSHOT_TRIM_ENABLED", "1"
).strip().lower() in ("1", "true", "yes")
