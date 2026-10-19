from __future__ import annotations

import unittest

from helpers import make_git_repo, run_cli

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

    def test_make_git_repo_returns_head_sha(self):
        repo, sha = make_git_repo({"a.txt": "x"}, remote="https://github.com/o/r")
        self.assertEqual(len(sha), 40)
        self.assertTrue((repo / "a.txt").is_file())


if __name__ == "__main__":
    unittest.main()
