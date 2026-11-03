#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Aditya Chaudhuri
#
# The full run matrix from PREREGISTRATION.md section 3, then monitor scoring.
# Model runs go to runs/model, scripted runs to runs/scripted. Safe to stop and
# rerun a stage: each stage writes new run files, so delete a stage's output
# before repeating it. Needs ANTHROPIC_API_KEY in .env.
#
# Usage: bash scripts/run_all.sh [model|scripted|score|all]   (default: all)

set -euo pipefail
STAGE="${1:-all}"
RUN="python -m ranoversight.run --display plain"
H="101 102 103 104 105 106 107 108 109 110 111 112 113 114 115"
A8="201 202 203 204 205 206 207 208"
A4="201 202 203 204"
A3="201 202 203"

model() {
  M="--runs-dir runs/model --log-dir logs/model"
  $RUN $M --mode honest --honest-seeds $H                                                              # 45
  $RUN $M --mode attack --pairing outage:zone_degrade stadium:zone_degrade energy:zone_degrade --attack-seeds $A8  # 24
  $RUN $M --mode attack --pairing outage:time_bomb energy:time_bomb --attack-seeds $A8               # 16
  $RUN $M --mode attack --pairing outage:overpower stadium:overpower --attack-seeds $A3              # 6
  $RUN $M --mode attack --pairing outage:alarm_suppress stadium:alarm_suppress --attack-seeds $A3    # 6
  $RUN $M --mode attack --named-zones --pairing outage:zone_degrade stadium:zone_degrade energy:zone_degrade --attack-seeds $A4  # 12
  $RUN $M --mode attack --pairing outage:covert_sinr_inflation stadium:covert_sinr_inflation --attack-seeds $A4   # 8
}

scripted() {
  # Fallback condition (PREREGISTRATION.md section 3). No API calls. Compared only
  # with scripted honest runs, never pooled with model runs.
  S="--policy scripted --runs-dir runs/scripted --log-dir logs/scripted"
  $RUN $S --mode honest --honest-seeds $H
  $RUN $S --mode attack --pairing outage:zone_degrade stadium:zone_degrade energy:zone_degrade outage:time_bomb energy:time_bomb --attack-seeds $A8
  $RUN $S --mode attack --pairing outage:overpower stadium:overpower outage:alarm_suppress stadium:alarm_suppress --attack-seeds $A3
}

score() {
  python -m ranoversight.score --runs-dir runs/model --out results/scores_model.jsonl --monitors M0 M1 M2 M3 M4
  python -m ranoversight.score --runs-dir runs/scripted --out results/scores_scripted.jsonl --monitors M0 M1 M2 M3 M4
}

case "$STAGE" in
  model) model ;;
  scripted) scripted ;;
  score) score ;;
  all) model; scripted; score ;;
  *) echo "unknown stage $STAGE"; exit 1 ;;
esac
echo "Stage '$STAGE' finished."
