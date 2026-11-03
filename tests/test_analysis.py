# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Aditya Chaudhuri
"""Analysis metrics (ARCHITECTURE.md tests 25, 26)."""

from __future__ import annotations

import numpy as np
import pytest

from ranoversight.analysis.metrics import auroc, bootstrap_ci, catch_at_fpr, rate_ci, threshold_at_fpr


# 25
def test_auroc_known_values():
    assert auroc([0, 1, 2], [3, 4, 5]) == 1.0
    assert auroc([3, 4, 5], [0, 1, 2]) == 0.0
    assert auroc([1, 1], [1, 1]) == 0.5
    assert auroc([0, 2], [1, 3]) == pytest.approx(0.75)


def test_threshold_keeps_false_alarms_at_or_below_target():
    honest = list(range(100))                      # 0..99
    t = threshold_at_fpr(honest, 0.05)
    assert np.mean(np.array(honest) > t) <= 0.05
    assert t == 94


def test_catch_rate_known_values():
    honest = [0] * 19 + [50]                      # 1 of 20 honest runs scores 50: exactly 5%
    catch, fpr, t = catch_at_fpr(honest, [10, 60, 70, 40], 0.05)
    assert t == 0 and fpr == pytest.approx(0.05) and catch == 1.0
    catch, fpr, t = catch_at_fpr([0] * 18 + [50, 50], [10, 60, 70, 40], 0.05)   # 10% at 0, so threshold moves to 50
    assert t == 50 and fpr == 0.0 and catch == 0.5


def test_ties_with_the_threshold_are_not_flagged():
    catch, _, t = catch_at_fpr([5] * 20, [5, 5, 6], 0.05)
    assert t == 5 and catch == pytest.approx(1 / 3)


# 26
def test_bootstrap_interval_covers_the_true_auroc_most_of_the_time():
    rng = np.random.default_rng(1)
    true = 0.76                                   # P(N(1,1) > N(0,1)) = Phi(1/sqrt 2)
    covered = 0
    for i in range(200):
        h = rng.normal(0, 1, 40)
        a = rng.normal(1, 1, 40)
        lo, hi = bootstrap_ci(auroc, h, a, n=300, seed=i)
        covered += lo <= true <= hi
    assert covered >= 180


def test_wilson_interval():
    lo, hi = rate_ci(0, 10)
    assert lo == 0.0 and 0.25 < hi < 0.35
    lo, hi = rate_ci(5, 10)
    assert lo < 0.5 < hi
