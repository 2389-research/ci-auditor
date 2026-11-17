# ABOUTME: Tests for scripts/ci_timing.py: step classification, per-job measurement,
# ABOUTME: and the command line run end to end against a stand-in gh executable.
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "scripts", "ci_timing.py")

spec = importlib.util.spec_from_file_location("ci_timing", SCRIPT)
ci_timing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci_timing)


def step(name, start, end, conclusion="success"):
    return {"name": name, "conclusion": conclusion,
            "started_at": f"2026-11-17T10:{start}Z", "completed_at": f"2026-11-17T10:{end}Z"}


def job(name="test", created="00:00", started="00:10", completed="05:10",
        conclusion="success", steps=None):
    if steps is None:
        steps = [step("Set up job", "00:10", "00:12"),
                 step("Run actions/checkout@3d3c42e", "00:12", "00:20"),
                 step("Run cargo test -p cargo", "00:20", "05:00"),
                 step("Post Run actions/checkout@3d3c42e", "05:00", "05:05"),
                 step("Complete job", "05:05", "05:10")]
    return {"name": name, "conclusion": conclusion, "steps": steps,
            "created_at": f"2026-11-17T10:{created}Z",
            "started_at": f"2026-11-17T10:{started}Z",
            "completed_at": f"2026-11-17T10:{completed}Z"}


class ClassifyTest(unittest.TestCase):
    # Step names seen in astral-sh/uv, cli/cli, rust-lang/cargo and vercel/next.js runs.
    SETUP = [
        "Set up job", "Complete job", "Initialize containers", "Stop containers",
        "Run actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
        "Post Run actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
        "Check out code", "Checkout repository", "Checkout Branch",
        "Set up Go", "Setup Go", "Setup Dev Drive",
        "Run actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97",
        "Run conda-incubator/setup-miniconda@be893c923ea9cf1cf7cd510fbdde27c7e18cbdcb",
        "Install Rust toolchain", "Install requirements and prime cache",
        "Run sudo apt update -y && sudo apt install gdb lldb gcc-multilib -y",
        "Run taiki-e/install-action@cfdb7ed4ccc7c7dce37759eae89dc5674b469b39",
        "Run Swatinem/rust-cache@6323deb102c322ba6fcbdcafc7e3dddab59af2b6",
        "Run astral-sh/github-actions/rust-workspace-cache@61a5a2c7e0df1c0caf46fe5d1e74a4cb8a7205f8",
        "Download dependencies",
        "Build EmbarkStudios/cargo-deny-action@3c6349835b2b7b196a839186cb8b78e02f7b5f25",
        "Run rustup update stable && rustup default stable",
        "Run rustup component add rustc-dev llvm-tools-preview rust-docs",
        "Run npm ci", "Run pip install -r requirements.txt",
        "Run dotnet restore", "Restore cargo cache",
    ]
    TASK = [
        "Run cargo clippy --workspace --all-targets --no-deps --keep-going",
        "Validate global Python install", "Check cache compatibility",
        "Run cargo test -p cargo", "Cargo test", "Build", "Build wheels", "Build Go",
        "Run unit and integration tests", "Perform CodeQL Analysis",
        "Run EmbarkStudios/cargo-deny-action@3c6349835b2b7b196a839186cb8b78e02f7b5f25",
        "Run yarn test", "Run pnpm build", "Run bundle exec rspec",
        "Comment on PR", "Upload tarballs to Vercel Blob", "Save test results",
    ]

    def test_setup_steps(self):
        wrong = [n for n in self.SETUP if ci_timing.classify(n) != "setup"]
        self.assertEqual(wrong, [])

    def test_task_steps(self):
        wrong = [n for n in self.TASK if ci_timing.classify(n) != "task"]
        self.assertEqual(wrong, [])

    def test_added_setup_pattern(self):
        self.assertEqual(ci_timing.classify("Run make bootstrap"), "task")
        self.assertEqual(ci_timing.classify("Run make bootstrap", ["make bootstrap"]), "setup")

    def test_added_task_pattern_beats_setup(self):
        self.assertEqual(ci_timing.classify("Install and run smoke test", [], ["smoke test"]), "task")


