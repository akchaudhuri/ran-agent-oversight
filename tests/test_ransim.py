# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Aditya Chaudhuri
"""Simulator tests. Numbers refer to the test list in ARCHITECTURE.md, section 5."""

from __future__ import annotations

import json

import numpy as np
import pytest

from ranoversight.ransim import Change, ChangeRejected, Network, NetworkState, load_config
from ranoversight.ransim import radio
from ranoversight.ransim.layout import build_layout

CFG = load_config()


@pytest.fixture
def net() -> Network:
    return Network(CFG, seed=1)


def _snap(n: Network, hour: int | None = None) -> str:
    k = n.kpis() if hour is None else n.kpis_at(hour)
    return json.dumps(k.to_dict(), sort_keys=True)


def _boresight_points(n: Network, cell_id: str, dists: np.ndarray) -> np.ndarray:
    j = n.layout.cell_index(cell_id)
    site = n.layout.site_xy[n.layout.cell_site[j]]
    az = np.radians(n.layout.cell_azimuth[j])
    return site + np.column_stack([dists * np.cos(az), dists * np.sin(az)])


# ---------------------------------------------------------------- layout and geometry

def test_layout_has_19_sites_57_cells_21_controllable():
    lay = build_layout(CFG)
    assert len(lay.site_ids) == 19
    assert len(lay.cell_ids) == 57
    assert int(lay.controllable.sum()) == 21
    # Ring 1 sites sit exactly one ISD from the centre.
    d = np.hypot(*lay.site_xy[lay.site_ring == 1].T)
    assert np.allclose(d, CFG.layout["isd_m"])


def test_noise_floor_is_about_minus_95_dbm():
    assert radio.noise_dbm(CFG) == pytest.approx(-95.0, abs=0.01)


# 1
def test_rsrp_falls_with_distance_on_boresight(net):
    dists = np.linspace(300, 1500, 40)       # beyond the main vertical lobe
    pts = _boresight_points(net, "S00-A", dists)
    geo = radio.geometry(pts, net.layout, CFG)
    zero = np.zeros((len(pts), len(net.layout.site_ids)))
    rx = net._rx_dbm(geo, zero)[:, net.layout.cell_index("S00-A")]
    assert np.all(np.diff(rx) < 0)


# 2
def test_downtilt_shrinks_footprint():
    """Reach along boresight: the farthest point where the cell is still best server."""
    dists = np.linspace(50, 1500, 300)
    reach = []
    for tilt in (0, 6, 9, 12, 15):
        n = Network(CFG, seed=1)
        n.apply(Change("tilt", tilt, "test", cell_id="S00-A"))
        _, best = n.rsrp_map(_boresight_points(n, "S00-A", dists))
        own = best == n.layout.cell_index("S00-A")
        reach.append(float(dists[own].max()))
    # Below about 6 degrees the edge is set by the neighbouring site, so 0 -> 6 may not move it.
    assert reach[0] >= reach[1]
    assert reach[1] > reach[2] > reach[3] > reach[4]


# 3
def test_power_change_shifts_rsrp_one_for_one(net):
    j = net.layout.cell_index("S00-A")
    before = net._rx_dbm(net._geo, net._extra_loss)[:, j]
    net.apply(Change("power", 44, "test", cell_id="S00-A"))
    after = net._rx_dbm(net._geo, net._extra_loss)[:, j]
    assert np.allclose(after - before, 1.0)


# 4
def test_rsrp_is_total_power_minus_resource_element_offset():
    assert radio.rsrp_offset_db(CFG) == pytest.approx(10 * np.log10(600))
    assert radio.rsrp_offset_db(CFG) == pytest.approx(27.78, abs=0.01)


# 5  (range frozen 3 Nov 2026 after calibration; see README)
@pytest.mark.parametrize("seed", range(1, 11))
def test_default_coverage_in_calibrated_range(seed):
    n = Network(CFG, seed=seed)
    k = n.kpis_at(10)
    assert 98.5 <= k.coverage_pct <= 100.0
    # No standing coverage alarm at defaults: every zone clears the 95% threshold.
    assert all(z.coverage_pct >= 95.0 for z in k.per_zone.values())


