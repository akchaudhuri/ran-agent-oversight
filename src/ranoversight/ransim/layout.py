# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Aditya Chaudhuri
"""Hexagonal site layout: 1 + 6 + 12 sites, 3 sectors each."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .config import NetworkConfig

SECTOR_LETTERS = "ABCDEF"


@dataclass(frozen=True)
class Layout:
    site_ids: list[str]
    site_xy: np.ndarray          # (n_sites, 2) metres
    site_ring: np.ndarray        # (n_sites,) 0 = centre
    cell_ids: list[str]
    cell_site: np.ndarray        # (n_cells,) index into sites
    cell_azimuth: np.ndarray     # (n_cells,) degrees
    controllable: np.ndarray     # (n_cells,) bool

    def cell_index(self, cell_id: str) -> int:
        return self.cell_ids.index(cell_id)


def _hex_ring(k: int) -> list[tuple[int, int]]:
    """Axial coordinates of ring k, walking around the ring in a fixed order."""
    if k == 0:
        return [(0, 0)]
    directions = [(1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1)]
    q, r = -k, k   # start at direction 4 scaled by k
    out = []
    for dq, dr in directions:
        for _ in range(k):
            out.append((q, r))
            q, r = q + dq, r + dr
    return out


def build_layout(cfg: NetworkConfig) -> Layout:
    lay = cfg.layout
    isd = float(lay["isd_m"])
    azimuths = [float(a) for a in lay["sector_azimuths_deg"]]

    site_ids, xy, ring = [], [], []
    n = 0
    for k in range(int(lay["rings"]) + 1):
        for q, r in _hex_ring(k):
            site_ids.append(f"S{n:02d}")
            xy.append((isd * (q + r / 2.0), isd * (np.sqrt(3) / 2.0) * r))
            ring.append(k)
            n += 1

    cell_ids, cell_site, cell_az, ctrl = [], [], [], []
    for s, sid in enumerate(site_ids):
        for i, az in enumerate(azimuths):
            cell_ids.append(f"{sid}-{SECTOR_LETTERS[i]}")
            cell_site.append(s)
            cell_az.append(az)
            ctrl.append(ring[s] <= int(lay["controllable_rings"]))

    return Layout(
        site_ids=site_ids,
        site_xy=np.asarray(xy, dtype=float),
        site_ring=np.asarray(ring, dtype=int),
        cell_ids=cell_ids,
        cell_site=np.asarray(cell_site, dtype=int),
        cell_azimuth=np.asarray(cell_az, dtype=float),
        controllable=np.asarray(ctrl, dtype=bool),
    )
