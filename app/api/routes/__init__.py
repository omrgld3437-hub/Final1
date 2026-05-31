"""
routes Python paketi.
"""
# app.api.routes is a package; the main router and helpers live in the sibling module routes.py.
# Load that module explicitly (it is shadowed by this package) and re-export for "from app.api.routes import ...".
import importlib.util
import os
import sys

_mod_dir = os.path.dirname(os.path.abspath(__file__))
_routes_py = os.path.join(_mod_dir, "..", "routes.py")
_spec = importlib.util.spec_from_file_location("app.api._routes_impl", _routes_py)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["app.api._routes_impl"] = _mod
_spec.loader.exec_module(_mod)

router = _mod.router
invalidate_wallet_cache = _mod.invalidate_wallet_cache
invalidate_open_orders_cache = _mod.invalidate_open_orders_cache

def __getattr__(name):
    # Lazy export for names used by main.py, admin.py, finance.py, routes/home.py, subroutes/home.py
    if name in (
        "get_binance_cache_stats",
        "_price_cache",
        "_fetch_wallet_uncached",
        "_wallet_response",
        "_cache",
        "_fetch_server_public_ip",
        "_parse_public_ip_response",
    ):
        return getattr(_mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
