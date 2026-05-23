#!/usr/bin/env python3
"""
Binance weight simulator.
Inputs: users, poll_interval, worker_trade_rate
Output: expected weight/minute & whether limit exceeded.
Usage: python scripts/binance_weight_sim.py --users 10 --poll 3 --trades 2
"""
import argparse

BINANCE_WEIGHT_LIMIT = 1200  # Typical IP limit per minute
WEIGHT_ACCOUNT = 10
WEIGHT_ORDER = 1
WEIGHT_TICKER_PRICE = 2
WEIGHT_TICKER_24HR = 40  # per symbol; bulk ~40
WEIGHT_EXCHANGE_INFO = 10
WEIGHT_TIME = 1


def main():
    ap = argparse.ArgumentParser(description="Binance weight simulator")
    ap.add_argument("--users", type=int, default=10, help="Concurrent users (snapshot)")
    ap.add_argument("--poll", type=float, default=3.0, help="Snapshot poll interval (seconds)")
    ap.add_argument("--trades", type=float, default=2.0, help="Worker trades per minute")
    ap.add_argument("--datahub", type=int, default=12, help="DataHub weight/min (ticker/price 2*6)")
    args = ap.parse_args()

    users = max(1, args.users)
    poll = max(0.5, args.poll)
    trades = max(0, args.trades)

    # Snapshot: account call per user per poll
    account_calls_per_min = (60 / poll) * users
    account_weight_per_min = account_calls_per_min * WEIGHT_ACCOUNT

    # Worker
    order_weight_per_min = trades * WEIGHT_ORDER

    # DataHub (shared)
    datahub_weight = args.datahub

    total_weight = account_weight_per_min + order_weight_per_min + datahub_weight
    limit_exceeded = total_weight > BINANCE_WEIGHT_LIMIT
    safe_users = int((BINANCE_WEIGHT_LIMIT - order_weight_per_min - datahub_weight) / ((60 / poll) * WEIGHT_ACCOUNT)) if poll > 0 else 0

    print("=== Binance Weight Simulator ===")
    print(f"Users: {users}")
    print(f"Poll interval: {poll}s")
    print(f"Worker trades/min: {trades}")
    print(f"Account weight/min: {account_weight_per_min:.0f} ({account_calls_per_min:.0f} calls)")
    print(f"Order weight/min: {order_weight_per_min:.0f}")
    print(f"DataHub weight/min: {datahub_weight}")
    print(f"---")
    print(f"Total weight/min: {total_weight:.0f}")
    print(f"Binance limit: {BINANCE_WEIGHT_LIMIT}")
    print(f"Limit exceeded: {limit_exceeded}")
    print(f"Safe max users (at this poll): {max(0, safe_users)}")


if __name__ == "__main__":
    main()
