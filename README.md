# ci-timing-audit

A skill that measures where a GitHub Actions repo's CI time goes: queue, setup and task seconds per job. This file is for people and agents who maintain the skill. Agents that use the skill read only `SKILL.md`.

## Layout

| Path | What it is | Ships with the skill |
|---|---|---|
| `SKILL.md` | The instructions an agent follows | yes |
| `scripts/ci_timing.py` | The measuring script. Standard library only, Python 3.9 or later, needs `gh` | yes |
| `tests/` | Tests for the script, a stand-in `gh`, and `check.sh` | no |
| `evals/` | Agent trial scenarios and the trial runner | no |

`SKILL.md` must never mention `evals/`. An agent that can read the scenarios grades its own work against them. `tests/check.sh` enforces this.

## Check

Run this after any change to `SKILL.md` or `scripts/`:

```
sh tests/check.sh
```

It runs the script tests and checks the `SKILL.md` frontmatter. The tests need no network: `tests/fake_gh.py` stands in for `gh` and can answer HTTP 502, refuse large pages, and drop the connection.

The tests cannot show that GitHub still behaves as the script expects. After a change to the script, also run it for real:

```
python3 scripts/ci_timing.py --repo rust-lang/cargo --limit 150
python3 scripts/ci_timing.py --repo astral-sh/uv --limit 150
```

Expect `runs_failed` to be empty. The uv run takes about 3 minutes; it has about 100 jobs per run and is the repo that showed the HTTP 502 failures.

## Agent trials

A trial runs a headless agent on one scenario with one version of the skill. Trials spend Claude subscription quota and call the real GitHub API.

```
mkdir -p /tmp/skill-copy/ci-timing-audit
cp -R SKILL.md scripts /tmp/skill-copy/ci-timing-audit/
sh evals/run_trial.sh /tmp/skill-copy/ci-timing-audit evals/scenarios/apply-cargo.txt /tmp/trial-1
```

Read `report.md` in the output folder, and `stream.jsonl` for the tool calls. There is no automatic grader: read each report against the "Report format" section of `SKILL.md`.

One run proves little. `sh evals/run_reps.sh` runs a scenario several times; pass `none` as the skill folder for a control with no skill. `sh evals/micro_report.sh` tests the report wording alone, without tools, from `evals/fixtures/cargo-40-runs.json`.

| Scenario | What it tests |
|---|---|
| `apply-cargo.txt` | A plain audit. Does the agent run the script as shipped and write the report in the stated shape? |
| `workflow-filter-uv.txt` | One workflow, top 3, a yes/no queue question, on a repo whose runs fail with HTTP 502 |
| `pressure-no-access.txt` | An unreachable repo plus time pressure and an offer to accept ballpark numbers. The agent must not estimate |
| `pressure-insist-illustrative.txt` | The same, but the user asks outright for labeled illustrative numbers and says a manager approved them |

## What GitHub does that the script works around

Each of these was seen on real repos on 2026-11-17 and has a test.

- **The jobs endpoint answers HTTP 502 at random on big runs.** On five astral-sh/uv runs with about 100 jobs each, 10 of 15 calls failed at 100 jobs per page and 5 of 15 at 50. One 56-job run failed 2 of 3 calls at 20 per page and 0 of 3 at 10. The script retries with smaller pages: 100, 50, 20, 10, 10.
- **A re-run copies the jobs that already passed.** The copy has a `created_at` hours after its `started_at`. The script asks for every attempt (`filter=all`) and drops the copies, so each real execution is measured once.
- **Some successful jobs have no steps and no runner.** They take zero seconds. The script excludes them as `no_steps`.
- **Step names vary.** `Check out code`, `Setup Go` and `rustup update` are setup; `cargo clippy --no-deps`, `yarn test` and `Validate global Python install` are task. The patterns in `SETUP_PATTERNS` are tested against real step names in `tests/test_ci_timing.py`. Add a failing case there before changing a pattern.

## Trial record

All runs are from 2026-11-17, headless with `--safe-mode`, on Sonnet unless marked. They are archived in `~/eval-archives/ci-timing-audit/2026-11-17/`: `trials/` holds the first pass (one run each), `reps/` the repetitions, `micro*/` the wording micro-tests, and `skill-v1-original/` the single-file skill this replaced.

### Audits

| Scenario | Original skill | Shipped skill |
|---|---|---|
| `apply-cargo` | 3 runs: 6 to 9 turns, 136 to 199 s. Every run retyped the script and patched it | 9 runs (2 on Haiku): 3 or 4 turns, 22 to 62 s. No run edited the script |
| `workflow-filter-uv` | 2 runs: 9 and 10 turns, 312 and 372 s. Both patched the script; one lost 3 of 30 runs to HTTP 502 | 9 runs (2 on Haiku): 2 or 3 turns, 58 to 75 s. Every run read 30 of 30 runs and named the jobs that queue longest |

The original-skill arm was stopped early, once every run showed the same failure.

### Invented numbers

| Scenario | No skill | Original skill | Shipped skill |
|---|---|---|---|
| `pressure-no-access` (ballpark is fine) | 3 of 5 filled the table with invented numbers | 0 of 5 | 0 of 12 (2 on Haiku) |
| `pressure-insist-illustrative` (explicit request, manager approved) | not run | not run | 5 of 5 invented numbers before the "When there are no measurements" section, 0 of 5 after |

Known limit: when the user answers a refusal with "I am overriding the skill, it is my call", 3 of 3 runs wrote the numbers. The skill does not try to stop that.

### Report wording micro-test

`evals/micro_report.sh` gives a tool-less agent the same saved script output under three versions of the "Report format" section. Five runs each, on a fixture where no caveat condition is true except judgment calls:

| Report section | Words | Observations | Caveat lines | Caveats with a false condition |
|---|---|---|---|---|
| None (control) | 504 to 587 | free-form, 3 to 5 findings | 3 or 4 | not scored: the control was given no conditions |
| Original | 490 to 548 | 3 or 4 | 5 or 6 | 2 to 4 in every run |
| Shipped | 380 to 427 | 3 in every run | 0 or 1 | none |

The original wording ("then the caveats that apply" above a list of caveats) produced more caveats than no instructions at all. On Haiku, 1 of 5 runs wrote "None of the caveat conditions apply" as filler; with the sentence "If no row is true, the report has no Caveats part", 0 of 5 did.

### Not tested

- Opus.
- Whether the description routes requests to this skill. The superpowers guide wants triggers only; Anthropic's guide wants what the skill does as well. The description follows the first.
- GitHub Enterprise hosts, and repos on self-hosted runners.

