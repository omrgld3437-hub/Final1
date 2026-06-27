"""V5 audit violation model."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional

Severity = Literal["BLOCKER", "CRITICAL", "MAJOR", "MINOR"]


@dataclass
class V5AuditViolation:
    severity: Severity
    code: str
    message: str
    route_key: Optional[str] = None
    shelf_id: Optional[str] = None
    symbol: Optional[str] = None
    expected: Any = None
    actual: Any = None
    source_file: Optional[str] = None
    repairable: bool = False
    repair_action: Optional[str] = None
    iteration: int = 0

    def to_dict(self) -> dict:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "route_key": self.route_key,
            "shelf_id": self.shelf_id,
            "symbol": self.symbol,
            "expected": self.expected,
            "actual": self.actual,
            "source_file": self.source_file,
            "repairable": self.repairable,
            "repair_action": self.repair_action,
            "iteration": self.iteration,
        }


def has_no_blocker_or_critical(violations: list[V5AuditViolation]) -> bool:
    return not any(v.severity in ("BLOCKER", "CRITICAL") for v in violations)


def has_no_unrepairable_major(violations: list[V5AuditViolation]) -> bool:
    return not any(v.severity == "MAJOR" and not v.repairable for v in violations)
