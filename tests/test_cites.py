from __future__ import annotations

import unittest

from helpers import git, make_dir, make_git_repo, run_cli, write_tree

from ia import cites
from ia import findings as findingsmod
from ia import run as runmod

BODY = "".join(f"line {i}\n" for i in range(1, 11))


def manifest_for(repo, sha, subdir="", remote="", alias="BACK"):
    return {"repos": [{"alias": alias, "path": str(repo), "subdir": subdir, "sha": sha, "remote": remote}]}


def finding(cite, start, end, fid="C-01"):
    return {"id": fid, "evidence": [{"cite": cite, "from": start, "to": end, "note": ""}]}


class CheckCitesTest(unittest.TestCase):
    def test_valid_cite_passes(self):
        repo, sha = make_git_repo({"src/a.py": BODY})
        self.assertEqual(cites.check_cites(manifest_for(repo, sha), [finding("BACK/src/a.py", 2, 10)]), [])

    def test_unknown_alias(self):
        repo, sha = make_git_repo({"src/a.py": BODY})
        problems = cites.check_cites(manifest_for(repo, sha), [finding("NOPE/src/a.py", 1, 2)])
        self.assertEqual(problems, ["C-01: NOPE/src/a.py:1-2: unknown alias"])

    def test_path_missing_at_sha_even_if_present_in_worktree(self):
        repo, sha = make_git_repo({"src/a.py": BODY})
        write_tree(repo, {"src/new.py": BODY})
        git(repo, "add", "-A")
        git(repo, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "later")
        problems = cites.check_cites(manifest_for(repo, sha), [finding("BACK/src/new.py", 1, 2)])
        self.assertEqual(problems, [f"C-01: BACK/src/new.py:1-2: path not found at {sha[:7]}"])

    def test_range_past_eof_reports_line_count(self):
        repo, sha = make_git_repo({"src/a.py": BODY})
        problems = cites.check_cites(manifest_for(repo, sha), [finding("BACK/src/a.py", 5, 11)])
        self.assertEqual(problems, ["C-01: BACK/src/a.py:5-11: range past end of file (10 lines)"])

    def test_from_greater_than_to(self):
        repo, sha = make_git_repo({"src/a.py": BODY})
        problems = cites.check_cites(manifest_for(repo, sha), [finding("BACK/src/a.py", 6, 3)])
        self.assertEqual(problems, ["C-01: BACK/src/a.py:6-3: from > to"])

    def test_subdir_prefixed(self):
        repo, sha = make_git_repo({"svc/src/a.py": BODY, "src/a.py": "x\n"})
        m = manifest_for(repo, sha, subdir="svc")
        self.assertEqual(cites.check_cites(m, [finding("BACK/src/a.py", 1, 10)]), [])
        self.assertEqual(len(cites.check_cites(m, [finding("BACK/src/a.py", 1, 11)])), 1)

    def test_unparseable_cite_does_not_crash(self):
        repo, sha = make_git_repo({"a.py": BODY})
        problems = cites.check_cites(manifest_for(repo, sha), [finding("justafile", 1, 2)])
        self.assertEqual(problems, ["C-01: justafile: not ALIAS/path"])

    def test_directory_cite_is_a_problem(self):
        repo, sha = make_git_repo({"src/a.py": BODY})
        problems = cites.check_cites(manifest_for(repo, sha), [finding("BACK/src", 1, 1)])
        self.assertEqual(problems, [f"C-01: BACK/src:1-1: path is a directory at {sha[:7]}"])

    def test_non_dict_evidence_is_a_problem(self):
        repo, sha = make_git_repo({"a.py": BODY})
        f = {"id": "C-01", "evidence": ["BACK/a.py", None]}
        problems = cites.check_cites(manifest_for(repo, sha), [f])
        self.assertEqual(problems, ["C-01: evidence entry is not an object"] * 2)

    def test_empty_file_any_range_is_past_eof(self):
        repo, sha = make_git_repo({"empty.txt": ""})
        problems = cites.check_cites(manifest_for(repo, sha), [finding("BACK/empty.txt", 1, 1)])
        self.assertEqual(problems, ["C-01: BACK/empty.txt:1-1: range past end of file (0 lines)"])

    def test_bad_numbers(self):
        repo, sha = make_git_repo({"a.py": BODY})
        m = manifest_for(repo, sha)
        self.assertIn("from/to must be integers", cites.check_cites(m, [finding("BACK/a.py", "1", 2)])[0])
        self.assertIn("from/to must be integers", cites.check_cites(m, [finding("BACK/a.py", True, 2)])[0])
        problems = cites.check_cites(m, [finding("BACK/a.py", 0, 2)])
        self.assertEqual(len(problems), 1)
        self.assertIn("from must be >= 1", problems[0])


