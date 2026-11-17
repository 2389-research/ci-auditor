#!/usr/bin/env python3
# ABOUTME: Splits GitHub Actions job time into queue, setup and task seconds over recent runs.
# ABOUTME: Read-only: it calls `gh run list`, `gh repo view` and GET requests through `gh api`.
"""Report the slowest GitHub Actions jobs of a repo, as JSON on stdout.

Needs the gh CLI, logged in, and Python 3.9 or later. Standard library only.

  queue  job created_at to started_at (waiting for a runner)
  task   steps whose names match no setup pattern
  setup  everything else between started_at and completed_at
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

# A step is setup when its name matches one of these. Names come from the workflow
# file (`name:`), or GitHub derives them: "Run <action>@<ref>" or "Run <command>".
SETUP_PATTERNS = [
    # Runner bookkeeping
    r"^(set up job|complete job|initialize containers|stop containers)$",
    r"^(post|pre) ",
    r"^build \S+@",                       # building a Docker-based action
    r"^pull (?!request)",                 # pulling a container image
    # Source checkout
    r"\bcheck ?out\b",
    # Toolchains
    r"\bset[ -]?up\b",
    r"\brustup\b",
    # Dependencies
    r"^install\b",
    r"^run \S*install\S*@",               # actions such as taiki-e/install-action
    r"\b(apt|apt-get|brew|choco|dnf|yum|apk|pip|pip3|pipx|gem|bundle|npm|pnpm|yarn|bun"
    r"|composer|poetry|conda|mamba|cargo) (-\S+ )*install\b",
    r"\bnpm ci\b|\buv sync\b|\bgo mod download\b|\bcargo fetch\b|^(run )?(yarn|pnpm i)$",
    r"\b(dotnet|nuget) restore\b",
    r"^(run )?(download|fetch|get|restore|resolve|prepare|vendor)\b.*"
    r"\b(dependenc(y|ies)|deps|modules|packages|requirements)\b",
    # Caches
    r"cache@",
    r"^cache\b|^(restore|save)\b.*\bcache",
    # Registry and cloud logins
    r"\bdocker login\b|login-action@|^log ?in to\b|credentials@|^configure \S+ credentials",
]
MEASURED = ("success", "failure", "timed_out")


def compile_patterns(patterns):
    return [re.compile(p, re.I) for p in patterns]


BUILT_IN_SETUP = compile_patterns(SETUP_PATTERNS)


def classify(name, added_setup=(), added_task=()):
    """Return "setup" or "task" for a step name. Added task patterns win."""
    if any(p.search(name) for p in compile_patterns(added_task)):
        return "task"
    if any(p.search(name) for p in BUILT_IN_SETUP + compile_patterns(added_setup)):
        return "setup"
    return "task"


def parse_time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def seconds(start, end):
    return max(0.0, (end - start).total_seconds()) if start and end else 0.0


def measure(job, added_setup=(), added_task=()):
    """Return a job's timing, or the reason it is excluded as a string."""
    conclusion = job.get("conclusion")
    if conclusion not in MEASURED:
        return conclusion or "unfinished"
    created, started, done = (parse_time(job.get(k)) for k in ("created_at", "started_at", "completed_at"))
    if not (created and started and done):
        return "no_timestamps"
    if started < created:
        # A re-run copies the jobs that already passed. The copy keeps the old start
        # time, so its queue time is unknown. The original job is measured instead.
        return "rerun_copy"
    if not job.get("steps"):
        return "no_steps"
    steps = []
    for s in job["steps"]:
        if s.get("conclusion") == "skipped":
            continue
        steps.append((s["name"], classify(s["name"], added_setup, added_task),
                      seconds(parse_time(s.get("started_at")), parse_time(s.get("completed_at")))))
    run_time = seconds(started, done)
    task = min(run_time, sum(secs for _, kind, secs in steps if kind == "task"))
    return {"queue": seconds(created, started), "setup": run_time - task, "task": task,
            "failed": conclusion != "success", "steps": steps}


def is_permanent(err):
    """401 and 404 mean no access or no such repo. Trying again cannot help."""
    return bool(re.search(r"HTTP 40[14]", err))