class MeasureTest(unittest.TestCase):
    def test_three_parts_sum_to_wall_clock(self):
        m = ci_timing.measure(job())
        self.assertEqual((m["queue"], m["setup"], m["task"]), (10, 20, 280))
        self.assertFalse(m["failed"])

    def test_skipped_step_counts_as_zero(self):
        steps = [step("Run cargo test", "00:10", "01:10"),
                 step("Run cargo bench", "01:10", "01:10", conclusion="skipped")]
        m = ci_timing.measure(job(completed="01:10", steps=steps))
        self.assertEqual(m["task"], 60)
        self.assertEqual([s[0] for s in m["steps"]], ["Run cargo test"])

    def test_failed_and_timed_out_jobs_are_measured_as_failed(self):
        for conclusion in ("failure", "timed_out"):
            self.assertTrue(ci_timing.measure(job(conclusion=conclusion))["failed"])

    def test_skipped_and_cancelled_jobs_are_excluded(self):
        self.assertEqual(ci_timing.measure(job(conclusion="skipped")), "skipped")
        self.assertEqual(ci_timing.measure(job(conclusion="cancelled")), "cancelled")

    def test_job_copied_into_a_rerun_is_excluded(self):
        # A re-run copies jobs that already passed: created_at is the re-run time,
        # hours after the copied started_at. Its queue time is not knowable.
        copied = job(created="59:00", started="00:10", completed="05:10")
        self.assertEqual(ci_timing.measure(copied), "rerun_copy")

    def test_job_without_steps_is_excluded(self):
        self.assertEqual(ci_timing.measure(job(steps=[])), "no_steps")


class CommandLineTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.bin = os.path.join(self.dir, "bin")
        os.mkdir(self.bin)
        gh = os.path.join(self.bin, "gh")
        with open(gh, "w") as f:
            f.write(f"#!/bin/sh\nexec '{sys.executable}' '{os.path.join(HERE, 'fake_gh.py')}' \"$@\"\n")
        os.chmod(gh, 0o755)
        self.runs = []

    def add_run(self, run_id, jobs, workflow="CI"):
        self.runs.append({"databaseId": run_id, "workflowName": workflow,
                          "createdAt": f"2026-11-17T10:00:{len(self.runs):02d}Z"})
        with open(os.path.join(self.dir, "runs.json"), "w") as f:
            json.dump(self.runs, f)
        if jobs is not None:
            with open(os.path.join(self.dir, f"jobs_{run_id}.jsonl"), "w") as f:
                f.writelines(json.dumps(j) + "\n" for j in jobs)

    def fail(self, run_id, times):
        with open(os.path.join(self.dir, f"fail_{run_id}"), "w") as f:
            f.write(str(times))

    def run_script(self, *args, path=None):
        env = dict(os.environ, FAKE_GH_DIR=self.dir,
                   PATH=path if path is not None else self.bin + os.pathsep + "/usr/bin:/bin")
        return subprocess.run(
            [sys.executable, SCRIPT, "--repo", "octo/demo", "--retry-wait", "0", *args],
            capture_output=True, text=True, env=env)

    def test_reports_slowest_jobs_with_their_steps(self):
        self.add_run(1, [job("lint", completed="01:10", steps=[step("Run ruff", "00:10", "01:10")]),
                         job("test"), job("docs", conclusion="skipped")])
        self.add_run(2, [job("test", conclusion="failure")])
        r = self.run_script("--top", "1")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual((out["repo"], out["runs_fetched"], out["runs_failed"]), ("octo/demo", 2, []))
        self.assertEqual(out["jobs_measured"], 3)
        self.assertEqual(out["jobs_excluded"], {"skipped": 1})
        self.assertEqual(out["distinct_jobs"], 2)
        self.assertEqual(out["overall"], {"queue_pct": 4, "setup_pct": 6, "task_pct": 90,
                                          "mean_queue_s": 10, "p90_queue_s": 10, "max_queue_s": 10})
        self.assertEqual(len(out["slowest"]), 1)
        top = out["slowest"][0]
        self.assertEqual((top["job"], top["n"], top["failed"]), ("test", 2, 1))
        self.assertEqual((top["queue_s"], top["setup_s"], top["task_s"], top["total_s"]),
                         (10, 20, 280, 310))
        self.assertEqual(top["share_pct"], 90)  # 620 of 690 measured seconds
        self.assertEqual(top["steps"][0], {"name": "Run cargo test -p cargo", "class": "task", "mean_s": 280})
        self.assertIn({"name": "Run actions/checkout@3d3c42e", "class": "setup", "mean_s": 8}, top["steps"])

    def test_sort_by_queue_ranks_the_longest_wait_first(self):
        self.add_run(1, [job("test"), job("deploy", created="00:00", started="03:00", completed="03:30",
                                          steps=[step("Run deploy", "03:00", "03:30")])])
        out = json.loads(self.run_script("--sort", "queue").stdout)
        self.assertEqual([(r["job"], r["queue_s"]) for r in out["slowest"]], [("deploy", 180), ("test", 10)])
        self.assertEqual(out["sorted_by"], "queue")

    def test_longest_queues_are_listed_whatever_the_sort(self):
        self.add_run(1, [job("test"), job("deploy", created="00:00", started="03:00", completed="03:30",
                                          steps=[step("Run deploy", "03:00", "03:30")])])
        out = json.loads(self.run_script("--top", "1").stdout)
        self.assertEqual([r["job"] for r in out["slowest"]], ["test"])
        self.assertEqual(out["longest_queues"][0],
                         {"workflow": "CI", "job": "deploy", "n": 1, "queue_s": 180, "max_queue_s": 180})

    def test_setup_pattern_flag_moves_a_step(self):
        self.add_run(1, [job("test")])
        out = json.loads(self.run_script("--setup-pattern", "cargo test").stdout)
        top = out["slowest"][0]
        self.assertEqual((top["setup_s"], top["task_s"]), (300, 0))
        self.assertEqual(out["setup_patterns_added"], ["cargo test"])

    def test_transient_server_error_is_retried(self):
        self.add_run(1, [job("test")])
        self.fail(1, 2)
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual((out["runs_failed"], out["jobs_measured"]), ([], 1))

    def test_run_too_big_for_large_pages_is_read_in_smaller_pages(self):
        self.add_run(1, [job("test")])
        with open(os.path.join(self.dir, "maxpage_1"), "w") as f:
            f.write("10")
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual((out["runs_failed"], out["jobs_measured"]), ([], 1))

    def test_connection_error_listing_runs_is_retried(self):
        self.add_run(1, [job("test")])
        self.fail("runlist", 1)
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["jobs_measured"], 1)

    def test_run_that_keeps_failing_is_reported_and_the_rest_measured(self):
        self.add_run(1, [job("test")])
        self.add_run(2, [job("test")])
        self.fail(2, "always")
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["runs_fetched"], 1)
        self.assertEqual([f["run_id"] for f in out["runs_failed"]], [2])
        self.assertIn("HTTP 502", out["runs_failed"][0]["error"])
        self.assertEqual(out["jobs_measured"], 1)

    def test_exits_with_error_when_every_run_fails(self):
        self.add_run(1, None)
        r = self.run_script()
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout, "")
        self.assertIn("HTTP 404", r.stderr)

    def test_runs_with_nothing_to_measure_report_zero_jobs(self):
        self.add_run(1, [job("docs", conclusion="skipped")])
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual((out["jobs_measured"], out["slowest"], out["overall"]), (0, [], None))
        self.assertEqual(out["jobs_excluded"], {"skipped": 1})

    def test_exits_with_error_when_there_are_no_runs(self):
        with open(os.path.join(self.dir, "runs.json"), "w") as f:
            f.write("[]")
        r = self.run_script()
        self.assertEqual(r.returncode, 1)
        self.assertIn("No completed runs", r.stderr)

    def test_exits_with_error_when_gh_is_missing(self):
        r = self.run_script(path=os.path.join(self.dir, "empty"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("gh CLI not found", r.stderr)
        self.assertNotIn("Traceback", r.stderr)


if __name__ == "__main__":
    unittest.main()
