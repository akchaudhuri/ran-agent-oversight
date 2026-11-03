# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Aditya Chaudhuri
"""ControlArena adapter. The only part of the project that imports ControlArena."""

from .setting import ATTACK_PROMPT_FILE, RanOversightSetting, operator_brief, ran_main_task_scorer, ran_side_task_scorer

__all__ = ["ATTACK_PROMPT_FILE", "RanOversightSetting", "operator_brief", "ran_main_task_scorer", "ran_side_task_scorer"]
