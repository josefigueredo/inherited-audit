from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr
from unittest import mock

from helpers import git, make_dir, make_git_repo, run_cli, write_tree

from ia import branches
from ia import findings as findingsmod
from ia import run as runmod


def commit_on(repo, branch, files, base="main"):
    git(repo, "checkout", "-q", "-b", branch, base)
    write_tree(repo, files)
    git(repo, "add", "-A")
    git(repo, "-c", "commit.gpgsign=false", "commit", "-q", "-m", branch)
    git(repo, "checkout", "-q", base)


def new_run(repo, aliases=("BACK",)):
    out = make_dir() / "run"
    args = ["init", "--system", "s", "--out", str(out)]
    for alias in aliases:
        args += ["--repo", f"{alias}={repo}"]
    assert run_cli(args).returncode == 0
    return out


def add_finding(run, alias, branch, verdict="confirmed", path="a.py"):
    findingsmod.add(run, {
        "report": "quality", "suggestion": "s", "effort": "S", "category": "x", "dimension": "bug", "title": "t", "verdict": verdict,
        "severity": "low", "confidence": "execution", "source": "t", "what_happens": "w", "branch": branch,
        "evidence": [{"cite": f"{alias}/{path}", "from": 1, "to": 1, "note": ""}]})


class SupportTest(unittest.TestCase):
    def test_version_parsing(self):
        self.assertFalse(branches.git_supports_merge_tree("git version 2.30.0"))
        self.assertTrue(branches.git_supports_merge_tree("git version 2.38.0"))
        self.assertTrue(branches.git_supports_merge_tree("git version 2.54.0 (Apple Git-157)"))
        self.assertTrue(branches.git_supports_merge_tree("git version 3.0.1"))
        self.assertFalse(branches.git_supports_merge_tree("garbage"))


class PairwiseTest(unittest.TestCase):
    def test_clean_and_conflicting(self):
        repo, _ = make_git_repo({"a.py": "one\n", "b.py": "x\n"})
        commit_on(repo, "fix/a", {"a.py": "A\n"})
        commit_on(repo, "fix/b", {"b.py": "B\n"})
        commit_on(repo, "fix/c", {"a.py": "C\n"})
        result = {(a, b): (clean, paths) for a, b, clean, paths in
                  branches.pairwise(repo, ["fix/a", "fix/b", "fix/c"])}
        self.assertEqual(result[("fix/a", "fix/b")], (True, []))
        self.assertEqual(result[("fix/b", "fix/c")], (True, []))
        self.assertEqual(result[("fix/a", "fix/c")], (False, ["a.py"]))


class CliTest(unittest.TestCase):
    def test_independent_branches_clean(self):
        repo, _ = make_git_repo({"a.py": "one\n", "b.py": "x\n"})
        commit_on(repo, "fix/a", {"a.py": "A\n"})
        commit_on(repo, "fix/b", {"b.py": "B\n"})
        run = new_run(repo)
        add_finding(run, "BACK", "fix/a")
        add_finding(run, "BACK", "fix/b")
        add_finding(run, "BACK", "fix/ignored", verdict="candidate")
        proc = run_cli(["merge-check", "--run", str(run)])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("fix/a", proc.stdout)
        self.assertIn("clean", proc.stdout)
        self.assertNotIn("ignored", proc.stdout)

    def test_conflicting_branches_listed_with_paths(self):
        repo, _ = make_git_repo({"a.py": "one\n"})
        commit_on(repo, "fix/a", {"a.py": "A\n"})
        commit_on(repo, "fix/c", {"a.py": "C\n"})
        run = new_run(repo)
        add_finding(run, "BACK", "fix/a")
        add_finding(run, "BACK", "fix/c")
        proc = run_cli(["merge-check", "--run", str(run)])
        self.assertEqual(proc.returncode, 1)
        self.assertIn("CONFLICT", proc.stdout)
        self.assertIn("a.py", proc.stdout)

    def test_tests_branch_included_and_aliases_group_by_path(self):
        repo, _ = make_git_repo({"a.py": "one\n", "t.py": "x\n"})
        commit_on(repo, "fix/a", {"a.py": "A\n"})
        commit_on(repo, "tests/t", {"a.py": "T\n"})
        run = new_run(repo, aliases=("BACK", "ALIAS2"))
        manifest = runmod.load(run)
        manifest["baseline"].setdefault("ALIAS2", {})["tests_branch"] = "tests/t"
        runmod.save(run, manifest)
        add_finding(run, "BACK", "fix/a")
        proc = run_cli(["merge-check", "--run", str(run)])
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("tests/t", proc.stdout)

    def test_fewer_than_two_nothing_to_compare(self):
        repo, _ = make_git_repo({"a.py": "one\n"})
        commit_on(repo, "fix/a", {"a.py": "A\n"})
        run = new_run(repo)
        add_finding(run, "BACK", "fix/a")
        proc = run_cli(["merge-check", "--run", str(run)])
        self.assertEqual(proc.returncode, 0)
        self.assertIn("nothing to compare", proc.stdout)

    def test_missing_branch_exit_1(self):
        repo, _ = make_git_repo({"a.py": "one\n"})
        commit_on(repo, "fix/a", {"a.py": "A\n"})
        run = new_run(repo)
        add_finding(run, "BACK", "fix/a")
        add_finding(run, "BACK", "fix/ghost")
        proc = run_cli(["merge-check", "--run", str(run)])
        self.assertEqual(proc.returncode, 1)
        self.assertIn("fix/ghost", proc.stderr + proc.stdout)

    def test_old_git_exit_3(self):
        repo, _ = make_git_repo({"a.py": "one\n"})
        run = new_run(repo)
        with self.assertRaises(runmod.ToolError):
            branches.check_run(run, version_text="git version 2.30.0")
        from ia import cli
        err = io.StringIO()
        with mock.patch.object(branches, "git_supports_merge_tree", return_value=False), redirect_stderr(err):
            self.assertEqual(cli.main(["merge-check", "--run", str(run)]), 3)
        self.assertIn("git >= 2.38", err.getvalue())


if __name__ == "__main__":
    unittest.main()
