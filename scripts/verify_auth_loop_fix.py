#!/usr/bin/env python3
"""
Verify auth login loop fix: login -> whoami 200 -> protected endpoint 200 -> logout -> whoami 401.
Run against a running server (e.g. BASE_URL=http://127.0.0.1:8000).
Requires TEST_LOGIN_USERNAME and TEST_LOGIN_PASSWORD, or pass --username/--password.
"""
import os
import sys
import argparse

try:
    import requests
except ImportError:
    print("pip install requests")
    sys.exit(1)

BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def main():
    p = argparse.ArgumentParser(description="Verify auth loop fix")
    p.add_argument("--username", default=os.environ.get("TEST_LOGIN_USERNAME", ""))
    p.add_argument("--password", default=os.environ.get("TEST_LOGIN_PASSWORD", ""))
    args = p.parse_args()
    if not args.username or not args.password:
        print("Set TEST_LOGIN_USERNAME and TEST_LOGIN_PASSWORD or pass --username and --password")
        sys.exit(2)

    session = requests.Session()
    session.headers["Content-Type"] = "application/json"
    session.headers["X-Request-ID"] = "verify-auth-" + str(os.getpid())

    # 1) Login
    r = session.post(
        f"{BASE_URL}/api/auth/login",
        json={"username": args.username, "password": args.password},
    )
    if r.status_code != 200:
        print("FAIL: login returned", r.status_code, r.text[:200])
        sys.exit(3)
    data = r.json()
    token = data.get("token")
    if not token:
        print("FAIL: no token in login response")
        sys.exit(4)
    session.headers["Authorization"] = f"Bearer {token}"
    print("OK: login 200, token received")

    # 2) Whoami
    r = session.get(f"{BASE_URL}/api/auth/whoami")
    if r.status_code != 200:
        print("FAIL: whoami returned", r.status_code, r.text[:200])
        sys.exit(5)
    print("OK: whoami 200", r.json())

    # 3) Protected endpoint (e.g. accounts or home)
    r = session.get(f"{BASE_URL}/api/accounts")
    if r.status_code != 200:
        print("FAIL: protected endpoint returned", r.status_code, r.text[:200])
        sys.exit(6)
    print("OK: protected endpoint 200")

    # 4) Logout
    account_id = data.get("user", {}).get("account_id") or 1
    r = session.post(
        f"{BASE_URL}/api/auth/logout",
        json={"account_id": account_id},
    )
    if r.status_code != 200:
        print("FAIL: logout returned", r.status_code, r.text[:200])
        sys.exit(7)
    print("OK: logout 200")

    # 5) Whoami after logout -> 401
    r = session.get(f"{BASE_URL}/api/auth/whoami")
    if r.status_code != 401:
        print("FAIL: whoami after logout should be 401, got", r.status_code)
        sys.exit(8)
    print("OK: whoami after logout 401")

    print("All checks passed. Auth loop fix verification OK.")


if __name__ == "__main__":
    main()