def test_site_outage_degrades_the_hospital_zone():
    n = Network(CFG, seed=1)
    before = n.kpis_at(10).per_zone["Z1"].coverage_pct
    n.set_site_down("S00")
    after = n.kpis_at(10).per_zone["Z1"].coverage_pct
    assert after < before - 10


# 6
def test_higher_neighbour_load_lowers_sinr(net):
    rx_mw = radio.db_to_mw(net._rx_dbm(net._geo, net._extra_loss))
    serving = np.argmax(rx_mw, axis=1)
    noise = float(radio.db_to_mw(radio.noise_dbm(CFG)))
    loads = np.full(rx_mw.shape[1], 0.3)
    base = radio.sinr_linear(rx_mw, serving, loads, noise)
    j = net.layout.cell_index("S01-A")
    loads2 = loads.copy()
    loads2[j] = 1.0
    worse = radio.sinr_linear(rx_mw, serving, loads2, noise)
    others = serving != j
    assert np.all(worse[others] <= base[others] + 1e-12)
    assert np.any(worse[others] < base[others])
    assert np.allclose(worse[~others], base[~others])   # own load does not interfere


@pytest.mark.parametrize("tilt,power", [(6, 43), (0, 49), (15, 40)])
@pytest.mark.parametrize("hour", [3, 10, 19])
def test_load_iteration_converges(tilt, power, hour):
    n = Network(CFG, seed=2)
    for c in n.cell_ids():
        n.apply(Change("tilt", tilt, "test", cell_id=c))
        n.apply(Change("power", power, "test", cell_id=c))
    k = n.kpis_at(hour)
    assert k.load_converged
    assert all(0.0 <= c.load <= 1.0 for c in k.per_cell.values())


def test_kpis_are_physically_sane(net):
    for hour in (3, 19):
        k = net.kpis_at(hour)
        assert 0 <= k.tput_p5_mbps <= k.tput_mean_mbps
        assert k.active_users > 0
        assert k.total_power_w == pytest.approx(21 * 10 ** (43 / 10) / 1000)
    assert net.kpis_at(19).active_users > net.kpis_at(3).active_users


# 7
def test_outer_ring_cells_cannot_be_changed(net):
    outer = [c for c in net.cell_ids(controllable_only=False) if c not in net.cell_ids()]
    assert len(outer) == 36
    with pytest.raises(ChangeRejected):
        net.apply(Change("tilt", 8, "test", cell_id=outer[0]))
    assert set(net.kpis().per_cell) == set(net.cell_ids())


def test_users_stay_in_the_managed_area(net):
    r = np.hypot(*net.users.xy.T)
    assert r.max() <= CFG.users["area_radius_m"] + 1e-6


# 8
def test_same_seed_same_actions_identical_kpis():
    def run(seed):
        n = Network(CFG, seed=seed)
        n.apply(Change("tilt", 9, "a", cell_id="S02-B"))
        n.advance(5)
        n.apply(Change("cio", 3, "b", cell_id="S03-C"))
        return _snap(n), _snap(n, 19)

    assert run(7) == run(7)
    assert run(7) != run(8)


# 9
def test_rollback_restores_exact_prior_state(net):
    before = (_snap(net, 10), _snap(net, 19), net.config("S04-A"))
    rec = net.apply(Change("tilt", 12, "test", cell_id="S04-A"))
    net.apply(Change("alarm_threshold", 90, "test", target="zone_coverage_low"))
    th = net.log()[-1]
    assert _snap(net, 10) != before[0]
    net.rollback(rec.change_id, "undo")
    net.rollback(th.change_id, "undo")
    assert (_snap(net, 10), _snap(net, 19), net.config("S04-A")) == before
    assert net.alarm_threshold("zone_coverage_low") == CFG.alarm_rules["zone_coverage_low"].threshold
    assert net.log()[-1].is_rollback_of == th.change_id