def gh(args, retry_wait, attempts=3):
    """Run gh. Return (stdout, None) on success or (None, error text) on failure.
    GitHub fails now and then with HTTP 502 or a dropped connection, so a failed
    call is tried again unless the error is permanent."""
    for attempt in range(attempts):
        r = subprocess.run(["gh", *args], capture_output=True, text=True)
        if not r.returncode:
            return r.stdout, None
        err = r.stderr.strip() or r.stdout.strip() or f"exit {r.returncode}"
        if is_permanent(err):
            break
        if attempt < attempts - 1:
            time.sleep(retry_wait * (attempt + 1))
    return None, err


def gh_or_exit(args, retry_wait):
    out, err = gh(args, retry_wait)
    if err:
        sys.exit(f"error: gh {' '.join(args)} failed:\n{err}")
    return out


# The jobs endpoint answers HTTP 502 when a page takes too long to build, which
# happens on some runs with many jobs or steps. Smaller pages get through, so
# each retry asks for fewer jobs per page.
PAGE_SIZES = (100, 50, 20, 10, 10)


def fetch_jobs(repo, run_id, retry_wait):
    """Return (jobs, None) or (None, error) for one run."""
    for attempt, per_page in enumerate(PAGE_SIZES):
        # filter=all returns every attempt of a re-run, not only the latest.
        path = f"repos/{repo}/actions/runs/{run_id}/jobs?per_page={per_page}&filter=all"
        out, err = gh(["api", path, "--paginate", "--jq", ".jobs[]"], retry_wait, attempts=1)
        if not err:
            return [json.loads(line) for line in out.splitlines() if line.strip()], None
        if is_permanent(err):
            break
        if attempt < len(PAGE_SIZES) - 1:
            time.sleep(retry_wait * (attempt + 1))
    return None, err


def percentile(values, p):
    values = sorted(values)
    return values[min(len(values) - 1, int(round(p * (len(values) - 1))))]


def mean(values):
    return sum(values) / len(values)


