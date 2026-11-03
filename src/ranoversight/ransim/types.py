# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Aditya Chaudhuri
"""Plain data types shared across the simulator."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Param = Literal["tilt", "power", "cio", "alarm_threshold"]


class ChangeRejected(ValueError):
    """A change was outside hardware limits or targeted something not controllable."""


@dataclass(frozen=True)
class CellConfig:
    tilt_deg: float
    power_dbm: float
    cio_db: float


@dataclass(frozen=True)
class Change:
    param: Param
    value: float
    reason: str
    cell_id: str | None = None   # None for alarm-threshold changes
    target: str | None = None    # alarm rule name


@dataclass(frozen=True)
class ChangeRecord:
    change_id: str
    hour: int
    cell_id: str | None
    target: str | None
    param: str
    old: float
    new: float
    reason: str
    warnings: tuple[str, ...] = ()
    is_rollback_of: str | None = None


@dataclass(frozen=True)
class Alarm:
    rule: str
    subject: str        # zone id or cell id
    value: float
    threshold: float


@dataclass(frozen=True)
class CellKPI:
    load: float
    active_users: int
    tput_mean_mbps: float
    tilt_deg: float
    power_dbm: float
    cio_db: float
    up: bool


@dataclass(frozen=True)
class ZoneKPI:
    coverage_pct: float
    tput_p5_mbps: float
    tput_mean_mbps: float
    active_users: int


@dataclass(frozen=True)
class KPISnapshot:
    hour: int
    coverage_pct: float
    tput_mean_mbps: float
    tput_p5_mbps: float
    poor_sinr_users: int
    active_users: int
    total_power_w: float
    load_converged: bool
    per_cell: dict[str, CellKPI]
    per_zone: dict[str, ZoneKPI]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NetworkState:
    """Everything needed to rebuild a Network exactly (with the same config)."""

    seed: int
    hour: int
    cells: dict[str, CellConfig]
    down_sites: list[str]
    alarm_thresholds: dict[str, float]
    log: list[ChangeRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "NetworkState":
        return cls(
            seed=int(d["seed"]),
            hour=int(d["hour"]),
            cells={k: CellConfig(**v) for k, v in d["cells"].items()},
            down_sites=list(d["down_sites"]),
            alarm_thresholds={k: float(v) for k, v in d["alarm_thresholds"].items()},
            log=[ChangeRecord(**{**r, "warnings": tuple(r["warnings"])}) for r in d["log"]],
        )
