#!/bin/sh
# ABOUTME: Micro-test of the report wording: a tool-less agent writes the report from a saved
# ABOUTME: script output, under one of three versions of the "Report format" section.
#
# usage: sh evals/micro_report.sh VARIANT REP OUT_ROOT [ORIGINAL_SKILL_MD] [MODEL]
#   VARIANT  shipped   the current SKILL.md
#            control   the current SKILL.md with the "Report format" section removed
#            original  the current SKILL.md with that section taken from ORIGINAL_SKILL_MD
#   writes OUT_ROOT/VARIANT-rREP.md
# The fixture's top jobs meet none of the caveat conditions except judgment calls, so a
# report that lists other caveats is writing caveats whose condition is false.
set -eu
if [ $# -lt 3 ]; then
  sed -n '5,9p' "$0" >&2
  exit 2
fi
here=$(cd "$(dirname "$0")" && pwd -P)
variant=$1
rep=$2
out=$3
original=${4:-}
model=${5:-sonnet}
mkdir -p "$out"
out=$(cd "$out" && pwd -P)
section() { awk '/^## Report format/{f=1} /^## /&&!/^## Report format/{f=0} f' "$1"; }
before() { awk '/^## Report format/{exit} {print}' "$1"; }
prompt="$out/$variant-r$rep.prompt.txt"
{
  echo "Our CI feels slow. Audit the CI timing for rust-lang/cargo over the last 40 runs and tell me where the time goes."
  echo
  before "$here/../SKILL.md"
  case "$variant" in
    shipped) section "$here/../SKILL.md" ;;
    original) section "$original" ;;
    control) ;;
    *) echo "error: unknown variant $variant" >&2; exit 2 ;;
  esac
  echo
  echo "You have completed steps 1 to 3. The script printed the JSON below. Write the report now."
  echo
  cat "$here/fixtures/cargo-40-runs.json"
} > "$prompt"
cd "$out"
unset CLAUDE_CODE_EFFORT_LEVEL
claude -p --safe-mode --model "$model" --tools "" < "$prompt" > "$out/$variant-r$rep.md" 2> "$out/$variant-r$rep.err"
echo "done $variant r$rep"
