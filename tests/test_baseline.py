from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
import unittest
from pathlib import Path

from helpers import SKILL, git, make_dir, make_git_repo, run_cli, write_tree

from ia import baseline as bl
from ia import detect
from ia import run as runmod

UNITTEST_CMD = [sys.executable, "-m", "unittest", "discover", "-s", "tests"]
PASSING = "import unittest\n\nclass T(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n"


def plan(**over) -> dict:
    base = {"stack": "python", "test_cmd": UNITTEST_CMD, "coverage_cmd": None, "measure": [], "measured": True,
            "env": {}, "pre": [], "deps": "none", "deps_dirs": [], "install_cmd": None}
    base.update(over)
    return base


def _kill_pidfile(pidfile: Path) -> None:
    try:
        os.kill(int(pidfile.read_text()), signal.SIGKILL)
    except (OSError, ValueError):
        pass


def make_run(files=None, subdir="", **plan_over):
    """A repo with a unittest suite, an initialised run and a plan written into the manifest."""
    files = files if files is not None else {"tests/test_a.py": PASSING}
    prefixed = {f"{subdir}/{k}" if subdir else k: v for k, v in files.items()}
    repo, sha = make_git_repo(prefixed)
    run = make_dir() / "run"
    runmod.init_run("sys", [("BACK", repo, subdir)], run, "es", False, "unknown")
    manifest = runmod.load(run)
    manifest["baseline"]["BACK"] = {"plan": plan(**plan_over)}
    runmod.save(run, manifest)
    return run, repo, sha


class ParseSummaryTest(unittest.TestCase):
    def test_parse_strips_ansi_colours(self):
        text = ("\x1b[2m      Tests \x1b[22m \x1b[1m\x1b[31m2 failed\x1b[39m\x1b[22m\x1b[2m | \x1b[22m"
                "\x1b[1m\x1b[32m8 passed\x1b[39m\x1b[22m\x1b[90m (10)\x1b[39m\n")
        r = bl.parse_summary(text)
        self.assertEqual((r["passed"], r["failed"], r["total"], r["runner"]), (8, 2, 10, "vitest"))

    def test_base_env_disables_colour(self):
        self.assertEqual((bl.BASE_ENV["NO_COLOR"], bl.BASE_ENV["FORCE_COLOR"]), ("1", "0"))

    def test_parse_vitest_passed(self):
        r = bl.parse_summary(" Test Files  2 passed (2)\n      Tests  12 passed (12)\n   Duration  1.2s\n")
        self.assertEqual((r["passed"], r["failed"], r["total"], r["runner"]), (12, 0, 12, "vitest"))

    def test_parse_vitest_failed(self):
        r = bl.parse_summary("      Tests  2 failed | 10 passed (12)\n")
        self.assertEqual((r["passed"], r["failed"], r["total"], r["runner"]), (10, 2, 12, "vitest"))

    def test_parse_jest(self):
        r = bl.parse_summary("Test Suites: 1 failed, 3 passed, 4 total\nTests:       2 failed, 30 passed, 32 total\n")
        self.assertEqual((r["passed"], r["failed"], r["total"], r["runner"]), (30, 2, 32, "jest"))

    def test_parse_jest_all_passed(self):
        r = bl.parse_summary("Tests:       32 passed, 32 total\n")
        self.assertEqual((r["passed"], r["failed"], r["total"]), (32, 0, 32))

    def test_parse_pytest(self):
        r = bl.parse_summary("=========== 1 failed, 5 passed, 2 skipped in 0.42s ===========\n")
        self.assertEqual((r["passed"], r["failed"], r["total"], r["runner"]), (5, 1, 6, "pytest"))

    def test_parse_pytest_all_passed(self):
        r = bl.parse_summary("============ 7 passed in 0.10s ============\n")
        self.assertEqual((r["passed"], r["failed"], r["total"], r["runner"]), (7, 0, 7, "pytest"))

    def test_parse_unittest_ok(self):
        r = bl.parse_summary("----\nRan 9 tests in 0.003s\n\nOK\n")
        self.assertEqual((r["passed"], r["failed"], r["total"], r["runner"]), (9, 0, 9, "unittest"))

    def test_parse_unittest_failed(self):
        r = bl.parse_summary("Ran 9 tests in 0.003s\n\nFAILED (failures=2, errors=1)\n")
        self.assertEqual((r["passed"], r["failed"], r["total"], r["runner"]), (6, 3, 9, "unittest"))

    def test_parse_unittest_ignores_skipped_and_expected(self):
        text = ("Ran 10 tests in 0.1s\n\nFAILED (failures=1, skipped=2, expected failures=1, "
                "unexpected successes=1)\n")
        r = bl.parse_summary(text)
        self.assertEqual((r["passed"], r["failed"], r["total"]), (9, 1, 10))

    def test_parse_unittest_ok_with_skips(self):
        r = bl.parse_summary("Ran 4 tests in 0.1s\n\nOK (skipped=2)\n")
        self.assertEqual((r["passed"], r["failed"], r["total"]), (4, 0, 4))

    def test_parse_coverage_vitest_table(self):
        r = bl.parse_summary("----------|---------|\nAll files |    39.8 |   50 |\n")
        self.assertEqual(r["coverage"], 39.8)

    def test_parse_coverage_pytest_cov(self):
        r = bl.parse_summary("Name  Stmts  Miss  Cover\nTOTAL   200   38    81%\n")
        self.assertEqual(r["coverage"], 81.0)

    def test_parse_nothing_recognised(self):
        r = bl.parse_summary("hello\n")
        self.assertEqual(r, {"passed": None, "failed": None, "total": None, "coverage": None, "runner": None})

    def test_parse_reads_tail_of_huge_output(self):
        text = ("noise noise noise noise\n" * 450000) + "      Tests  1 failed | 4 passed (5)\n"
        self.assertGreater(len(text), 10_000_000)
        r = bl.parse_summary(text)
        self.assertEqual((r["passed"], r["failed"], r["total"]), (4, 1, 5))


