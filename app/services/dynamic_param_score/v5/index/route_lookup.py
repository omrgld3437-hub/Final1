"""V5 route index and O(1) lookup."""

from __future__ import annotations

from typing import Dict, List, Optional

from app.services.dynamic_param_score.v5.domain.dimensions import EXPECTED_V5_SHELF_COUNT
from app.services.dynamic_param_score.v5.domain.types import V5Shelf

V5RouteIndex = Dict[str, V5Shelf]

_index_cache: Optional[V5RouteIndex] = None


def build_v5_route_index(shelves: List[V5Shelf]) -> V5RouteIndex:
    index: V5RouteIndex = {}
    for shelf in shelves:
        if shelf.route_key in index:
            raise ValueError(f"Duplicate V5 route key: {shelf.route_key}")
        index[shelf.route_key] = shelf
    if len(index) != EXPECTED_V5_SHELF_COUNT:
        raise ValueError(f"V5 route index size mismatch: {len(index)}")
    return index


def lookup_exact_v5_shelf(index: V5RouteIndex, route_key: str) -> V5Shelf:
    shelf = index.get(route_key)
    if shelf is None:
        raise KeyError(f"V5 exact shelf not found for route: {route_key}")
    return shelf


def set_cached_index(index: V5RouteIndex) -> None:
    global _index_cache
    _index_cache = index


def get_cached_index() -> Optional[V5RouteIndex]:
    return _index_cache


def clear_index_cache() -> None:
    global _index_cache
    _index_cache = None
