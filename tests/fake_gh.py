#!/usr/bin/env python3
# ABOUTME: Stand-in for the gh CLI that serves canned GitHub Actions data to the tests.
# ABOUTME: It reads fixtures from $FAKE_GH_DIR and can fail a run's jobs call on demand.
"""Fixture layout in $FAKE_GH_DIR:
  runs.json          output of `gh run list --json ...`
  jobs_<run id>.jsonl  one job object per line, as `gh api --jq '.jobs[]'` prints
  fail_<run id>      a number N: fail the first N jobs calls for that run with HTTP 502,
                     or the word "always"
  maxpage_<run id>   a number N: answer HTTP 502 when per_page is above N, as GitHub does
                     for runs with many jobs
  fail_runlist       a number N: fail the first N `gh run list` calls with a connection error
Every call is appended to calls.log.
"""
import os
import re
import sys

root = os.environ["FAKE_GH_DIR"]
args = sys.argv[1:]
with open(os.path.join(root, "calls.log"), "a") as log:
    log.write(" ".join(args) + "\n")

if args[:2] == ["run", "list"]:
    fail = os.path.join(root, "fail_runlist")
    left = int(open(fail).read()) if os.path.exists(fail) else 0
    if left > 0:
        open(fail, "w").write(str(left - 1))
        sys.exit("error connecting to api.github.com\ncheck your internet connection or https://githubstatus.com")
    sys.stdout.write(open(os.path.join(root, "runs.json")).read())
    sys.exit(0)

if args[:1] == ["api"]:
    m = re.match(r"repos/[^/]+/[^/]+/actions/runs/(\d+)/jobs\?(.*)$", args[1])
    if not m:
        sys.exit(f"fake gh: unexpected api path {args[1]}")
    run_id, query = m.groups()
    if "filter=all" not in query:
        sys.exit("fake gh: jobs call without filter=all would hide earlier run attempts")
    fail = os.path.join(root, f"fail_{run_id}")
    if os.path.exists(fail):
        left = open(fail).read().strip()
        if left == "always" or int(left) > 0:
            if left != "always":
                open(fail, "w").write(str(int(left) - 1))
            sys.stdout.write('{\n  "message": "Server Error"\n}\n')
            sys.exit("gh: Server Error (HTTP 502)")
    maxpage = os.path.join(root, f"maxpage_{run_id}")
    if os.path.exists(maxpage) and int(re.search(r"per_page=(\d+)", query).group(1)) > int(open(maxpage).read()):
        sys.exit("gh: Server Error (HTTP 502)")
    path = os.path.join(root, f"jobs_{run_id}.jsonl")
    if not os.path.exists(path):
        sys.stdout.write('{"message":"Not Found","status":"404"}')
        sys.exit("gh: Not Found (HTTP 404)")
    sys.stdout.write(open(path).read())
    sys.exit(0)

sys.exit(f"fake gh: unexpected command {args}")
