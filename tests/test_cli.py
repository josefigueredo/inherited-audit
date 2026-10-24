from __future__ import annotations

import argparse
import contextlib
import io
import json
import subprocess
import sys
import unittest

from helpers import SKILL, make_dir, make_git_repo, run_cli

from ia import cli, run as runmod

IMPLEMENTED = {"init", "status", "step", "finding", "detect", "baseline", "cite-check", "merge-check", "hygiene", "filter", "publish", "render", "eval", "set", "coverage"}
SUBCOMMANDS = "init status step finding detect baseline cite-check merge-check hygiene filter publish render eval set coverage".split()


class CliTest(unittest.TestCase):
    def test_no_args_prints_usage_exit_2(self):
        result = run_cli([])
        self.assertEqual(result.returncode, 2)
        self.assertIn("usage", result.stderr.lower())

    def test_help_lists_every_subcommand(self):
        out = run_cli(["-h"]).stdout
        for name in SUBCOMMANDS:
            self.assertIn(name, out)

    def test_unimplemented_subcommand_says_so_and_exits_2(self):
        for name in SUBCOMMANDS:
            if name in IMPLEMENTED:
                continue
            result = run_cli([name])
            self.assertEqual(result.returncode, 2, name)
            self.assertIn(f"{name}: not implemented", result.stderr)

    def test_unexpected_error_is_exit_4_in_one_line(self):
        def boom(_args):
            raise ZeroDivisionError("division by zero")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = cli._guard(boom)(argparse.Namespace())
        self.assertEqual(code, 4)
        self.assertEqual(len(err.getvalue().strip().splitlines()), 1, err.getvalue())
        self.assertIn("ZeroDivisionError: division by zero", err.getvalue())

    def test_unwritable_findings_dir_is_not_a_usage_error(self):
        repo, _ = make_git_repo({"a.txt": "x\n"})
        run = runmod.init_run("sys", [("BACK", repo, "")], make_dir() / "run", "es", False, "unknown")
        src = make_dir() / "f.json"
        src.write_text(json.dumps({"report": "correctness", "category": "c", "dimension": "bug", "title": "t",
                                   "verdict": "candidate", "severity": "low", "confidence": "unverified",
                                   "source": "s", "what_happens": "w",
                                   "evidence": [{"cite": "BACK/a.txt", "from": 1, "to": 1}]}), encoding="utf-8")
        (run / "findings").chmod(0o555)
        self.addCleanup((run / "findings").chmod, 0o755)
        result = run_cli(["finding", "add", "--run", str(run), str(src)])
        self.assertEqual(result.returncode, 4, result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_missing_input_file_is_still_a_usage_error(self):
        repo, _ = make_git_repo({"a.txt": "x\n"})
        run = runmod.init_run("sys", [("BACK", repo, "")], make_dir() / "run", "es", False, "unknown")
        self.assertEqual(run_cli(["finding", "add", "--run", str(run), str(make_dir() / "nope.json")]).returncode, 2)

    def test_imports_without_fcntl_or_sighup(self):
        """Windows has neither: the CLI must still import (baseline is POSIX-only, the other commands are not)."""
        code = ("import sys, signal\nsys.modules['fcntl'] = None\ndel signal.SIGHUP\n"
                f"sys.path.insert(0, {str(SKILL)!r})\nimport ia.cli\nprint(ia.cli.STOP_SIGNALS)")
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_make_git_repo_returns_head_sha(self):
        repo, sha = make_git_repo({"a.txt": "x"}, remote="https://github.com/o/r")
        self.assertEqual(len(sha), 40)
        self.assertTrue((repo / "a.txt").is_file())



class MaskCommandTest(unittest.TestCase):
    DEFAULT = "s3cr3tDefault9"

    def mask(self, text, *args):
        return subprocess.run([sys.executable, str(SKILL / "ia.py"), "mask", *args], input=text, capture_output=True,
                              text=True)

    def test_mask_reads_stdin_and_writes_it_masked_line_for_line(self):
        ghp = "ghp_" + "a1B2c3D4e5" * 3 + "a1B2c3"
        text = (f"ok\n{{\"headers\":{{\"X-API-Token\":\"{self.DEFAULT}\"}}}}\nexport DB_PASSWORD={self.DEFAULT}\n"
                f"{ghp}\n")
        res = self.mask(text)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertNotIn(self.DEFAULT, res.stdout)
        self.assertNotIn(ghp, res.stdout)
        self.assertEqual(res.stdout.count("\n"), text.count("\n"))
        self.assertTrue(res.stdout.startswith("ok\n"))

    def test_mask_config_also_masks_bare_assignments(self):
        line = "  password: " + self.DEFAULT + "\n"
        self.assertIn(self.DEFAULT, self.mask(line).stdout)
        self.assertEqual(self.mask(line, "--config").stdout, "  password: ****\n")


if __name__ == "__main__":
    unittest.main()