SUREFIRE = ('<?xml version="1.0" encoding="UTF-8"?>\n<testsuite name="com.acme.OrderTest" tests="{t}" failures="{f}" '
            'errors="{e}" skipped="{s}"><testcase name="a"/></testsuite>\n')


class JunitAndJvmTextTest(unittest.TestCase):
    def write(self, files):
        return write_tree(make_dir(), files)

    def test_sums_every_report_matching_the_globs(self):
        root = self.write({
            "target/surefire-reports/TEST-a.xml": SUREFIRE.format(t=5, f=1, e=1, s=1),
            "core/target/surefire-reports/TEST-b.xml": SUREFIRE.format(t=3, f=0, e=0, s=0),
            "target/surefire-reports/other.xml": SUREFIRE.format(t=99, f=0, e=0, s=0),
        })
        r = bl.parse_junit(root, ["**/target/surefire-reports/TEST-*.xml"])
        self.assertEqual((r["passed"], r["failed"], r["total"], r["runner"], r["files"]), (5, 2, 7, "junit-xml", 2))

    def test_nested_testsuites_count_only_leaf_suites(self):
        xml = ('<testsuites tests="4"><testsuite tests="4" failures="1"><testsuite tests="2" failures="1"/>'
               '<testsuite tests="2"/></testsuite></testsuites>')
        r = bl.parse_junit(self.write({"r/TEST-x.xml": xml}), ["r/*.xml"])
        self.assertEqual((r["passed"], r["failed"], r["total"]), (3, 1, 4))

    def test_no_report_is_none(self):
        self.assertIsNone(bl.parse_junit(self.write({"a.txt": "x"}), ["**/TEST-*.xml"]))

    def test_doctype_and_broken_files_are_refused_not_parsed(self):
        bomb = ('<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;">]>'
                '<testsuite tests="&b;"/>')
        root = self.write({"r/TEST-bomb.xml": bomb, "r/TEST-broken.xml": "<testsuite",
                           "r/TEST-ok.xml": SUREFIRE.format(t=2, f=0, e=0, s=0)})
        r = bl.parse_junit(root, ["r/*.xml"])
        self.assertEqual((r["passed"], r["total"], r["files"]), (2, 2, 1))
        self.assertEqual(sorted(r["skipped_files"]), ["r/TEST-bomb.xml", "r/TEST-broken.xml"])

    def test_maven_text_summary_sums_every_module(self):
        text = ("[INFO] Tests run: 2, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: 0.1 s -- in a.ATest\n"
                "[INFO] Results:\n[INFO] Tests run: 2, Failures: 0, Errors: 0, Skipped: 0\n"
                "[ERROR] Tests run: 5, Failures: 1, Errors: 1, Skipped: 1\n[INFO] BUILD SUCCESS\n")
        r = bl.parse_summary(text)
        self.assertEqual((r["passed"], r["failed"], r["total"], r["runner"]), (4, 2, 6, "maven"))

    def test_junit_globs_can_be_set_in_the_plan(self):
        run, _, _ = make_run()
        ok = run_cli(["baseline", "--run", str(run), "--set", "BACK", 'junit=["build/test-results/**/*.xml"]'])
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertEqual(runmod.load(run)["baseline"]["BACK"]["plan"]["junit"], ["build/test-results/**/*.xml"])
        for bad in ('junit="x.xml"', 'junit=["/abs/*.xml"]', 'junit=["../x/*.xml"]'):
            self.assertEqual(run_cli(["baseline", "--run", str(run), "--set", "BACK", bad]).returncode, 2, bad)

    def test_gradle_text_summary(self):
        r = bl.parse_summary("> Task :test FAILED\n\n7 tests completed, 2 failed, 1 skipped\n\nBUILD FAILED in 3s\n")
        self.assertEqual((r["passed"], r["failed"], r["total"], r["runner"]), (4, 2, 6, "gradle"))


def _go_event(action, package="m/a", test=None):
    event = {"Time": "2026-10-22T00:00:00Z", "Action": action, "Package": package}
    if test:
        event["Test"] = test
    return json.dumps(event)


