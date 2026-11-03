# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Aditya Chaudhuri
"""Analysis: per-run table, detection metrics, summary tables and plots."""

from .metrics import auroc, bootstrap_ci, catch_at_fpr, rate_ci, threshold_at_fpr

__all__ = ["auroc", "bootstrap_ci", "catch_at_fpr", "rate_ci", "threshold_at_fpr"]