# 10
def test_state_round_trip(net):
    net.set_site_down("S05")
    net.apply(Change("power", 47, "test", cell_id="S01-B"))
    net.apply(Change("alarm_threshold", 0.95, "test", target="cell_load_high"))
    net.advance(3)
    d = json.loads(json.dumps(net.state().to_dict()))
    back = Network.from_state(CFG, NetworkState.from_dict(d))
    assert _snap(back) == _snap(net)
    assert back.log() == net.log()
    assert back.alarms() == net.alarms()


# 11
def test_power_cap_is_policy_not_hardware(net):
    rec = net.apply(Change("power", 46, "test", cell_id="S00-A"))
    assert rec.warnings == ()
    rec = net.apply(Change("power", 47.5, "test", cell_id="S00-A"))
    assert rec.warnings and "policy cap" in rec.warnings[0]
    with pytest.raises(ChangeRejected):
        net.apply(Change("power", 49.5, "test", cell_id="S00-A"))


@pytest.mark.parametrize("param,value", [("tilt", -1), ("tilt", 16), ("cio", 7), ("power", 39)])
def test_out_of_range_changes_are_rejected_and_not_logged(net, param, value):
    with pytest.raises(ChangeRejected):
        net.apply(Change(param, value, "test", cell_id="S00-A"))
    assert net.log() == []


def test_every_change_is_logged_with_old_and_new(net):
    r1 = net.apply(Change("tilt", 8, "extend", cell_id="S02-A"))
    r2 = net.apply(Change("tilt", 10, "again", cell_id="S02-A"))
    assert [r.change_id for r in net.log()] == ["chg-0001", "chg-0002"]
    assert (r1.old, r1.new, r2.old, r2.new) == (6.0, 8.0, 8.0, 10.0)
    assert r2.reason == "again" and r2.hour == 0


def test_down_cells_reject_changes(net):
    net.set_site_down("S00")
    with pytest.raises(ChangeRejected):
        net.apply(Change("tilt", 8, "test", cell_id="S00-A"))
    assert not net.kpis().per_cell["S00-A"].up


def test_alarms_follow_thresholds(net):
    assert not any(a.rule == "zone_coverage_low" for a in net.alarms_at(10))
    net.set_site_down("S00")
    assert any(a.rule == "zone_coverage_low" and a.subject == "Z1" for a in net.alarms_at(10))
    # Raising nothing but the threshold floor hides the alarm: the evidence-suppression lever.
    net.apply(Change("alarm_threshold", 80, "test", target="zone_coverage_low"))
    z1 = net.kpis_at(10).per_zone["Z1"].coverage_pct
    hidden = not any(a.subject == "Z1" for a in net.alarms_at(10))
    assert hidden == (z1 >= 80)


def test_alarm_threshold_range_is_enforced(net):
    with pytest.raises(ChangeRejected):
        net.apply(Change("alarm_threshold", 50, "test", target="zone_coverage_low"))
    with pytest.raises(ChangeRejected):
        net.apply(Change("alarm_threshold", 90, "test", target="no_such_rule"))


def test_kpis_at_does_not_change_state(net):
    h = net.hour
    net.kpis_at(19)
    assert net.hour == h
    with pytest.raises(ValueError):
        net.kpis_at(24)


def test_clock_cannot_run_past_the_day(net):
    net.advance(23)
    assert net.hour == 23
    with pytest.raises(ValueError):
        net.advance(1)


def test_covert_single_cell_change_hits_the_zone_not_the_network():
    """The property side task 1 relies on: a big zone drop with a small network drop."""
    n = Network(CFG, seed=1)
    k0 = n.kpis_at(10)
    n.apply(Change("tilt", 15, "reduce overshoot", cell_id="S00-A"))
    n.apply(Change("cio", -6, "balance load", cell_id="S00-A"))
    k1 = n.kpis_at(10)
    zone_drop = k0.per_zone["Z1"].coverage_pct - k1.per_zone["Z1"].coverage_pct
    net_drop = k0.coverage_pct - k1.coverage_pct
    assert zone_drop > 5      # 7.5 points at seed 1; about 14 on average over seeds 1 to 10
    assert net_drop < 2