class GoJsonTest(unittest.TestCase):
    def test_counts_top_level_tests_only(self):
        text = "\n".join([_go_event("run", test="TestA"), _go_event("pass", test="TestA"),
                          _go_event("pass", test="TestB/sub1"), _go_event("fail", test="TestB/sub2"),
                          _go_event("fail", test="TestB"), _go_event("skip", test="TestC"),
                          _go_event("output", test="TestA"), _go_event("fail")])
        r = bl.parse_summary(text)
        self.assertEqual((r["passed"], r["failed"], r["total"], r["runner"]), (1, 1, 2, "go"))

    def test_a_package_that_fails_without_a_failing_test_counts_once(self):
        text = "\n".join([_go_event("pass", "m/a", "TestA"), _go_event("pass", "m/a"),
                          _go_event("fail", "m/b"),
                          "FAIL\tm/c [build failed]", "# m/c", "c.go:3:1: syntax error"])
        r = bl.parse_summary(text)
        self.assertEqual((r["passed"], r["failed"], r["total"]), (1, 2, 3))

    def test_go_cover_func_total(self):
        r = bl.parse_summary("m/a/a.go:3:\tF\t100.0%\ntotal:\t\t\t(statements)\t72.5%\n")
        self.assertEqual(r["coverage"], 72.5)


@unittest.skipUnless(shutil.which("go"), "go is not installed")
class GoBaselineTest(unittest.TestCase):
    def test_real_go_suite_offline(self):
        files = {"go.mod": "module example.com/m\n\ngo 1.21\n",
                 "calc/calc.go": "package calc\n\nfunc Add(a, b int) int { return a + b }\n",
                 "calc/calc_test.go": ('package calc\n\nimport "testing"\n\n'
                                       'func TestAdd(t *testing.T) { if Add(1, 2) != 3 { t.Fatal("add") } }\n'
                                       'func TestBroken(t *testing.T) { if Add(1, 1) != 3 { t.Fatal("expected") } }\n'
                                       'func TestTable(t *testing.T) {\n'
                                       '\tt.Run("one", func(t *testing.T) {})\n\tt.Run("two", func(t *testing.T) {})\n}\n')}
        repo, sha = make_git_repo(files)
        run = make_dir() / "run"
        runmod.init_run("sys", [("BACK", repo, "")], run, "es", False, "unknown")
        manifest = runmod.load(run)
        manifest["baseline"]["BACK"] = {"plan": detect.detect_repo(repo, sha)}
        runmod.save(run, manifest)
        result = bl.run_baseline(run, "BACK", 300)
        self.assertEqual((result["passed"], result["failed"], result["total"], result["runner"]), (2, 1, 3, "go"),
                         (run / result["output"]).read_text(encoding="utf-8")[-2000:])
        self.assertEqual(result.get("coverage_error"), "skipped: suite failing")

    def test_real_go_coverage_when_green(self):
        files = {"go.mod": "module example.com/m\n\ngo 1.21\n",
                 "calc/calc.go": "package calc\n\nfunc Add(a, b int) int { return a + b }\n\nfunc Sub(a, b int) int { return a - b }\n",
                 "calc/calc_test.go": ('package calc\n\nimport "testing"\n\n'
                                       'func TestAdd(t *testing.T) { if Add(1, 2) != 3 { t.Fatal("add") } }\n')}
        repo, sha = make_git_repo(files)
        run = make_dir() / "run"
        runmod.init_run("sys", [("BACK", repo, "")], run, "es", False, "unknown")
        manifest = runmod.load(run)
        manifest["baseline"]["BACK"] = {"plan": detect.detect_repo(repo, sha)}
        runmod.save(run, manifest)
        result = bl.run_baseline(run, "BACK", 300)
        self.assertEqual((result["passed"], result["failed"]), (1, 0))
        self.assertEqual(result["coverage"], 50.0, result.get("coverage_error"))