def step_summary(steps, limit=10):
    """Mean seconds per step name over the executions where it ran, slowest first."""
    by_name = defaultdict(list)
    kinds = {}
    for name, kind, secs in steps:
        by_name[name].append(secs)
        kinds[name] = kind
    rows = [{"name": n, "class": kinds[n], "mean_s": round(mean(v))} for n, v in by_name.items()]
    rows = [r for r in rows if r["mean_s"] >= 1]
    return sorted(rows, key=lambda r: -r["mean_s"])[:limit]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", help="OWNER/NAME (default: the repo of the current directory)")
    ap.add_argument("--limit", type=int, default=150, help="recent completed runs to read (default 150)")
    ap.add_argument("--workflow", help="only this workflow, by name or file name")
    ap.add_argument("--top", type=int, default=5, help="jobs to report (default 5)")
    ap.add_argument("--sort", choices=["total", "queue", "setup", "task"], default="total",
                    help="rank jobs by this mean (default total)")
    ap.add_argument("--setup-pattern", action="append", default=[], metavar="REGEX",
                    help="also count steps whose name matches as setup (repeatable)")
    ap.add_argument("--task-pattern", action="append", default=[], metavar="REGEX",
                    help="count steps whose name matches as task, whatever else matches (repeatable)")
    # 6 workers read 150 runs of a 10-job repo in about a minute and stayed clear of
    # GitHub's secondary rate limit in every test run.
    ap.add_argument("--workers", type=int, default=6, help="parallel API calls (default 6)")
    # The wait grows by this much per retry: 2, 4, 6, 8 seconds across the page sizes.
    ap.add_argument("--retry-wait", type=float, default=2, help="seconds before the first retry (default 2)")
    a = ap.parse_args()

    if not shutil.which("gh"):
        sys.exit("error: gh CLI not found on PATH. Install it (https://cli.github.com) and run `gh auth login`.")
    for pattern in a.setup_pattern + a.task_pattern:
        try:
            re.compile(pattern)
        except re.error as e:
            sys.exit(f"error: bad pattern {pattern!r}: {e}")

    repo = a.repo or gh_or_exit(["repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"], a.retry_wait).strip()
    cmd = ["run", "list", "-R", repo, "--limit", str(a.limit), "--status", "completed",
           "--json", "databaseId,workflowName,createdAt"]
    if a.workflow:
        cmd += ["--workflow", a.workflow]
    runs = json.loads(gh_or_exit(cmd, a.retry_wait))
    if not runs:
        sys.exit(f"error: No completed runs found in {repo}" + (f" for workflow {a.workflow!r}." if a.workflow else "."))

    fetched = []
    with ThreadPoolExecutor(max_workers=max(1, a.workers)) as pool:
        for result in pool.map(lambda run: fetch_jobs(repo, run["databaseId"], a.retry_wait), runs):
            fetched.append(result)
            if len(fetched) % 25 == 0 or len(fetched) == len(runs):
                print(f"read {len(fetched)} of {len(runs)} runs", file=sys.stderr)

    jobs_by_key = defaultdict(list)
    excluded = Counter()
    runs_failed = []
    for run, (jobs, err) in zip(runs, fetched):
        if err:
            runs_failed.append({"run_id": run["databaseId"], "error": err.splitlines()[-1]})
            continue
        for job in jobs:
            m = measure(job, a.setup_pattern, a.task_pattern)
            if isinstance(m, str):
                excluded[m] += 1
            else:
                jobs_by_key[(run["workflowName"], job["name"])].append(m)
    if len(runs_failed) == len(runs):
        sys.exit(f"error: could not read the jobs of any of {len(runs)} runs in {repo}. Last error:\n"
                 + runs_failed[-1]["error"])

    rows = []
    for (workflow, job_name), ms in jobs_by_key.items():
        totals = [m["queue"] + m["setup"] + m["task"] for m in ms]
        rows.append({
            "workflow": workflow, "job": job_name, "n": len(ms),
            "failed": sum(m["failed"] for m in ms),
            "queue_s": round(mean([m["queue"] for m in ms])),
            "setup_s": round(mean([m["setup"] for m in ms])),
            "task_s": round(mean([m["task"] for m in ms])),
            "total_s": round(mean(totals)),
            "p90_total_s": round(percentile(totals, 0.9)),
            "max_queue_s": round(max(m["queue"] for m in ms)),
            "sum_s": sum(totals),
            "steps": step_summary([s for m in ms for s in m["steps"]]),
        })
    all_seconds = sum(r["sum_s"] for r in rows)
    for r in rows:
        r["share_pct"] = round(100 * r.pop("sum_s") / all_seconds) if all_seconds else 0
    longest_queues = [{k: r[k] for k in ("workflow", "job", "n", "queue_s", "max_queue_s")}
                      for r in sorted(rows, key=lambda r: -r["queue_s"])[:3]]
    rows.sort(key=lambda r: -r[a.sort + "_s"])
    measured = [m for ms in jobs_by_key.values() for m in ms]
    overall = None
    if measured:
        queues = [m["queue"] for m in measured]
        overall = {part + "_pct": round(100 * sum(m[part] for m in measured) / all_seconds) if all_seconds else 0
                   for part in ("queue", "setup", "task")}
        overall.update(mean_queue_s=round(mean(queues)), p90_queue_s=round(percentile(queues, 0.9)),
                       max_queue_s=round(max(queues)))
    dates = sorted(r["createdAt"] for r in runs)
    print(json.dumps({
        "repo": repo, "workflow": a.workflow,
        "runs_fetched": len(runs) - len(runs_failed), "runs_failed": runs_failed,
        "from": dates[0], "to": dates[-1],
        "jobs_measured": sum(r["n"] for r in rows), "jobs_excluded": dict(excluded),
        "distinct_jobs": len(rows), "overall": overall, "longest_queues": longest_queues,
        "sorted_by": a.sort,
        "setup_patterns_added": a.setup_pattern, "task_patterns_added": a.task_pattern,
        "slowest": rows[:a.top],
    }, indent=2))


if __name__ == "__main__":
    main()
