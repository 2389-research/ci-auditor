#!/bin/sh
# ABOUTME: Runs one scenario several times against one skill version, one trial after another.
# ABOUTME: Use it to get the 5 or more repetitions a wording comparison needs.
#
# usage: sh evals/run_reps.sh SKILL_DIR SCENARIO_FILE OUT_ROOT LABEL FIRST LAST [MODEL]
#   writes OUT_ROOT/LABEL-<scenario>-r<N>/ for N from FIRST to LAST
set -eu
if [ $# -lt 6 ]; then
  sed -n '5,6p' "$0" >&2
  exit 2
fi
name=$(basename "$2" .txt)
n=$4
i=$5
while [ "$i" -le "$6" ]; do
  sh "$(dirname "$0")/run_trial.sh" "$1" "$2" "$3/$n-$name-r$i" ${7:-sonnet}
  i=$((i + 1))
done