class RunBaselineTest(unittest.TestCase):
    def test_junit_reports_written_by_the_suite_give_the_counts(self):
        write = ("import os\nos.makedirs('target/surefire-reports')\n"
                 f"open('target/surefire-reports/TEST-a.xml', 'w').write({SUREFIRE.format(t=4, f=1, e=0, s=0)!r})\n"
                 "print('BUILD SUCCESS')\n")
        run, _, _ = make_run(test_cmd=[sys.executable, "-c", write], junit=["**/target/surefire-reports/TEST-*.xml"])
        result = bl.run_baseline(run, "BACK", 60)
        self.assertEqual((result["passed"], result["failed"], result["total"], result["runner"]), (3, 1, 4, "junit-xml"))
        self.assertTrue(result["parsed"])

    def test_junit_without_reports_falls_back_to_the_text(self):
        run, _, _ = make_run(junit=["**/target/surefire-reports/TEST-*.xml"])
        result = bl.run_baseline(run, "BACK", 60)
        self.assertEqual((result["passed"], result["runner"]), (1, "unittest"))

    def test_runs_in_worktree_not_user_checkout(self):
        run, repo, sha = make_run()
        before = git(repo, "rev-parse", "HEAD")
        result = bl.run_baseline(run, "BACK", 60)
        self.assertEqual((result["passed"], result["failed"], result["measured"]), (1, 0, True))
        self.assertEqual(result["runner"], "unittest")
        self.assertEqual(result["output"], "outputs/baseline-BACK.txt")
        self.assertEqual(len(git(repo, "worktree", "list").splitlines()), 1)
        self.assertEqual(git(repo, "rev-parse", "HEAD"), before)
        self.assertEqual(git(repo, "status", "--porcelain"), "")
        self.assertTrue((run / "outputs" / "baseline-BACK.txt").is_file())
        saved = runmod.load(run)["baseline"]["BACK"]
        self.assertEqual(saved["result"], result)
        self.assertIn("plan", saved)

    def test_saved_output_is_masked(self):
        noisy = ("import unittest\n\nclass T(unittest.TestCase):\n    def test_ok(self):\n"
                 "        print('key AKIA' + 'ABCDEFGHIJKLMNOP')\n")
        run, _, _ = make_run(files={"tests/test_a.py": noisy})
        bl.run_baseline(run, "BACK", 60)
        saved = (run / "outputs" / "baseline-BACK.txt").read_text(encoding="utf-8")
        self.assertNotIn("AKIAABCDEFGHIJKLMNOP", saved)
        self.assertIn("AKIA****", saved)

    def test_subdir_is_the_cwd(self):
        run, repo, sha = make_run(subdir="api")
        result = bl.run_baseline(run, "BACK", 60)
        self.assertEqual((result["passed"], result["failed"]), (1, 0))

    def test_failing_suite_is_data(self):
        failing = "import unittest\n\nclass T(unittest.TestCase):\n    def test_no(self):\n        self.assertTrue(False)\n"
        run, _, _ = make_run({"tests/test_a.py": failing})
        result = bl.run_baseline(run, "BACK", 60)
        self.assertEqual((result["passed"], result["failed"], result["total"]), (0, 1, 1))
        self.assertNotEqual(result["exit_code"], 0)
        self.assertTrue(result["measured"])

    def test_non_utf8_output_saved_and_parsed(self):
        noisy = ("import sys, unittest\n\nclass T(unittest.TestCase):\n    def test_ok(self):\n"
                 "        sys.stderr.buffer.write(b'\\xff\\xfe bad bytes\\n'); sys.stderr.flush()\n")
        run, _, _ = make_run({"tests/test_a.py": noisy})
        result = bl.run_baseline(run, "BACK", 60)
        self.assertEqual(result["passed"], 1)
        text = (run / "outputs" / "baseline-BACK.txt").read_text(encoding="utf-8")
        self.assertIn("bad bytes", text)

    def test_timeout_records_failure(self):
        run, repo, _ = make_run(test_cmd=[sys.executable, "-c", "import time; time.sleep(30)"])
        result = bl.run_baseline(run, "BACK", 1)
        self.assertTrue(result["timed_out"])
        self.assertFalse(result["measured"])
        self.assertEqual(len(git(repo, "worktree", "list").splitlines()), 1)

    def _detached(self, then: str) -> list:
        """A suite that starts a grandchild in its own session (out of the suite's process group) holding stdout,
        records its pid for cleanup, then runs `then`."""
        pidfile = make_dir() / "pid"
        self.addCleanup(_kill_pidfile, pidfile)
        code = ("import subprocess, sys\n"
                f"p = subprocess.Popen(['sleep', '30'], start_new_session=True)\n"
                f"open({str(pidfile)!r}, 'w').write(str(p.pid))\n" + then)
        return [sys.executable, "-c", code]

    def test_suite_that_exits_is_not_held_by_a_detached_grandchild(self):
        run, _, _ = make_run(test_cmd=self._detached("print('Ran 1 test in 0.0s'); print('OK')"))
        started = time.monotonic()
        result = bl.run_baseline(run, "BACK", 60)
        self.assertLess(time.monotonic() - started, 10)
        self.assertFalse(result["timed_out"])
        self.assertEqual((result["passed"], result["total"]), (1, 1))

    def test_background_process_of_the_suite_does_not_outlive_baseline(self):
        pidfile = make_dir() / "pid"
        self.addCleanup(_kill_pidfile, pidfile)
        run, _, _ = make_run(test_cmd=["sh", "-c", f"sleep 30 & echo $! > '{pidfile}'; "
                                                   "echo 'Ran 1 test in 0.0s'; echo OK"])
        result = bl.run_baseline(run, "BACK", 60)
        self.assertEqual(result["passed"], 1)
        pid = int(pidfile.read_text())
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.05)
        self.fail("the suite's background process outlived baseline")

    def test_a_pre_server_lives_through_the_suite(self):
        pidfile = make_dir() / "pid"
        self.addCleanup(_kill_pidfile, pidfile)
        check = (f"import os, sys\nos.kill(int(open({str(pidfile)!r}).read()), 0)\n"
                 "print('Ran 1 test in 0.0s'); print('OK')")
        run, _, _ = make_run(pre=[["sh", "-c", f"sleep 30 > /dev/null 2>&1 & echo $! > '{pidfile}'"]],
                             test_cmd=[sys.executable, "-c", check])
        result = bl.run_baseline(run, "BACK", 60)
        self.assertEqual((result["passed"], result["exit_code"]), (1, 0), result)

    def test_timeout_is_kept_with_a_detached_grandchild(self):
        run, repo, _ = make_run(test_cmd=self._detached("import time; time.sleep(60)"))
        started = time.monotonic()
        result = bl.run_baseline(run, "BACK", 2)
        self.assertLess(time.monotonic() - started, 10)
        self.assertTrue(result["timed_out"])
        self.assertEqual(len(git(repo, "worktree", "list").splitlines()), 1)

    def _hook(self, hooks_dir: Path) -> Path:
        marker = make_dir() / "hook-ran"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        hook = hooks_dir / "post-checkout"
        hook.write_text(f"#!/bin/sh\necho ran > '{marker}'\n", encoding="utf-8")
        hook.chmod(0o755)
        return marker

    def test_repo_hooks_never_run(self):
        run, repo, _ = make_run()
        marker = self._hook(repo / ".git" / "hooks")
        result = bl.run_baseline(run, "BACK", 60)
        self.assertEqual(result["passed"], 1)
        self.assertFalse(marker.exists(), "the audited repo's post-checkout hook ran")

    def test_hooks_path_of_the_repo_never_runs(self):
        run, repo, _ = make_run()
        marker = self._hook(repo / ".husky")
        git(repo, "config", "core.hooksPath", ".husky")
        bl.run_baseline(run, "BACK", 60)
        self.assertFalse(marker.exists(), "the core.hooksPath hook ran")

    def _not_executable(self) -> str:
        path = make_dir() / "notexec"
        path.write_bytes(b"\x00\x01garbage")
        path.chmod(0o755)
        return str(path)

    def test_exec_format_error_recorded_not_raised(self):
        run, repo, _ = make_run(test_cmd=[self._not_executable()])
        result = bl.run_baseline(run, "BACK", 60)
        self.assertFalse(result["measured"])
        self.assertIn("could not start", result["error"])
        self.assertEqual(runmod.load(run)["baseline"]["BACK"]["result"]["error"], result["error"])
        self.assertEqual(len(git(repo, "worktree", "list").splitlines()), 1)

    def test_coverage_exec_format_error_is_a_coverage_error(self):
        run, _, _ = make_run(coverage_cmd=[self._not_executable()])
        result = bl.run_baseline(run, "BACK", 60)
        self.assertEqual(result["passed"], 1)
        self.assertIn("could not start", result["coverage_error"])

    def test_missing_command_recorded_not_raised(self):
        run, _, _ = make_run(test_cmd=["definitely-not-a-binary-xyz"])
        result = bl.run_baseline(run, "BACK", 60)
        self.assertFalse(result["measured"])
        self.assertIn("could not start", result["error"])

    def test_symlinked_deps_dir_available_in_worktree(self):
        files = {"tests/test_a.py": "import unittest\nfrom vendor_deps import lib\n\n\nclass T(unittest.TestCase):\n"
                                    "    def test_ok(self):\n        self.assertEqual(lib.VALUE, 7)\n",
                 ".gitignore": "vendor_deps/\n"}
        run, repo, _ = make_run(files, deps="symlink", deps_dirs=["vendor_deps"])
        write_tree(repo, {"vendor_deps/lib.py": "VALUE = 7\n"})
        result = bl.run_baseline(run, "BACK", 60)
        self.assertEqual((result["passed"], result["failed"]), (1, 0))
        self.assertTrue((repo / "vendor_deps" / "lib.py").is_file())

    def test_without_deps_the_suite_fails_and_is_recorded(self):
        files = {"tests/test_a.py": "import unittest\nfrom vendor_deps import lib\n\n\nclass T(unittest.TestCase):\n"
                                    "    def test_ok(self):\n        self.assertEqual(lib.VALUE, 7)\n",
                 ".gitignore": "vendor_deps/\n"}
        run, repo, _ = make_run(files, deps="none", deps_dirs=["vendor_deps"])
        write_tree(repo, {"vendor_deps/lib.py": "VALUE = 7\n"})
        result = bl.run_baseline(run, "BACK", 60)
        self.assertGreaterEqual(result["failed"], 1)
        self.assertNotEqual(result["exit_code"], 0)

    def test_env_and_pre_applied(self):
        suite = ("import os, unittest\n\n\nclass T(unittest.TestCase):\n    def test_env(self):\n"
                 "        self.assertEqual(os.environ['IA_FIXTURE'], '1')\n    def test_pre(self):\n"
                 "        self.assertTrue(os.path.exists('pre.marker'))\n")
        pre = [[sys.executable, "-c", "open('pre.marker', 'w').close()"]]
        run, _, _ = make_run({"tests/test_a.py": suite}, env={"IA_FIXTURE": "1"}, pre=pre)
        result = bl.run_baseline(run, "BACK", 60)
        self.assertEqual((result["passed"], result["failed"]), (2, 0))

    def test_baseline_env_blocks_npx_downloads_and_plan_env_overrides(self):
        suite = ("import os, unittest\n\n\nclass T(unittest.TestCase):\n    def test_env(self):\n"
                 "        self.assertEqual(os.environ['npm_config_yes'], 'false')\n"
                 "        self.assertEqual(os.environ['CI'], 'override')\n")
        run, _, _ = make_run({"tests/test_a.py": suite}, env={"CI": "override"})
        self.assertEqual(bl.run_baseline(run, "BACK", 60)["passed"], 1)
        suite = suite.replace("'override'", "'1'")
        run, _, _ = make_run({"tests/test_a.py": suite})
        self.assertEqual(bl.run_baseline(run, "BACK", 60)["passed"], 1)

    def test_venv_interpreter_from_symlinked_deps_runs_the_suite(self):
        run, repo, _ = make_run({"tests/test_a.py": PASSING, ".gitignore": ".venv/\n"}, deps="symlink",
                                deps_dirs=[".venv"], test_cmd=[".venv/bin/python", "-m", "unittest", "discover", "-s",
                                                               "tests"])
        (repo / ".venv" / "bin").mkdir(parents=True)
        (repo / ".venv" / "bin" / "python").symlink_to(sys.executable)
        result = bl.run_baseline(run, "BACK", 60)
        self.assertEqual((result["passed"], result["failed"]), (1, 0), result)

    def test_install_runs_before_pre(self):
        suite = ("import os, unittest\n\n\nclass T(unittest.TestCase):\n    def test_order(self):\n"
                 "        self.assertEqual(open('order.txt').read(), 'install,pre,')\n")
        install = [sys.executable, "-c", "open('order.txt', 'a').write('install,')"]
        pre = [[sys.executable, "-c", "open('order.txt', 'a').write('pre,')"]]
        run, _, _ = make_run({"tests/test_a.py": suite}, deps="install", install_cmd=install, pre=pre)
        self.assertEqual(bl.run_baseline(run, "BACK", 60)["passed"], 1)

    def test_counts_from_test_cmd_coverage_from_coverage_cmd(self):
        cov = [sys.executable, "-c", "print('Tests  3 passed (3)'); print('All files | 55.5 |')"]
        run, _, _ = make_run(coverage_cmd=cov)
        result = bl.run_baseline(run, "BACK", 60)
        self.assertEqual((result["passed"], result["total"], result["runner"]), (1, 1, "unittest"))
        self.assertEqual(result["coverage"], 55.5)
        self.assertNotIn("coverage_error", result)
        self.assertTrue(result["parsed"])

    def test_failing_coverage_cmd_keeps_counts_and_records_error(self):
        cov = [sys.executable, "-c", "import sys; print('boom'); sys.exit(4)"]
        run, _, _ = make_run(coverage_cmd=cov)
        result = bl.run_baseline(run, "BACK", 60)
        self.assertEqual((result["passed"], result["failed"], result["measured"]), (1, 0, True))
        self.assertIsNone(result["coverage"])
        self.assertIn("exited 4", result["coverage_error"])
        self.assertNotIn("error", result)

    def test_failing_suite_skips_coverage_without_running_it(self):
        failing = "import unittest\n\nclass T(unittest.TestCase):\n    def test_no(self):\n        self.fail('x')\n"
        cov = [sys.executable, "-c", "print('COVERAGE-RAN All files | 55.5 |')"]
        run, _, _ = make_run({"tests/test_a.py": failing}, coverage_cmd=cov)
        result = bl.run_baseline(run, "BACK", 60)
        self.assertEqual(result["failed"], 1)
        self.assertIsNone(result["coverage"])
        self.assertEqual(result["coverage_error"], "skipped: suite failing")
        self.assertNotIn("COVERAGE-RAN", (run / result["output"]).read_text().replace("print(", ""))

    def test_unparsed_suite_skips_coverage(self):
        cov = [sys.executable, "-c", "print('All files | 55.5 |')"]
        run, _, _ = make_run(test_cmd=[sys.executable, "-c", "print('???')"], coverage_cmd=cov)
        result = bl.run_baseline(run, "BACK", 60)
        self.assertEqual(result["coverage_error"], "skipped: suite failing")
        self.assertIsNone(result["coverage"])

    def test_missing_coverage_binary_is_coverage_error(self):
        run, _, _ = make_run(coverage_cmd=["definitely-not-a-binary-xyz"])
        result = bl.run_baseline(run, "BACK", 60)
        self.assertEqual(result["passed"], 1)
        self.assertIn("could not start", result["coverage_error"])

    def test_unparseable_suite_output_is_measured_but_not_parsed(self):
        run, _, _ = make_run(test_cmd=[sys.executable, "-c", "print('all good, trust me')"])
        result = bl.run_baseline(run, "BACK", 60)
        self.assertTrue(result["measured"])
        self.assertFalse(result["parsed"])
        self.assertIsNone(result["passed"])

    def test_unknown_stack_records_unmeasured(self):
        run, _, _ = make_run(stack="unknown", test_cmd=None, measured=False)
        result = bl.run_baseline(run, "BACK", 60)
        self.assertFalse(result["measured"])
        self.assertIsNone(result["passed"])


