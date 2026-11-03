# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Aditya Chaudhuri
"""Static user placement, indoor flags and hourly activity."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .config import NetworkConfig

HOURS = 24


@dataclass(frozen=True)
class Users:
    xy: np.ndarray           # (n, 2) metres
    zone: np.ndarray         # (n,) zone id strings
    indoor: np.ndarray       # (n,) bool
    indoor_loss_db: np.ndarray  # (n,) building entry loss, 0 for outdoor users
    active: np.ndarray       # (24, n) bool, fixed per seed

    @property
    def n(self) -> int:
        return len(self.zone)


def _disc(rng: np.random.Generator, n: int, centre: tuple[float, float], radius: float) -> np.ndarray:
    r = radius * np.sqrt(rng.random(n))
    t = 2 * np.pi * rng.random(n)
    return np.column_stack([centre[0] + r * np.cos(t), centre[1] + r * np.sin(t)])


def place_users(cfg: NetworkConfig, rng: np.random.Generator) -> Users:
    ucfg = cfg.users
    total = int(ucfg["count"])
    default_indoor = float(ucfg["indoor_fraction"])

    default_loss = float(ucfg["indoor_loss_db"])

    xy_parts, zone_parts, indoor_parts, loss_parts = [], [], [], []
    placed = 0

    def add(z, n: int, centre, radius) -> None:
        xy_parts.append(_disc(rng, n, centre, radius))
        zone_parts.append(np.full(n, z.zone_id, dtype=object))
        frac = default_indoor if z.indoor_fraction is None else float(z.indoor_fraction)
        ind = rng.random(n) < frac
        indoor_parts.append(ind)
        loss = default_loss if z.indoor_loss_db is None else float(z.indoor_loss_db)
        loss_parts.append(np.where(ind, loss, 0.0))

    for z in cfg.zones.values():
        if not z.background:
            add(z, z.users, z.centre_m, z.radius_m)
            placed += z.users
    add(cfg.zones[cfg.background_zone], total - placed, (0.0, 0.0), float(ucfg["area_radius_m"]))

    xy = np.vstack(xy_parts)
    zone = np.concatenate(zone_parts)
    indoor = np.concatenate(indoor_parts)
    indoor_loss = np.concatenate(loss_parts)

    # One uniform draw per user and hour; activity thresholds come from the zone profile.
    draws = rng.random((HOURS, len(zone)))
    p = np.empty((HOURS, len(zone)))
    for zid, prof in cfg.profiles.items():
        mask = zone == zid
        for h in range(HOURS):
            p[h, mask] = prof.activity(h)
    active = draws < p
    return Users(xy=xy, zone=zone, indoor=indoor, indoor_loss_db=indoor_loss, active=active)