class ParseCiteTest(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(cites.parse_cite("BACK/src/a.py"), ("BACK", "src/a.py", None))

    def test_no_slash(self):
        with self.assertRaises(ValueError):
            cites.parse_cite("BACK")


class LinkForTest(unittest.TestCase):
    SHA = "a" * 40

    def repo(self, remote, subdir=""):
        return {"alias": "BACK", "path": "/x", "subdir": subdir, "sha": self.SHA, "remote": remote}

    def test_link_github_pinned(self):
        self.assertEqual(cites.link_for(self.repo("https://github.com/o/r"), "src/a.py", 3, 9),
                         f"https://github.com/o/r/blob/{self.SHA}/src/a.py#L3-L9")

    def test_single_line(self):
        self.assertTrue(cites.link_for(self.repo("https://github.com/o/r"), "a.py", 4, 4).endswith("#L4"))

    def test_subdir(self):
        self.assertEqual(cites.link_for(self.repo("https://github.com/o/r", "svc"), "a.py", 1, 2),
                         f"https://github.com/o/r/blob/{self.SHA}/svc/a.py#L1-L2")

    def test_gitlab(self):
        self.assertEqual(cites.link_for(self.repo("https://gitlab.example.com/g/r"), "a.py", 1, 2),
                         f"https://gitlab.example.com/g/r/-/blob/{self.SHA}/a.py#L1-L2")

    def test_enterprise_github(self):
        self.assertIn("/blob/", cites.link_for(self.repo("https://git.corp.example/o/r"), "a.py", 1, 2))
        self.assertNotIn("/-/", cites.link_for(self.repo("https://git.corp.example/o/r"), "a.py", 1, 2))

    def test_link_none_without_remote(self):
        self.assertIsNone(cites.link_for(self.repo(""), "a.py", 1, 2))


class CiteCheckCliTest(unittest.TestCase):
    def make_run(self):
        repo, sha = make_git_repo({"src/a.py": BODY})
        run = make_dir() / "run"
        runmod.init_run("sys", [("BACK", repo, "")], run, "es", False, "unknown")
        return run

    def add(self, run, cite, start, end):
        data = {"report": "correctness", "category": "x", "dimension": "bug", "title": "t", "verdict": "candidate",
                "severity": "low", "confidence": "unverified", "source": "s", "what_happens": "w",
                "evidence": [{"cite": cite, "from": start, "to": end, "note": "n"}]}
        findingsmod.add(run, data)

    def test_clean_exit_0(self):
        run = self.make_run()
        self.add(run, "BACK/src/a.py", 1, 3)
        r = run_cli(["cite-check", "--run", str(run)])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("all 1 citations resolve", r.stdout)

    def test_problem_exit_1(self):
        run = self.make_run()
        self.add(run, "BACK/src/a.py", 1, 30)
        r = run_cli(["cite-check", "--run", str(run)])
        self.assertEqual(r.returncode, 1)
        self.assertIn("range past end of file (10 lines)", r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()


class HistoryCiteTest(unittest.TestCase):
    def history_repo(self):
        repo, first = make_git_repo({"src/.env": BODY, "src/a.py": BODY})
        git(repo, "rm", "-q", "src/.env")
        git(repo, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "drop env")
        return repo, first, git(repo, "rev-parse", "HEAD")

    def test_parse_cite_returns_commit_or_none(self):
        self.assertEqual(cites.parse_cite("BACK/src/a.py"), ("BACK", "src/a.py", None))
        self.assertEqual(cites.parse_cite("BACK/src/a.py@abc1234"), ("BACK", "src/a.py", "abc1234"))
        self.assertEqual(cites.parse_cite("BACK/node_modules/@s/x.js"), ("BACK", "node_modules/@s/x.js", None))
        self.assertEqual(cites.parse_cite("BACK/src/a.py@abc1234", with_commit=False), ("BACK", "src/a.py"))

    def test_history_cite_resolves_at_that_commit(self):
        repo, first, head = self.history_repo()
        m = manifest_for(repo, head)
        self.assertEqual(cites.check_cites(m, [finding(f"BACK/src/.env@{first[:7]}", 1, 3)]), [])
        problems = cites.check_cites(m, [finding("BACK/src/.env", 1, 3)])
        self.assertEqual(problems, [f"C-01: BACK/src/.env:1-3: path not found at {head[:7]}"])

    def test_history_cite_checks_lines_at_that_commit(self):
        repo, first, head = self.history_repo()
        problems = cites.check_cites(manifest_for(repo, head), [finding(f"BACK/src/.env@{first}", 1, 99)])
        self.assertEqual(problems, [f"C-01: BACK/src/.env@{first}:1-99: range past end of file (10 lines)"])

    def test_commit_must_be_ancestor_of_base(self):
        repo, first, head = self.history_repo()
        git(repo, "checkout", "-q", "-b", "side", first)
        write_tree(repo, {"src/b.py": BODY})
        git(repo, "add", "-A")
        git(repo, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "side")
        side = git(repo, "rev-parse", "HEAD")
        problems = cites.check_cites(manifest_for(repo, head), [finding(f"BACK/src/b.py@{side[:7]}", 1, 2)])
        self.assertEqual(problems, [f"C-01: BACK/src/b.py@{side[:7]}:1-2: commit {side[:7]} is not an ancestor of "
                                    f"or equal to the base {head[:7]}"])
        self.assertEqual(cites.check_cites(manifest_for(repo, head), [finding(f"BACK/src/a.py@{head[:7]}", 1, 2)]), [])

    def test_unknown_commit(self):
        repo, _, head = self.history_repo()
        problems = cites.check_cites(manifest_for(repo, head), [finding("BACK/src/a.py@deadbee", 1, 2)])
        self.assertEqual(problems, ["C-01: BACK/src/a.py@deadbee:1-2: commit deadbee not found"])
