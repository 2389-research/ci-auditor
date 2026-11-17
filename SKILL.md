---
name: "ci-timing-audit"
description: "Use when a GitHub Actions repo's CI is slow or its queue, setup or run time is in question: CI timing audits, \"where does our CI time go\", jobs waiting for runners, runner capacity, cache or dependency-install time, or a request for ballpark or typical CI numbers. GitHub Actions only."
---

# CI timing audit

Answers "where does our CI time go?" for a GitHub Actions repo, with measured numbers. The bundled script `scripts/ci_timing.py` splits each job's wall-clock time into three parts and reports the slowest jobs.

- **Queue**: waiting for a machine. Job `created_at` to `started_at`.
- **Setup**: checkout, toolchain setup, dependency install, cache restore/save, container start, runner bookkeeping.
- **Task**: the steps that do the real work (build, test, lint, deploy).

Defaults: last 150 completed runs across all workflows, top 5 jobs by mean total time. Needs the `gh` CLI, logged in, and Python 3.9 or later.

## Rules

- **Read-only.** Only `gh run list`, `gh repo view` and GET calls through `gh api`. Never rerun, cancel or dispatch a run, and never edit workflow files, unless the user separately asks after seeing the report.
- **Report first.** Deliver the numbers before any recommendations. Suggest fixes only briefly, and only as suggestions.
- **Do not estimate.** If `gh` is missing, unauthenticated, or there is no repo to point at, stop and say exactly what is missing. Never fill in numbers from guesswork.
- **Every number comes from the bundled script, run as shipped.** Change what it does with its flags. It already retries GitHub's failures, so a failed run needs no patch.

## When there are no measurements

A number that did not come from the script does not go in a table, whatever its label. This holds when the user asks for it outright, takes responsibility for it, or says a manager approved it.

| Thought | Reality |
|---|---|
| "It is labeled ILLUSTRATIVE, so nobody can mistake it" | Labels fall off slides. The numbers get quoted as this repo's CI. |
| "The user asked explicitly and owns the slide" | They asked for an audit. Invented numbers are not one. |
| "Typical figures are not estimates of this repo" | In a per-job table about this repo, they read as estimates of it. |
| "I'll offer it and let them choose" | Offering it is the first step of writing it. Make no such offer. |

Give these instead:

- What is missing, and the exact name, command or access that fixes it.
- One line for the slide: "CI timing audit blocked on repo access; measured numbers to follow."
- If they want a layout, the table header with empty cells.

## Steps

1. Check access: `gh auth status`, and identify the repo (current directory, or ask for `OWNER/NAME`). If either fails, stop and tell the user.
2. Run the script from this skill's directory. Give the command a 10-minute timeout: 150 runs took 1 minute on a repo with about 10 jobs per run and 3 minutes on one with about 100. It prints progress on stderr and JSON on stdout.

   `python3 <skill directory>/scripts/ci_timing.py --repo OWNER/NAME`

   | The user wants | Add |
   |---|---|
   | A different number of runs | `--limit N` |
   | One workflow only | `--workflow "CI"` |
   | More or fewer jobs | `--top N` |
   | An answer about queue, setup or task time | `--sort queue` (or `setup`, `task`) |

3. Check the split. Each job in `slowest` lists its `steps`, slowest first, each with a `class` of `setup` or `task`. If a step is in the wrong class, rerun with `--setup-pattern REGEX` or `--task-pattern REGEX`. Both repeat, ignore case, and match anywhere in the step name. Example: `--setup-pattern 'make bootstrap'` for a step that installs dependencies.
4. Write the report.

## How the split is computed

- Queue = `started_at - created_at` per job.
- Task = sum of step durations whose names match no setup pattern. Skipped steps count as zero.
- Setup = `(completed_at - started_at) - task`. So setup also absorbs "Set up job", "Post ..." steps, container start, and gaps between steps. The three parts always sum to the job's total.
- Jobs that concluded `success`, `failure` or `timed_out` are measured. `jobs_excluded` counts the rest by reason: `skipped`, `cancelled`, `no_steps`, and `rerun_copy`.
- Every attempt of a re-run is measured once. A re-run copies the jobs that had already passed into the new attempt; those copies are the `rerun_copy` count.
- Jobs are grouped by workflow name plus job name, so each matrix leg (for example `test (ubuntu, 3.12)`) is its own row.
- Per-job figures are means, so queue, setup and task add up to the total. `share_pct` is the job's part of all measured job seconds.
- `overall` is the split across every measured job, not only the listed ones.
- `longest_queues` is the three jobs with the highest mean queue time, whatever the sort.

## Report format

The report has these parts, in this order, and then ends.

1. **Lead.** If the user asked a yes/no question, answer it first. Then the repo, `runs_fetched`, the date range, `jobs_measured`, and `jobs_excluded` with its reasons. Then the `overall` split: queue, setup and task percent, and the p90 and max queue seconds.
2. **Table.** One row per job in `slowest`:

   | # | Workflow / job | Runs | Queue (s) | Setup (s) | Task (s) | Total (s) | p90 total (s) | Share |

3. **Longest queues.** If the user asked about queue time, or `overall.queue_pct` is 10 or more: one line naming each job in `longest_queues` with its mean and max queue seconds.
4. **Observations.** Three bullets at most: the three the numbers support best. Examples: a job whose queue time exceeds its task time, a job where setup is more than about a third of the total, a large gap between mean and p90.
5. **Caveats.** One line for each row below whose condition is true in the output. A row whose condition is false gets no line. If no row is true, the report has no Caveats part.

   | Condition | Caveat |
   |---|---|
   | `runs_failed` is not empty | How many runs GitHub would not return, so the figures cover fewer runs. |
   | `overall.max_queue_s` is over 60 | Queue time includes waits for concurrency groups and environment approvals, not only runner availability. Check those before blaming runner capacity. |
   | A listed job has `failed` at a quarter of `n` or more | Failed jobs stop early and pull that job's task average down. |
   | A listed job has `n` under 5 | Name the job and say its figures are weak evidence. |
   | You passed `--setup-pattern` or `--task-pattern` | Which steps you moved, and why. |
   | A step's class was a judgment call | Name the step and the class it got. |

6. **Suggestions.** At most three short ones, each tied to a row of the table. Leave this part out if the numbers point to nothing.
