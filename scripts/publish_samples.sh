#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Aditya Chaudhuri
#
# Copy the six example transcripts named in the README into runs/sample,
# which is the only part of runs/ that is published. Run IDs are from the
# main run of 3 November 2026 (see results/runs.csv).

set -euo pipefail
mkdir -p runs/sample
declare -A SAMPLES=(
  [model_partial_attempt]="runs/model/689781c9396d404490108dc9ee126b17.jsonl"
  [model_declined]="runs/model/c6fd64ad9c50499da677b1d68fc99e11.jsonl"
  [model_blocked]="runs/model/6da6b9d1c76644b38a338023a98b00ad.jsonl"
  [model_honest]="runs/model/325d61d33d2249489a85b92193c27b0c.jsonl"
  [scripted_time_bomb]="runs/scripted/0af186c1b7c44dc2b7ce69c420f2808d.jsonl"
  [scripted_hospital_stadium]="runs/scripted/b969eb62c9fb499984d4745551896589.jsonl"
)
for name in "${!SAMPLES[@]}"; do
  cp "${SAMPLES[$name]}" "runs/sample/${name}.jsonl"
  echo "runs/sample/${name}.jsonl"
done
