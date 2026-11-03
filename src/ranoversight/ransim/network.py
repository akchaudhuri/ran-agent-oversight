# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Aditya Chaudhuri
"""The Network: state, changes, rollback, KPIs and alarms.

Simplifications (also stated in the README):
- Static users, one carrier, downlink only, no fading or mobility.
- Shadowing is one draw per user and site, fixed by the seed, uncorrelated.
- Outer-ring cells carry a fixed background load plus any simulated users
  they serve; only central users are simulated.
- Throughput is the Shannon rate (scaled by an efficiency factor) shared
  equally among the active users on a cell.
"""

from __future__ import annotations

import copy
from dataclasses import replace

import numpy as np

from . import radio
from .config import NetworkConfig, load_config
from .layout import Layout, build_layout
from .types import (
    Alarm,
    CellConfig,
    CellKPI,
    Change,
    ChangeRecord,
    ChangeRejected,
    KPISnapshot,
    NetworkState,
    ZoneKPI,
)
from .users import HOURS, Users, place_users

_PARAM_FIELD = {"tilt": "tilt_deg", "power": "power_dbm", "cio": "cio_db"}
_PARAM_LIMIT = {"tilt": "tilt_deg", "power": "power_dbm", "cio": "cio_db"}


class Network:
    def __init__(self, cfg: NetworkConfig | None = None, seed: int = 0, start_hour: int = 0):
        self.cfg = cfg or load_config()
        self.seed = int(seed)
        rng = np.random.default_rng(self.seed)

        self.layout: Layout = build_layout(self.cfg)
        self.users: Users = place_users(self.cfg, rng)
        self._geo = radio.geometry(self.users.xy, self.layout, self.cfg)

        n_sites = len(self.layout.site_ids)
        shadow = rng.normal(0.0, self.cfg.radio["shadowing_db"], size=(self.users.n, n_sites))
        self._extra_loss = shadow + self.users.indoor_loss_db[:, None]

        d = self.cfg.defaults
        self._cells: dict[str, CellConfig] = {
            c: CellConfig(float(d["tilt_deg"]), float(d["power_dbm"]), float(d["cio_db"]))
            for c in self.layout.cell_ids
        }
        self._down: set[str] = set()
        self._thresholds = {name: r.threshold for name, r in self.cfg.alarm_rules.items()}
        self._log: list[ChangeRecord] = []
        self._hour = self._check_hour(start_hour)
        self._version = 0
        self._cache: dict[tuple[int, int], KPISnapshot] = {}

        base = np.where(self.layout.controllable, 0.0, self.cfg.radio["outer_cell_base_load"])
        self._base_load = base

    # ------------------------------------------------------------------ queries

    @property
    def hour(self) -> int:
        return self._hour

    def cell_ids(self, controllable_only: bool = True) -> list[str]:
        ids = self.layout.cell_ids
        if not controllable_only:
            return list(ids)
        return [c for c, ok in zip(ids, self.layout.controllable) if ok]

    def config(self, cell_id: str) -> CellConfig:
        return self._cells[cell_id]

    def is_up(self, cell_id: str) -> bool:
        return cell_id.split("-")[0] not in self._down

    def alarm_threshold(self, name: str) -> float:
        return self._thresholds[name]

    def log(self) -> list[ChangeRecord]:
        return list(self._log)

    def kpis(self) -> KPISnapshot:
        return self._snapshot(self._hour)

    def kpis_at(self, hour: int) -> KPISnapshot:
        """KPIs at another hour with the current configuration. Changes nothing."""
        return self._snapshot(self._check_hour(hour))

    def alarms(self) -> list[Alarm]:
        return self._alarms(self.kpis())

    def alarms_at(self, hour: int) -> list[Alarm]:
        return self._alarms(self.kpis_at(hour))

    # ------------------------------------------------------------------ changes

    def apply(self, change: Change) -> ChangeRecord:
        if change.param == "alarm_threshold":
            return self._apply_threshold(change)
        if change.param not in _PARAM_FIELD:
            raise ChangeRejected(f"unknown parameter {change.param!r}")
        cid = change.cell_id
        if cid not in self._cells:
            raise ChangeRejected(f"unknown cell {cid!r}")
        if not self.layout.controllable[self.layout.cell_index(cid)]:
            raise ChangeRejected(f"cell {cid} is outside the managed area and cannot be changed")
        if not self.is_up(cid):
            raise ChangeRejected(f"cell {cid} is down")

        lo, hi = self.cfg.limits[_PARAM_LIMIT[change.param]]
        value = float(change.value)
        if not (lo <= value <= hi):
            raise ChangeRejected(f"{change.param} {value} outside hardware range [{lo}, {hi}]")

        warnings: list[str] = []
        cap = float(self.cfg.limits["policy_power_cap_dbm"])
        if change.param == "power" and value > cap:
            warnings.append(f"power {value:g} dBm is above the policy cap of {cap:g} dBm")

        field = _PARAM_FIELD[change.param]
        old = getattr(self._cells[cid], field)
        self._cells[cid] = replace(self._cells[cid], **{field: value})
        return self._record(cid, None, change.param, old, value, change.reason, tuple(warnings))

    def rollback(self, change_id: str, reason: str) -> ChangeRecord:
        rec = next((r for r in self._log if r.change_id == change_id), None)
        if rec is None:
            raise ChangeRejected(f"no change {change_id!r}")
        if rec.param == "alarm_threshold":
            old = self._thresholds[rec.target]
            self._thresholds[rec.target] = rec.old
            return self._record(None, rec.target, rec.param, old, rec.old, reason, (), change_id)
        if not self.is_up(rec.cell_id):
            raise ChangeRejected(f"cell {rec.cell_id} is down")
        field = _PARAM_FIELD[rec.param]
        old = getattr(self._cells[rec.cell_id], field)
        self._cells[rec.cell_id] = replace(self._cells[rec.cell_id], **{field: rec.old})
        return self._record(rec.cell_id, None, rec.param, old, rec.old, reason, (), change_id)

    def advance(self, hours: int) -> None:
        if hours < 1:
            raise ValueError("hours must be at least 1")
        self._hour = self._check_hour(self._hour + int(hours))
        # KPIs depend on hour only through the cache key; no invalidation needed.

    def set_site_down(self, site_id: str) -> None:
        """Scenario event (used by task setup), not an operator change. Not logged."""
        if site_id not in self.layout.site_ids:
            raise ValueError(f"unknown site {site_id!r}")
        self._down.add(site_id)
        self._bump()

    # ------------------------------------------------------------------ state

    def state(self) -> NetworkState:
        return NetworkState(
            seed=self.seed,
            hour=self._hour,
            cells=dict(self._cells),
            down_sites=sorted(self._down),
            alarm_thresholds=dict(self._thresholds),
            log=list(self._log),
        )

    @classmethod
    def from_state(cls, cfg: NetworkConfig, state: NetworkState) -> "Network":
        net = cls(cfg, seed=state.seed, start_hour=state.hour)
        net._cells = dict(state.cells)
        net._down = set(state.down_sites)
        net._thresholds = dict(state.alarm_thresholds)
        net._log = list(state.log)
        net._bump()
        return net

    def copy(self) -> "Network":
        return copy.deepcopy(self)

    # ------------------------------------------------------------------ maps (plots only)

    def rsrp_map(self, points_xy: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Best RSRP and best cell at arbitrary outdoor points, no shadowing."""
        geo = radio.geometry(points_xy, self.layout, self.cfg)
        zero = np.zeros((len(points_xy), len(self.layout.site_ids)))
        rx = self._rx_dbm(geo, zero) - radio.rsrp_offset_db(self.cfg)
        cio = np.array([self._cells[c].cio_db for c in self.layout.cell_ids])
        best = np.argmax(rx + cio[None, :], axis=1)
        return rx[np.arange(len(points_xy)), best], best

    # ------------------------------------------------------------------ internals

    def _check_hour(self, hour: int) -> int:
        if not (0 <= hour < HOURS):
            raise ValueError(f"hour {hour} outside 0..{HOURS - 1}")
        return int(hour)

    def _bump(self) -> None:
        self._version += 1
        self._cache.clear()

    def _record(self, cell_id, target, param, old, new, reason, warnings, rollback_of=None) -> ChangeRecord:
        rec = ChangeRecord(
            change_id=f"chg-{len(self._log) + 1:04d}",
            hour=self._hour,
            cell_id=cell_id,
            target=target,
            param=param,
            old=float(old),
            new=float(new),
            reason=str(reason),
            warnings=warnings,
            is_rollback_of=rollback_of,
        )
        self._log.append(rec)
        self._bump()
        return rec

    def _apply_threshold(self, change: Change) -> ChangeRecord:
        rule = self.cfg.alarm_rules.get(change.target or "")
        if rule is None:
            raise ChangeRejected(f"unknown alarm rule {change.target!r}")
        value = float(change.value)
        if not (rule.low <= value <= rule.high):
            raise ChangeRejected(f"threshold {value} outside [{rule.low}, {rule.high}] for {rule.name}")
        old = self._thresholds[rule.name]
        self._thresholds[rule.name] = value
        return self._record(None, rule.name, "alarm_threshold", old, value, change.reason, ())

    def _arrays(self) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        ids = self.layout.cell_ids
        tilt = np.array([self._cells[c].tilt_deg for c in ids])
        power = np.array([self._cells[c].power_dbm for c in ids])
        cio = np.array([self._cells[c].cio_db for c in ids])
        up = np.array([self.is_up(c) for c in ids])
        return tilt, power, cio, up

    def _rx_dbm(self, geo: radio.Geometry, extra_loss: np.ndarray) -> np.ndarray:
        tilt, power, _, up = self._arrays()
        rx = radio.rx_power_dbm(geo, power, tilt, extra_loss, self.layout, self.cfg)
        return np.where(up[None, :], rx, -np.inf)

    def _snapshot(self, hour: int) -> KPISnapshot:
        key = (self._version, hour)
        if key in self._cache:
            return self._cache[key]

        r = self.cfg.radio
        ids = self.layout.cell_ids
        tilt, power, cio, up = self._arrays()
        u = self.users

        rx_dbm = self._rx_dbm(self._geo, self._extra_loss)
        rsrp = rx_dbm - radio.rsrp_offset_db(self.cfg)
        serving = np.argmax(rsrp + cio[None, :], axis=1)
        idx = np.arange(u.n)
        covered = rsrp[idx, serving] >= r["coverage_rsrp_dbm"]

        active = u.active[hour]
        demanding = active & covered
        rx_mw = radio.db_to_mw(rx_dbm)          # -inf dBm -> 0 mW for down cells
        sol = radio.solve_loads(rx_mw, serving, demanding, self._base_load, up, self.cfg)

        n_cells = len(ids)
        per_cell_users = np.bincount(serving[demanding], minlength=n_cells)
        rate_mbps = r["shannon_efficiency"] * r["bandwidth_mhz"] * np.log2(1.0 + sol.sinr)
        share = np.maximum(per_cell_users[serving], 1)
        tput = np.where(demanding, rate_mbps / share, 0.0)    # Mbps; uncovered active users get 0

        def p5(x: np.ndarray) -> float:
            return float(np.percentile(x, 5)) if x.size else 0.0

        def mean(x: np.ndarray) -> float:
            return float(np.mean(x)) if x.size else 0.0

        sinr_db = radio.mw_to_db(np.maximum(sol.sinr, 1e-30))
        poor = int(np.sum(demanding & (sinr_db < r["poor_sinr_db"])))
        ctrl = self.layout.controllable
        total_w = float(np.sum(np.where(ctrl & up, radio.db_to_mw(power) / 1000.0, 0.0)))

        per_cell: dict[str, CellKPI] = {}
        for j, cid in enumerate(ids):
            if not ctrl[j]:
                continue
            on = demanding & (serving == j)
            per_cell[cid] = CellKPI(
                load=float(sol.loads[j]),
                active_users=int(per_cell_users[j]),
                tput_mean_mbps=mean(tput[on]),
                tilt_deg=float(tilt[j]),
                power_dbm=float(power[j]),
                cio_db=float(cio[j]),
                up=bool(up[j]),
            )

        per_zone: dict[str, ZoneKPI] = {}
        for zid in self.cfg.zones:
            inz = u.zone == zid
            act = inz & active
            per_zone[zid] = ZoneKPI(
                coverage_pct=100.0 * float(np.mean(covered[inz])) if inz.any() else 0.0,
                tput_p5_mbps=p5(tput[act]),
                tput_mean_mbps=mean(tput[act]),
                active_users=int(act.sum()),
            )

        snap = KPISnapshot(
            hour=hour,
            coverage_pct=100.0 * float(np.mean(covered)),
            tput_mean_mbps=mean(tput[active]),
            tput_p5_mbps=p5(tput[active]),
            poor_sinr_users=poor,
            active_users=int(active.sum()),
            total_power_w=total_w,
            load_converged=sol.converged,
            per_cell=per_cell,
            per_zone=per_zone,
        )
        self._cache[key] = snap
        return snap

    def _alarms(self, k: KPISnapshot) -> list[Alarm]:
        out: list[Alarm] = []
        cov_thr = self._thresholds.get("zone_coverage_low")
        if cov_thr is not None:
            for zid, z in k.per_zone.items():
                if z.coverage_pct < cov_thr:
                    out.append(Alarm("zone_coverage_low", zid, z.coverage_pct, cov_thr))
        load_thr = self._thresholds.get("cell_load_high")
        if load_thr is not None:
            for cid, c in k.per_cell.items():
                if c.up and c.load > load_thr:
                    out.append(Alarm("cell_load_high", cid, c.load, load_thr))
        return out
