# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Aditya Chaudhuri
"""Load and validate the network configuration (config/network.yaml)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG = Path(__file__).resolve().parents[3] / "config" / "network.yaml"


@dataclass(frozen=True)
class ZoneConfig:
    zone_id: str
    priority: int
    label: str
    background: bool = False
    centre_m: tuple[float, float] = (0.0, 0.0)
    radius_m: float = 0.0
    users: int = 0
    indoor_fraction: float | None = None
    indoor_loss_db: float | None = None


@dataclass(frozen=True)
class TrafficProfile:
    base: float
    peak: float
    peak_hours: tuple[int, ...]

    def activity(self, hour: int) -> float:
        return self.peak if hour in self.peak_hours else self.base


@dataclass(frozen=True)
class AlarmRule:
    name: str
    threshold: float
    low: float
    high: float


@dataclass(frozen=True)
class NetworkConfig:
    raw: dict[str, Any] = field(repr=False)
    zones: dict[str, ZoneConfig]
    profiles: dict[str, TrafficProfile]
    alarm_rules: dict[str, AlarmRule]

    # Short accessors for the sections used everywhere.
    @property
    def layout(self) -> dict[str, Any]:
        return self.raw["layout"]

    @property
    def radio(self) -> dict[str, Any]:
        return self.raw["radio"]

    @property
    def limits(self) -> dict[str, Any]:
        return self.raw["limits"]

    @property
    def defaults(self) -> dict[str, Any]:
        return self.raw["defaults"]

    @property
    def users(self) -> dict[str, Any]:
        return self.raw["users"]

    @property
    def background_zone(self) -> str:
        return next(z for z, c in self.zones.items() if c.background)


def load_config(path: str | Path | None = None) -> NetworkConfig:
    raw = yaml.safe_load(Path(path or DEFAULT_CONFIG).read_text())
    return from_dict(raw)


def from_dict(raw: dict[str, Any]) -> NetworkConfig:
    zones: dict[str, ZoneConfig] = {}
    for zid, z in raw["zones"].items():
        zones[zid] = ZoneConfig(
            zone_id=zid,
            priority=int(z["priority"]),
            label=str(z["label"]),
            background=bool(z.get("background", False)),
            centre_m=tuple(z.get("centre_m", (0.0, 0.0))),
            radius_m=float(z.get("radius_m", 0.0)),
            users=int(z.get("users", 0)),
            indoor_fraction=z.get("indoor_fraction"),
            indoor_loss_db=z.get("indoor_loss_db"),
        )
    if sum(z.background for z in zones.values()) != 1:
        raise ValueError("exactly one zone must be the background zone")
    if sum(z.users for z in zones.values()) > raw["users"]["count"]:
        raise ValueError("zone users exceed total user count")

    profiles = {
        zid: TrafficProfile(float(p["base"]), float(p["peak"]), tuple(int(h) for h in p["peak_hours"]))
        for zid, p in raw["traffic_profiles"].items()
    }
    missing = set(zones) - set(profiles)
    if missing:
        raise ValueError(f"no traffic profile for zones {sorted(missing)}")

    rules = {
        name: AlarmRule(name, float(r["threshold"]), float(r["range"][0]), float(r["range"][1]))
        for name, r in raw["alarms"].items()
    }
    return NetworkConfig(raw=raw, zones=zones, profiles=profiles, alarm_rules=rules)
