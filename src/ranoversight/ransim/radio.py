# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Aditya Chaudhuri
"""Radio model: path loss, 3GPP-style sector antenna, RSRP, load-coupled SINR.

All functions are pure. Arrays are (users, cells) unless stated otherwise.
Powers are in dBm (log) or mW (linear); the suffix says which.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .config import NetworkConfig
from .layout import Layout


def db_to_mw(x_dbm: np.ndarray | float) -> np.ndarray:
    return np.power(10.0, np.asarray(x_dbm) / 10.0)


def mw_to_db(x_mw: np.ndarray | float) -> np.ndarray:
    with np.errstate(divide="ignore"):
        return 10.0 * np.log10(np.asarray(x_mw))


def noise_dbm(cfg: NetworkConfig) -> float:
    r = cfg.radio
    return -174.0 + 10.0 * np.log10(r["bandwidth_mhz"] * 1e6) + r["noise_figure_db"]


def rsrp_offset_db(cfg: NetworkConfig) -> float:
    """Total received power minus RSRP (power per resource element)."""
    return 10.0 * np.log10(cfg.radio["subcarriers"])


def pathloss_db(dist_m: np.ndarray, cfg: NetworkConfig) -> np.ndarray:
    pl = cfg.radio["pathloss"]
    d = np.maximum(dist_m, pl["min_dist_m"]) / 1000.0
    return pl["a"] + pl["b"] * np.log10(d)


@dataclass(frozen=True)
class Geometry:
    """Config-independent geometry for a set of points (users or a map grid)."""

    dist_m: np.ndarray        # (n, sites) ground distance
    elev_deg: np.ndarray      # (n, sites) angle below horizon from the antenna
    horiz_att_db: np.ndarray  # (n, cells) horizontal pattern, <= 0


def geometry(points_xy: np.ndarray, layout: Layout, cfg: NetworkConfig) -> Geometry:
    lay, ant = cfg.layout, cfg.radio["antenna"]
    diff = points_xy[:, None, :] - layout.site_xy[None, :, :]          # (n, sites, 2)
    dist = np.hypot(diff[..., 0], diff[..., 1])
    elev = np.degrees(np.arctan2(lay["bs_height_m"] - lay["ue_height_m"], np.maximum(dist, 1.0)))

    bearing = np.degrees(np.arctan2(diff[..., 1], diff[..., 0]))       # (n, sites)
    phi = bearing[:, layout.cell_site] - layout.cell_azimuth[None, :]  # (n, cells)
    phi = (phi + 180.0) % 360.0 - 180.0
    horiz = -np.minimum(12.0 * (phi / ant["h_bw_deg"]) ** 2, ant["max_att_db"])
    return Geometry(dist_m=dist, elev_deg=elev, horiz_att_db=horiz)


def antenna_gain_db(geo: Geometry, tilt_deg: np.ndarray, layout: Layout, cfg: NetworkConfig) -> np.ndarray:
    """Total antenna gain toward each point, (n, cells). tilt_deg is (cells,)."""
    ant = cfg.radio["antenna"]
    theta = geo.elev_deg[:, layout.cell_site]                          # (n, cells)
    vert = -np.minimum(12.0 * ((theta - tilt_deg[None, :]) / ant["v_bw_deg"]) ** 2, ant["max_att_db"])
    combined = -np.minimum(-(geo.horiz_att_db + vert), ant["max_att_db"])
    return ant["gain_dbi"] + combined


def rx_power_dbm(
    geo: Geometry,
    power_dbm: np.ndarray,       # (cells,)
    tilt_deg: np.ndarray,        # (cells,)
    extra_loss_db: np.ndarray,   # (n, sites): shadowing + indoor loss; zeros for a clean map
    layout: Layout,
    cfg: NetworkConfig,
) -> np.ndarray:
    """Total received power from each cell (whole carrier), (n, cells)."""
    pl = pathloss_db(geo.dist_m, cfg) + extra_loss_db                  # (n, sites)
    gain = antenna_gain_db(geo, tilt_deg, layout, cfg)
    return power_dbm[None, :] + gain - pl[:, layout.cell_site]


def sinr_linear(rx_mw: np.ndarray, serving: np.ndarray, loads: np.ndarray, noise_mw: float) -> np.ndarray:
    """SINR for each user given its serving cell and every cell's load.

    Interference from cell j is weighted by its load (fraction of resources in use).
    rx_mw must already be zero for cells that are down.
    """
    n = rx_mw.shape[0]
    idx = np.arange(n)
    signal = rx_mw[idx, serving]
    interference = rx_mw @ loads - loads[serving] * signal
    return signal / (np.maximum(interference, 0.0) + noise_mw)


@dataclass(frozen=True)
class LoadSolution:
    loads: np.ndarray        # (cells,)
    sinr: np.ndarray         # (n,) linear, for every user (meaningful for served users)
    converged: bool
    iterations: int


def solve_loads(
    rx_mw: np.ndarray,
    serving: np.ndarray,          # (n,) serving cell index
    demanding: np.ndarray,        # (n,) bool: active and covered
    base_load: np.ndarray,        # (cells,) fixed background load (outer ring), 0 elsewhere
    up: np.ndarray,               # (cells,) bool
    cfg: NetworkConfig,
) -> LoadSolution:
    """Fixed point of load = demand / capacity under load-weighted interference.

    Starts from full load and iterates downward, which converges monotonically
    for this map. Loads are capped at 1.
    """
    r = cfg.radio
    noise_mw = float(db_to_mw(noise_dbm(cfg)))
    bw_hz = r["bandwidth_mhz"] * 1e6
    eff = r["shannon_efficiency"]
    demand_bps = r["demand_mbps"] * 1e6
    n_cells = rx_mw.shape[1]

    loads = np.where(up, 1.0, 0.0)
    sinr = sinr_linear(rx_mw, serving, loads, noise_mw)
    converged = False
    it = 0
    for it in range(1, int(r["load_iterations"]) + 1):
        rate = eff * bw_hz * np.log2(1.0 + sinr)                         # bps if the user had the whole cell
        need = np.where(demanding, demand_bps / np.maximum(rate, 1.0), 0.0)
        raw = np.bincount(serving, weights=need, minlength=n_cells)
        new = np.where(up, np.minimum(1.0, base_load + raw), 0.0)
        delta = float(np.max(np.abs(new - loads)))
        loads = new
        sinr = sinr_linear(rx_mw, serving, loads, noise_mw)
        if delta < r["load_tolerance"]:
            converged = True
            break
    return LoadSolution(loads=loads, sinr=sinr, converged=converged, iterations=it)