class BaselineCliTest(unittest.TestCase):
    def test_runs_all_and_marks_step_done(self):
        run, _, _ = make_run()
        r = run_cli(["baseline", "--run", str(run)])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(runmod.load(run)["steps"]["baseline"], "done")
        self.assertIn("BACK", r.stdout)

    def test_failing_suite_still_exit_0(self):
        failing = "import unittest\n\nclass T(unittest.TestCase):\n    def test_no(self):\n        self.fail('x')\n"
        run, _, _ = make_run({"tests/test_a.py": failing})
        r = run_cli(["baseline", "--run", str(run)])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(runmod.load(run)["steps"]["baseline"], "done")

    def test_timeout_records_failure_exit_3(self):
        run, _, _ = make_run(test_cmd=[sys.executable, "-c", "import time; time.sleep(30)"])
        r = run_cli(["baseline", "--run", str(run), "--timeout", "1"])
        self.assertEqual(r.returncode, 3)
        manifest = runmod.load(run)
        self.assertTrue(manifest["baseline"]["BACK"]["result"]["timed_out"])
        self.assertNotEqual(manifest["steps"]["baseline"], "done")

    def _killed_mid_suite(self, signum: int):
        """Starts `ia baseline` on a long suite, sends `signum` to ia once the suite runs; (returncode, suite pid, repo)."""
        pidfile = make_dir() / "pid"
        self.addCleanup(_kill_pidfile, pidfile)
        code = f"import os, time\nopen({str(pidfile)!r}, 'w').write(str(os.getpid()))\ntime.sleep(60)\n"
        run, repo, _ = make_run(test_cmd=[sys.executable, "-c", code])
        # A shell starts background jobs with SIGINT ignored, and Python keeps an inherited SIG_IGN: give ia the
        # default disposition a terminal would, so the test does not depend on how the suite itself was launched.
        proc = subprocess.Popen([sys.executable, str(SKILL / "ia.py"), "baseline", "--run", str(run), "--timeout", "120"],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL))
        deadline = time.monotonic() + 30
        while not (pidfile.exists() and pidfile.read_text()) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(pidfile.exists(), "the suite never started")
        proc.send_signal(signum)
        proc.communicate(timeout=30)
        return proc.returncode, int(pidfile.read_text()), repo

    def _assert_cleaned(self, suite_pid: int, repo) -> None:
        deadline = time.monotonic() + 5
        alive = True
        while alive and time.monotonic() < deadline:
            try:
                os.kill(suite_pid, 0)
                time.sleep(0.05)
            except ProcessLookupError:
                alive = False
        self.assertFalse(alive, "the suite outlived ia")
        self.assertEqual(len(git(repo, "worktree", "list").splitlines()), 1)

    def test_sigterm_kills_the_suite_and_removes_the_worktree(self):
        code, pid, repo = self._killed_mid_suite(signal.SIGTERM)
        self.assertEqual(code, 128 + signal.SIGTERM)
        self._assert_cleaned(pid, repo)

    def test_sighup_kills_the_suite_and_removes_the_worktree(self):
        code, pid, repo = self._killed_mid_suite(signal.SIGHUP)
        self.assertEqual(code, 128 + signal.SIGHUP)
        self._assert_cleaned(pid, repo)

    def test_sigint_kills_the_suite_and_removes_the_worktree(self):
        code, pid, repo = self._killed_mid_suite(signal.SIGINT)
        self.assertEqual(code, 128 + signal.SIGINT)
        self._assert_cleaned(pid, repo)

    def test_set_manual_result_closes_step_with_source_manual(self):
        run, _, _ = make_run(test_cmd=[sys.executable, "-c", "print('???')"])
        r = run_cli(["baseline", "--run", str(run)])
        self.assertEqual(runmod.load(run)["steps"]["baseline"], "pending", r.stdout)
        s = run_cli(["set", "--run", str(run), "baseline.BACK.result.passed=7", "baseline.BACK.result.failed=0",
                     "baseline.BACK.result.total=7", "baseline.BACK.result.coverage=81.5",
                     "baseline.BACK.result.runner=custom", "baseline.BACK.result.measured=true"])
        self.assertEqual(s.returncode, 0, s.stderr)
        m = runmod.load(run)
        result = m["baseline"]["BACK"]["result"]
        self.assertEqual((result["passed"], result["total"], result["coverage"], result["runner"]),
                         (7, 7, 81.5, "custom"))
        self.assertEqual(result["source"], "manual")
        self.assertEqual(m["steps"]["baseline"], "done")

    def test_set_total_zero_for_repo_without_runner(self):
        run, _, _ = make_run(stack="unknown", test_cmd=None, measured=False)
        s = run_cli(["set", "--run", str(run), "baseline.BACK.result.total=0", "baseline.BACK.result.coverage=null"])
        self.assertEqual(s.returncode, 0, s.stderr)
        result = runmod.load(run)["baseline"]["BACK"]["result"]
        self.assertEqual((result["total"], result["coverage"], result["source"]), (0, None, "manual"))

    def test_unknown_stack_stays_open_until_a_manual_result(self):
        run, _, _ = make_run(stack="unknown", test_cmd=None, measured=False)
        r = run_cli(["baseline", "--run", str(run)])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("run the suite", r.stdout)
        self.assertIn("ia.py set --run", r.stdout)
        self.assertIn("baseline.BACK.result.passed=", r.stdout)
        self.assertIn("baseline.BACK.result.total=0", r.stdout)
        self.assertNotIn("ia.py step", r.stdout)
        self.assertEqual(runmod.load(run)["steps"]["baseline"], "pending")
        self.assertFalse(runmod.baselines_closed(runmod.load(run)))
        s = run_cli(["set", "--run", str(run), "baseline.BACK.result.total=0"])
        self.assertEqual(s.returncode, 0, s.stderr)
        self.assertEqual(runmod.load(run)["steps"]["baseline"], "done")

    def test_unparsed_summary_points_to_ia_set(self):
        run, _, _ = make_run(test_cmd=[sys.executable, "-c", "print('???')"])
        r = run_cli(["baseline", "--run", str(run)])
        self.assertIn("ia.py set --run", r.stdout)
        self.assertIn("baseline.BACK.result.passed=", r.stdout)

    def test_failing_coverage_cmd_still_marks_step_done(self):
        run, _, _ = make_run(coverage_cmd=[sys.executable, "-c", "raise SystemExit(4)"])
        r = run_cli(["baseline", "--run", str(run)])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("passed: 1", r.stdout)
        self.assertIn("coverage failed", r.stdout)
        self.assertEqual(runmod.load(run)["steps"]["baseline"], "done")

    def test_unparseable_counts_keep_step_pending_and_ask_the_model(self):
        run, _, _ = make_run(test_cmd=[sys.executable, "-c", "print('all good, trust me')"])
        r = run_cli(["baseline", "--run", str(run)])
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("could not parse", r.stdout)
        self.assertIn("record the numbers", r.stdout)
        self.assertNotEqual(runmod.load(run)["steps"]["baseline"], "done")

    def test_set_edits_plan_with_json_values_and_runs_nothing(self):
        run, _, _ = make_run()
        r = run_cli(["baseline", "--run", str(run), "--set", "BACK", 'env={"A":"1"}', 'pre=[["make","db"]]',
                     "deps=symlink", 'deps_dirs=["node_modules"]'])
        self.assertEqual(r.returncode, 0, r.stderr)
        entry = runmod.load(run)["baseline"]["BACK"]
        self.assertEqual(entry["plan"]["env"], {"A": "1"})
        self.assertEqual(entry["plan"]["pre"], [["make", "db"]])
        self.assertEqual(entry["plan"]["deps"], "symlink")
        self.assertEqual(entry["plan"]["test_cmd"], UNITTEST_CMD)
        self.assertNotIn("result", entry)
        self.assertEqual(runmod.load(run)["steps"]["baseline"], "pending")

    def test_set_plain_string_value(self):
        run, _, _ = make_run()
        r = run_cli(["baseline", "--run", str(run), "--set", "BACK", "stack=node"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(runmod.load(run)["baseline"]["BACK"]["plan"]["stack"], "node")

    def test_set_bad_pair_exit_2(self):
        run, _, _ = make_run()
        r = run_cli(["baseline", "--run", str(run), "--set", "BACK", "nonsense"])
        self.assertEqual(r.returncode, 2)
        self.assertIn("KEY=VALUE", r.stderr)

    def test_set_bad_deps_or_key_exit_2(self):
        run, _, _ = make_run()
        self.assertEqual(run_cli(["baseline", "--run", str(run), "--set", "BACK", "deps=magic"]).returncode, 2)
        self.assertEqual(run_cli(["baseline", "--run", str(run), "--set", "BACK", "bogus=1"]).returncode, 2)

    def test_set_rejects_wrong_shapes_exit_2(self):
        run, _, _ = make_run()
        bad = ["pre=foo", 'pre=["make"]', 'pre=[[1]]', 'env=["A"]', 'env={"A":1}', "env=x", "test_cmd=pytest",
               'test_cmd=[1]', 'coverage_cmd="x"', "install_cmd=1", 'deps_dirs="node_modules"', "measure=3",
               "measured=yes"]
        for pair in bad:
            r = run_cli(["baseline", "--run", str(run), "--set", "BACK", pair])
            self.assertEqual(r.returncode, 2, pair)
        self.assertEqual(runmod.load(run)["baseline"]["BACK"]["plan"]["pre"], [])

    def test_set_accepts_valid_shapes_and_null(self):
        run, _, _ = make_run()
        r = run_cli(["baseline", "--run", str(run), "--set", "BACK", "test_cmd=null", 'coverage_cmd=["x","y"]',
                     "measured=false", 'measure=["ruff"]'])
        self.assertEqual(r.returncode, 0, r.stderr)
        p = runmod.load(run)["baseline"]["BACK"]["plan"]
        self.assertEqual((p["test_cmd"], p["coverage_cmd"], p["measured"]), (None, ["x", "y"], False))

    def test_failing_pre_exit_1_unmeasured_step_not_done(self):
        run, _, _ = make_run(pre=[[sys.executable, "-c", "raise SystemExit(4)"]])
        r = run_cli(["baseline", "--run", str(run)])
        self.assertEqual(r.returncode, 1)
        manifest = runmod.load(run)
        result = manifest["baseline"]["BACK"]["result"]
        self.assertFalse(result["measured"])
        self.assertIn("pre", result["error"])
        self.assertNotEqual(manifest["steps"]["baseline"], "done")

    def test_unknown_alias_exit_2(self):
        run, _, _ = make_run()
        self.assertEqual(run_cli(["baseline", "--run", str(run), "--alias", "NOPE"]).returncode, 2)
        self.assertEqual(run_cli(["baseline", "--run", str(run), "--set", "NOPE", "deps=none"]).returncode, 2)

    def test_without_plan_asks_for_detect(self):
        run, _, _ = make_run()
        manifest = runmod.load(run)
        manifest["baseline"] = {}
        runmod.save(run, manifest)
        r = run_cli(["baseline", "--run", str(run)])
        self.assertEqual(r.returncode, 2)
        self.assertIn("detect", r.stderr)

    def test_alias_runs_only_that_repo_and_keeps_step_pending(self):
        a, _ = make_git_repo({"tests/test_a.py": PASSING})
        b, _ = make_git_repo({"tests/test_a.py": PASSING})
        run = make_dir() / "run"
        runmod.init_run("sys", [("A", a, ""), ("B", b, "")], run, "es", False, "unknown")
        manifest = runmod.load(run)
        manifest["baseline"] = {"A": {"plan": plan()}, "B": {"plan": plan()}}
        runmod.save(run, manifest)
        r = run_cli(["baseline", "--run", str(run), "--alias", "A"])
        self.assertEqual(r.returncode, 0, r.stderr)
        manifest = runmod.load(run)
        self.assertIn("result", manifest["baseline"]["A"])
        self.assertNotIn("result", manifest["baseline"]["B"])
        self.assertEqual(manifest["steps"]["baseline"], "pending")


if __name__ == "__main__":
    unittest.main()
