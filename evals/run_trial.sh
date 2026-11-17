#!/bin/sh
# ABOUTME: Runs one headless agent trial of this skill against a scenario file.
# ABOUTME: Use it to compare skill versions; it spends Claude subscription quota.
#
# usage: sh evals/run_trial.sh SKILL_DIR SCENARIO_FILE OUT_DIR [MODEL]
#   SKILL_DIR      folder holding the SKILL.md under test (a copy without evals/),
#                  or the word "none" for a control run with no skill at all
#   SCENARIO_FILE  one of evals/scenarios/*.txt
#   OUT_DIR        new folder for this trial: stream.jsonl, report.md, work/
# The agent runs with --safe-mode (no CLAUDE.md, hooks, MCP or plugins), so the
# skill text is passed in the prompt. Scenarios call the real GitHub API through gh.
set -eu
if [ $# -lt 3 ]; then
  sed -n '5,11p' "$0" >&2
  exit 2
fi
scenario=$2
out=$3
model=${4:-sonnet}
mkdir -p "$out/work"
out=$(cd "$out" && pwd -P)
if [ "$1" = none ]; then
  cp "$scenario" "$out/prompt.txt"
  set --
else
  skill_dir=$(cd "$1" && pwd -P)
  if [ ! -f "$skill_dir/SKILL.md" ]; then
    echo "error: no SKILL.md in $skill_dir" >&2
    exit 2
  fi
  if [ -d "$skill_dir/evals" ]; then
    echo "error: $skill_dir contains evals/; test a copy without it, so the agent cannot read the scenarios" >&2
    exit 2
  fi
  {
    cat "$scenario"
    printf '\nBase directory for this skill: %s\n\n' "$skill_dir"
    cat "$skill_dir/SKILL.md"
  } > "$out/prompt.txt"
  set -- --add-dir "$skill_dir"
fi
cd "$out/work"
unset CLAUDE_CODE_EFFORT_LEVEL
claude -p --safe-mode --model "$model" "$@" \
  --allowedTools Bash Read Write Edit \
  --max-budget-usd 3 --output-format stream-json --verbose \
  < "$out/prompt.txt" > "$out/stream.jsonl" 2> "$out/stderr.log" || echo "claude exited $?" >> "$out/stderr.log"
jq -rs 'map(select(.type == "result")) | last | .result // "NO RESULT"' "$out/stream.jsonl" > "$out/report.md"
echo "trial done: $out/report.md"
