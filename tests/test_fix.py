"""ia.py fix (inherited-fix): plan, start, check, done and publish on a repo whose suite is a shell script that writes a
JUnit report from the content of its production files, with a bare local remote and a fake gh."""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from helpers import SKILL, git, make_dir, make_git_repo

from ia import findings as findingsmod
from ia import fix as fixmod
from ia import hygiene as hygienemod
from ia import publish as publishmod
from ia import run as runmod
from test_branches import new_run

SUITE = r"""#!/bin/sh
mkdir -p build
p=0; f=0; cases=""
tc() {
  if [ "$3" = pass ]; then p=$((p+1)); cases="$cases<testcase classname=\"$2\" name=\"$1\"/>"
  else f=$((f+1)); cases="$cases<testcase classname=\"$2\" name=\"$1\"><failure message=\"no\"/></testcase>"; fi
}
has() { if grep -q "$1" "$2" 2>/dev/null; then echo pass; else echo fail; fi }
tc test_one tests.BaseTest pass
if grep -q break src/calc.py; then tc test_two tests.BaseTest fail; else tc test_two tests.BaseTest pass; fi
if [ -f tests/CalcTest.py ]; then tc test_add tests.CalcTest "$(has fixed src/calc.py)"; fi
if [ -f tests/AuditTest.py ]; then tc test_audit tests.AuditTest "$(has fixed1 src/audit.py)"; fi
if [ -f tests/Audit2Test.py ]; then tc test_audit2 tests.Audit2Test "$(has fixed2 src/audit.py)"; fi
echo "<testsuite name=\"all\" tests=\"$((p+f))\" failures=\"$f\">$cases</testsuite>" > build/TEST-all.xml
if [ $f -gt 0 ]; then echo "$f failed, $p passed in 0.01s"; exit 1; fi
echo "$p passed in 0.01s"
"""

GH = r"""#!/bin/sh
echo "$*" >> "$FAKE_GH_LOG"
case "$1 $2" in
  "pr list") case "$*" in *--jq*) echo "${FAKE_GH_NUMBER:-7}" ;; *) printf '%s\n' "${FAKE_GH_PRS:-[]}" ;; esac ;;
  "pr view") cat "$FAKE_GH_BODY" ;;
esac
"""

# Split so this file never carries a real attribution line.
TRAILER = "Co-Authored-" + "By: Claude <noreply@" + "anthropic.com>"


def commit(repo: Path, message: str, *paths: str) -> str:
    git(repo, "add", *paths) if paths else git(repo, "add", "-A")
    git(repo, "-c", "commit.gpgsign=false", "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def write(repo: Path, rel: str, text: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def red_finding(run: Path, fid: str, branch: str, sha: str, test: str, prod: str, red: str = "1 of 1 fail") -> None:
    findingsmod.add(run, {
        "id": fid, "report": "correctness", "category": "x", "dimension": "bug", "title": f"Bug {fid}",
        "verdict": "confirmed", "severity": "high", "confidence": "execution", "source": "t",
        "what_happens": "It breaks.", "fix_summary": f"Repair {prod}.", "branch": branch, "sha_test": sha,
        "prod_files": [prod], "tests": [{"path": test, "red": red, "green": "", "note": ""}],
        "red_reason": "the assertion fails",
        "evidence": [{"cite": f"BACK/{prod}:1-1", "from": 1, "to": 1, "note": ""}]})


class Fixture:
    """main with the suite; fix/c-01-calc (C-01, single PR); fix/c-02-audit and fix/c-03-audit2 merged into
    audit/pr-2 (C-02 and C-03, one group PR); everything pushed to a bare origin."""

    def __init__(self, junit: bool = True) -> None:
        self.repo, _ = make_git_repo({
            "run_tests.sh": SUITE, ".gitignore": "build/\n", "src/calc.py": "ADD = 1\n", "src/audit.py": "audit\n",
            "src/other.py": "x\n", "tests/BaseTest.py": "base\n"}, remote="https://github.com/o/r")
        self.run = new_run(self.repo)
        self.bare = make_dir() / "origin.git"
        subprocess.run(["git", "clone", "-q", "--bare", str(self.repo), str(self.bare)], check=True)
        git(self.repo, "remote", "set-url", "origin", str(self.bare))
        self.shas = {}
        self.shas["C-01"] = self.branch("fix/c-01-calc", "tests/CalcTest.py", "test(calc): show add is wrong")
        self.shas["C-02"] = self.branch("fix/c-02-audit", "tests/AuditTest.py", "test(audit): show audit one")
        self.shas["C-03"] = self.branch("fix/c-03-audit2", "tests/Audit2Test.py", "test(audit): show audit two")
        git(self.repo, "switch", "-q", "-c", "audit/pr-2", "fix/c-02-audit")
        git(self.repo, "-c", "commit.gpgsign=false", "merge", "-q", "--no-ff", "--no-edit", "fix/c-03-audit2")
        git(self.repo, "switch", "-q", "main")
        git(self.repo, "push", "-q", "-u", "origin", "main", "fix/c-01-calc", "fix/c-02-audit", "fix/c-03-audit2",
            "audit/pr-2")
        red_finding(self.run, "C-01", "fix/c-01-calc", self.shas["C-01"], "tests/CalcTest.py", "src/calc.py")
        red_finding(self.run, "C-02", "fix/c-02-audit", self.shas["C-02"], "tests/AuditTest.py", "src/audit.py")
        red_finding(self.run, "C-03", "fix/c-03-audit2", self.shas["C-03"], "tests/Audit2Test.py", "src/audit.py")
        plan = {"stack": "python", "test_cmd": ["sh", "run_tests.sh"], "env": {}, "pre": [], "deps": "none"}
        if junit:
            plan["junit"] = ["build/TEST-*.xml"]
        with runmod.transaction(self.run) as manifest:
            manifest["baseline"]["BACK"] = {"plan": plan, "result": {"passed": 2, "failed": 0, "total": 2}}
        runmod.set_keys(self.run, ["fix.authorized_by=the owner team (test)"])
        self.stubs = make_dir()
        (self.stubs / "gh").write_text(GH, encoding="utf-8")
        os.chmod(self.stubs / "gh", 0o755)
        self.log = self.stubs / "gh.log"
        self.body = self.stubs / "body.md"
        self.env = {"PATH": f"{self.stubs}:{os.environ['PATH']}", "FAKE_GH_LOG": str(self.log),
                    "FAKE_GH_PRS": json.dumps([{"number": 7, "baseRefName": "main", "state": "OPEN"}]),
                    "FAKE_GH_BODY": str(self.body)}

    def branch(self, name: str, test: str, message: str) -> str:
        git(self.repo, "switch", "-q", "-c", name, "main")
        write(self.repo, test, "red\n")
        sha = commit(self.repo, message, test)
        git(self.repo, "switch", "-q", "main")
        return sha

    def gh(self):
        return mock.patch.dict(os.environ, self.env)

    def start(self, target: str = "C-01", base_ref=None):
        with self.gh():
            return fixmod.start(self.run, target, base_ref)

    def wt(self, branch: str = "fix/c-01-calc") -> Path:
        return self.run / "fix" / f"wt-{fixmod._slug(branch)}"

    def fix(self, fid: str = "C-01", rel: str = "src/calc.py", text: str = "ADD = 1  # fixed\n",
            message: str = "fix(calc): add returns the sum", branch: str = "fix/c-01-calc", green: bool = True) -> str:
        wt = self.wt(branch)
        write(wt, rel, text)
        if green:
            (self.run / "outputs" / f"{fid}-green.txt").write_text("1 passed\n", encoding="utf-8")
        return commit(wt, message, rel)

    def check(self, fid: str = "C-01"):
        return fixmod.check(self.run, fid)

    def review(self, fid: str, sha: str, state: str = "CONFIDENT") -> None:
        claims = {c: {"state": state, "evidence": "one hunk in src/calc.py"} for c in findingsmod.FIX_CLAIMS}
        findingsmod.update(self.run, fid, {"fix.review": {"model": "other-model", "sha": sha, "claims": claims}})

    def finding(self, fid: str) -> dict:
        return json.loads((self.run / "findings" / f"{fid}.json").read_text(encoding="utf-8"))


class PlanTest(unittest.TestCase):
    def test_plan_selects_confirmed_red_branches_and_groups_by_pr_branch(self):
        fx = Fixture()
        findingsmod.add(fx.run, {
            "report": "correctness", "category": "x", "dimension": "bug", "title": "No branch", "verdict": "confirmed",
            "severity": "high", "confidence": "docs", "source": "t", "what_happens": "w",
            "evidence": [{"cite": "BACK/src/other.py:1-1", "from": 1, "to": 1, "note": ""}]})
        with fx.gh():
            lines = fixmod.plan(fx.run)
        text = "\n".join(lines)
        self.assertIn("BACK fix/c-01-calc  PR #7 (open) base main", text)
        self.assertIn("BACK audit/pr-2  PR #7 (open) base main (group", text)
        self.assertIn("C-02 high: Repair src/audit.py.", text)
        self.assertIn("prod_files: src/audit.py", text)
        self.assertNotIn("C-04", text)
        self.assertNotIn("fix/c-02-audit ", text)
        self.assertIn("pr list --repo o/r --head fix/c-01-calc --state all", fx.log.read_text(encoding="utf-8"))
        with fx.gh():
            only = "\n".join(fixmod.plan(fx.run, ids=["C-03"]))
        self.assertIn("C-02 high  (in the same PR, not selected): Repair src/audit.py.", only)
        self.assertNotIn("fix/c-01-calc", only)

    def test_plan_without_gh_says_to_pass_base_ref(self):
        fx = Fixture()
        broken = make_dir()
        (broken / "gh").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        os.chmod(broken / "gh", 0o755)
        with mock.patch.dict(os.environ, {"PATH": f"{broken}:{os.environ['PATH']}"}):
            self.assertIn("PR ? (gh found none; pass --base-ref to start)", "\n".join(fixmod.plan(fx.run)))


class StartTest(unittest.TestCase):
    def test_start_refuses_without_authorization(self):
        fx = Fixture()
        with runmod.transaction(fx.run) as manifest:
            manifest.pop("fix")
        with self.assertRaises(runmod.RunError) as ctx:
            fx.start()
        self.assertIn("fix.authorized_by", str(ctx.exception))

    def test_start_refuses_dirty_repo(self):
        fx = Fixture()
        write(fx.repo, "src/calc.py", "dirty\n")
        with self.assertRaises(runmod.RunError) as ctx:
            fx.start()
        self.assertIn("uncommitted changes", str(ctx.exception))
        self.assertFalse(fx.wt().exists())

    def test_start_refuses_branch_diverged_from_upstream(self):
        fx = Fixture()
        git(fx.repo, "switch", "-q", "fix/c-01-calc")
        write(fx.repo, "tests/Extra.py", "x\n")
        commit(fx.repo, "test: local only", "tests/Extra.py")
        git(fx.repo, "switch", "-q", "main")
        with self.assertRaises(runmod.RunError) as ctx:
            fx.start()
        self.assertIn("differs from its upstream", str(ctx.exception))

    def test_start_refuses_branch_without_upstream_unless_base_ref(self):
        fx = Fixture()
        git(fx.repo, "branch", "--unset-upstream", "fix/c-01-calc")
        with self.assertRaises(runmod.RunError) as ctx:
            fx.start()
        self.assertIn("has no upstream", str(ctx.exception))
        lines = fx.start(base_ref="main")
        self.assertIn("proving on a throwaway merge of main into fix/c-01-calc", "\n".join(lines))

    def test_start_records_passing_names_red_tests_and_context(self):
        fx = Fixture()
        lines = "\n".join(fx.start())
        self.assertIn("suite at start: 2 of 3 pass (compared later by names)", lines)
        self.assertIn("C-01: started (red now: 1 test)", lines)
        state = fixmod.load_state(fx.run, "fix/c-01-calc")
        self.assertEqual(state["base"], "origin/main")
        self.assertEqual(state["pr"], 7)
        self.assertEqual(state["start"]["passed"], ["tests.BaseTest.test_one", "tests.BaseTest.test_two"])
        self.assertEqual(state["red"]["C-01"], ["tests.CalcTest.test_add"])
        self.assertEqual(git(fx.wt(), "rev-parse", "--abbrev-ref", "HEAD"), "fix/c-01-calc")
        context = (fx.run / "fix" / "fix-c-01-calc" / "C-01.md").read_text(encoding="utf-8")
        self.assertIn("Repair src/calc.py.", context)
        self.assertIn("frozen", context)
        self.assertEqual(fx.finding("C-01")["fix"]["status"], "started")
        self.assertTrue((fx.run / "outputs" / "C-01-fix-red.txt").is_file())

    def test_start_marks_moot_when_the_pr_base_already_fixed_it(self):
        fx = Fixture()
        write(fx.repo, "src/calc.py", "ADD = 1  # fixed upstream\n")
        commit(fx.repo, "fix(calc): upstream fix", "src/calc.py")
        git(fx.repo, "push", "-q", "origin", "main")
        lines = "\n".join(fx.start())
        self.assertIn("C-01: moot", lines)
        f = fx.finding("C-01")
        self.assertEqual(f["fix"]["status"], "moot")
        self.assertIn("fixed upstream", f["fix"]["reason"])

    def test_start_reports_a_conflict_with_the_moved_base(self):
        fx = Fixture()
        write(fx.repo, "tests/CalcTest.py", "other\n")
        commit(fx.repo, "test: same file upstream", "tests/CalcTest.py")
        git(fx.repo, "push", "-q", "origin", "main")
        lines = "\n".join(fx.start())
        self.assertIn("conflict: fix/c-01-calc does not merge cleanly with origin/main (tests/CalcTest.py)", lines)
        self.assertTrue(fixmod.load_state(fx.run, "fix/c-01-calc")["start"]["conflict"])

    def test_start_on_a_group_member_uses_the_group_branch(self):
        fx = Fixture()
        lines = "\n".join(fx.start("C-03"))
        self.assertIn("worktree", lines)
        state = fixmod.load_state(fx.run, "audit/pr-2")
        self.assertEqual(state["members"], ["C-02", "C-03"])
        self.assertEqual(fx.finding("C-02")["fix"]["unit"], "audit/pr-2")
        self.assertEqual(git(fx.wt("audit/pr-2"), "rev-parse", "--abbrev-ref", "HEAD"), "audit/pr-2")


class CheckTest(unittest.TestCase):
    def test_check_passes_on_a_clean_fix(self):
        fx = Fixture()
        fx.start()
        sha = fx.fix()
        passed, lines = fx.check()
        self.assertTrue(passed, lines)
        self.assertIn("suite on the merge of origin/main", "\n".join(lines))
        record = fx.finding("C-01")["fix"]["check"]
        self.assertEqual((record["passed"], record["sha"], record["suite"], record["compared"]),
                         (True, sha, "3 of 3 pass", "names"))
        self.assertEqual(record["green"], {"tests/CalcTest.py": "1 of 1 pass"})

    def assertFails(self, fx, needle, fid="C-01"):
        passed, lines = fx.check(fid)
        self.assertFalse(passed)
        self.assertIn(needle, "\n".join(lines))
        self.assertFalse(fx.finding(fid)["fix"]["check"]["passed"])

    def test_check_fails_on_an_edited_red_test(self):
        fx = Fixture()
        fx.start()
        write(fx.wt(), "tests/CalcTest.py", "weakened\n")
        fx.fix(message="fix(calc): add returns the sum", rel="src/calc.py")
        git(fx.wt(), "add", "tests/CalcTest.py")
        git(fx.wt(), "-c", "commit.gpgsign=false", "commit", "-q", "--amend", "--no-edit")
        self.assertFails(fx, "red test changed: tests/CalcTest.py")

    def test_check_fails_on_an_out_of_scope_file(self):
        fx = Fixture()
        fx.start()
        write(fx.wt(), "src/other.py", "y\n")
        fx.fix()
        git(fx.wt(), "add", "src/other.py")
        git(fx.wt(), "-c", "commit.gpgsign=false", "commit", "-q", "--amend", "--no-edit")
        self.assertFails(fx, "out of scope: src/other.py")

    def test_check_allows_an_extra_file_named_with_its_reason_and_a_new_test(self):
        fx = Fixture()
        fx.start()
        findingsmod.update(fx.run, "C-01", {"fix.extra_files": ["src/other.py"]})
        write(fx.wt(), "src/other.py", "y\n")
        write(fx.wt(), "tests/CalcEdgeTest.py", "edge\n")
        fx.fix()
        git(fx.wt(), "add", "src/other.py", "tests/CalcEdgeTest.py")
        git(fx.wt(), "-c", "commit.gpgsign=false", "commit", "-q", "--amend", "--no-edit")
        passed, lines = fx.check()
        self.assertTrue(passed, lines)

    def test_check_fails_on_a_new_suite_failure(self):
        fx = Fixture()
        fx.start()
        fx.fix(text="ADD = 1  # fixed break\n")
        self.assertFails(fx, "new failure: tests.BaseTest.test_two")

    def test_check_fails_when_the_red_test_stays_red(self):
        fx = Fixture()
        fx.start()
        fx.fix(text="ADD = 2\n")
        self.assertFails(fx, "red test still not passing: tests.CalcTest.test_add")

    def test_check_fails_on_attribution(self):
        fx = Fixture()
        fx.start()
        fx.fix(message="fix(calc): add returns the sum\n\n" + TRAILER)
        self.assertFails(fx, hygienemod.R_ATTRIBUTION)

    def test_check_fails_on_a_long_subject(self):
        fx = Fixture()
        fx.start()
        fx.fix(message="fix(calc): " + "x" * 95)
        self.assertFails(fx, "subject is 106 characters (max 100)")

    def test_check_fails_on_a_closing_keyword_in_the_commit(self):
        fx = Fixture()
        fx.start()
        fx.fix(message="fix(calc): add returns the sum\n\nCloses #238.")
        self.assertFails(fx, "closing keyword 'Closes #238'")

    def test_check_fails_without_a_fix_commit_or_green_output(self):
        fx = Fixture()
        fx.start()
        self.assertFails(fx, "no fix commit on top of")
        fx.fix(green=False)
        self.assertFails(fx, "outputs/C-01-green.txt not found")

    def test_check_by_counts_without_junit_says_so(self):
        fx = Fixture(junit=False)
        lines = "\n".join(fx.start())
        self.assertIn("compared later by counts: the plan has no readable junit reports", lines)
        fx.fix()
        passed, lines = fx.check()
        self.assertTrue(passed, lines)
        self.assertIn("compared by counts: no junit names", "\n".join(lines))
        fx2 = Fixture(junit=False)
        fx2.start()
        fx2.fix(text="ADD = 1  # fixed break\n")
        passed, lines = fx2.check()
        self.assertFalse(passed)
        self.assertIn("by counts: 1 failing now, expected at most 0", "\n".join(lines))

    def test_check_fails_on_a_local_path_in_the_commit_message(self):
        fx = Fixture()
        fx.start()
        fx.fix(message="fix(calc): add returns the sum\n\nRan: sh /private/tmp/x/run/docker/run.sh BACK test")
        self.assertFails(fx, "local path in the message (/private/tmp/x/run/docker/run.sh)")

    def test_check_accepts_commands_quoted_from_the_repo_root(self):
        fx = Fixture()
        fx.start()
        fx.fix(message="fix(calc): add returns the sum\n\nRan: ./gradlew test --tests 'CalcTest' -> 1 of 1 pass")
        passed, lines = fx.check()
        self.assertTrue(passed, lines)

    def test_local_path_pattern(self):
        for text in ("/Users/me/x", "at /home/u/run.sh", "(/var/folders/7j/T/x)", "C:\\Users\\me", "/tmp/a"):
            self.assertTrue(hygienemod.local_path_hit(text), text)
        for text in ("./gradlew test", "src/main/kotlin/A.kt", "https://example.com/tmp/x", "~/notes"):
            self.assertEqual(hygienemod.local_path_hit(text), "", text)
        self.assertEqual(hygienemod.local_path_hit("ran in /opt/run/x", ("/opt/run",)), "/opt/run")

    def test_closing_keyword_pattern(self):
        for text in ("Closes #12", "fixes #3", "Resolved: #4", "closes o/r#5"):
            self.assertRegex(text, fixmod.CLOSING)
        for text in ("fix(security): reject revoked tokens", "Refs #238.", "the fix for #12 lands in the PR"):
            self.assertNotRegex(text, fixmod.CLOSING)


class DoneTest(unittest.TestCase):
    def test_done_needs_a_confident_review_of_head_then_records_the_fix(self):
        fx = Fixture()
        fx.start()
        sha = fx.fix()
        self.assertTrue(fx.check()[0])
        with self.assertRaises(runmod.RunError) as ctx:
            fixmod.done(fx.run, "C-01")
        self.assertIn("no review of HEAD", str(ctx.exception))
        fx.review("C-01", sha, state="UNSURE")
        with self.assertRaises(runmod.RunError) as ctx:
            fixmod.done(fx.run, "C-01")
        self.assertIn("not CONFIDENT: targeted, no_new_risk, minimal", str(ctx.exception))
        fx.review("C-01", "0" * 40)
        with self.assertRaises(runmod.RunError):
            fixmod.done(fx.run, "C-01")
        fx.review("C-01", sha)
        lines = "\n".join(fixmod.done(fx.run, "C-01"))
        self.assertIn("C-01: done", lines)
        self.assertIn("worktree removed", lines)
        f = fx.finding("C-01")
        self.assertEqual((f["fix"]["status"], f["sha_fix"]), ("done", sha))
        self.assertEqual(f["tests"][0]["green"], "1 of 1 pass")
        self.assertEqual(f["outputs"]["green"], "outputs/C-01-green.txt")
        self.assertEqual(f["outputs"]["suite"], "outputs/C-01-fix-suite.txt")
        self.assertFalse(fx.wt().exists())

    def test_done_warns_when_the_reviewer_is_the_contrast_model(self):
        fx = Fixture()
        findingsmod.update(fx.run, "C-01", {"contrast.model": "gpt-6-luna", "contrast.verdict": "agree"})
        fx.start()
        sha = fx.fix()
        self.assertTrue(fx.check()[0])
        fx.review("C-01", sha)
        findingsmod.update(fx.run, "C-01", {"fix.review.model": "gpt-6-luna (codex exec read-only)"})
        lines = "\n".join(fixmod.done(fx.run, "C-01"))
        self.assertIn("C-01: done", lines)
        self.assertIn("warning: C-01: the reviewer (gpt-6-luna (codex exec read-only)) is the model that already "
                      "judged this finding", lines)

    def test_review_claims_are_validated(self):
        fx = Fixture()
        with self.assertRaises(findingsmod.FindingError):
            findingsmod.update(fx.run, "C-01", {"fix.review.claims": {"targeted": {"state": "SURE", "evidence": "x"}}})
        with self.assertRaises(findingsmod.FindingError):
            findingsmod.update(fx.run, "C-01",
                               {"fix.review.claims": {"minimal": {"state": "CONFIDENT", "evidence": ""}}})
        with self.assertRaises(findingsmod.FindingError):
            findingsmod.update(fx.run, "C-01", {"fix.status": "declined"})

    def test_declined_resets_the_local_branch_and_frees_the_worktree(self):
        fx = Fixture()
        fx.start()
        fx.fix()
        findingsmod.update(fx.run, "C-01", {"fix.status": "declined", "fix.reason": "the review found it targets "
                                                                                   "the symptom"})
        lines = "\n".join(fixmod.done(fx.run, "C-01"))
        self.assertIn("reset from", lines)
        self.assertEqual(git(fx.repo, "rev-parse", "fix/c-01-calc"), fx.shas["C-01"])
        self.assertIn("worktree removed", lines)

    def test_group_members_are_fixed_in_order_in_one_worktree(self):
        fx = Fixture()
        fx.start("audit/pr-2")
        s2 = fx.fix("C-02", "src/audit.py", "audit fixed1\n", "fix(audit): audit one", branch="audit/pr-2")
        self.assertTrue(fx.check("C-02")[0])
        fx.review("C-02", s2)
        self.assertIn("worktree kept for C-03", "\n".join(fixmod.done(fx.run, "C-02")))
        s3 = fx.fix("C-03", "src/audit.py", "audit fixed1 fixed2\n", "fix(audit): audit two", branch="audit/pr-2")
        passed, lines = fx.check("C-03")
        self.assertTrue(passed, lines)
        self.assertEqual(fx.finding("C-03")["fix"]["check"]["suite"], "4 of 4 pass")
        fx.review("C-03", s3)
        self.assertIn("worktree removed", "\n".join(fixmod.done(fx.run, "C-03")))
        self.assertEqual(git(fx.repo, "rev-list", "--count", "origin/audit/pr-2..audit/pr-2"), "2")


def single_done(fx: Fixture) -> str:
    fx.start()
    sha = fx.fix()
    assert fx.check()[0]
    fx.review("C-01", sha)
    fixmod.done(fx.run, "C-01")
    return sha


DRAFT_BODY = (publishmod.DRAFT_NOTE + "\n\nRefs #244.\nRefs #245.\n\nFindings: C-02, C-03.\n\nShared files with "
              "sibling PRs:\n\nnone\n\nProposed fix (the branch holds only the failing test):\n\n"
              "- C-02: a\n- C-03: b\n")


class PublishTest(unittest.TestCase):
    def test_publish_single_pr(self):
        fx = Fixture()
        single_done(fx)
        out, lines = fixmod.publish(fx.run)
        cmds = out.read_text(encoding="utf-8")
        self.assertTrue(cmds.startswith("#!/bin/sh\nset -eu\n"))
        self.assertNotIn("--force", cmds)
        self.assertNotIn("-f ", " ".join(ln for ln in cmds.splitlines() if " push " in ln))
        self.assertIn(f"git -C {shlex.quote(str(fx.repo.resolve()))} push origin fix/c-01-calc", cmds)
        self.assertIn("PR=$(gh pr list --repo o/r --head fix/c-01-calc --state open --json number --jq "
                      "'.[0].number')", cmds)
        self.assertIn("gh pr edit \"$PR\" --repo o/r --title 'fix(calc): add returns the sum'", cmds)
        self.assertIn("gh pr ready \"$PR\" --repo o/r", cmds)
        self.assertIn("full suite: 3 of 3 pass", cmds)
        for line in cmds.splitlines():
            if "--title" in line:
                self.assertLessEqual(len(shlex.split(line.split("--title", 1)[1])[0]), 100)
        self.assertEqual(subprocess.run(["sh", "-n", str(out)]).returncode, 0)
        self.assertEqual(lines, ["fix/c-01-calc: ready (C-01)"])

    def test_publish_names_the_real_pr_base_when_a_local_ref_was_tested(self):
        fx = Fixture()
        fx.start(base_ref="origin/main")
        sha = fx.fix()
        self.assertTrue(fx.check()[0])
        fx.review("C-01", sha)
        fixmod.done(fx.run, "C-01")
        cmds = fixmod.publish(fx.run)[0].read_text(encoding="utf-8")
        self.assertIn("; PR base main (tested against local ref origin/main)", cmds)
        self.assertNotIn("PR base origin/main", cmds)

    def test_hygiene_flags_a_local_path_in_a_fix_body(self):
        fx = Fixture()
        (fx.run / "fix").mkdir()
        (fx.run / "fix" / "fix-c-01-calc.body.md").write_text("Ran /Users/me/run.sh\n", encoding="utf-8")
        self.assertIn("fix/fix-c-01-calc.body.md: local path: /Users/me/run.sh", hygienemod.check_fix(fx.run))

    def test_publish_commands_run_as_prepared_with_a_fake_gh(self):
        fx = Fixture()
        sha = single_done(fx)
        fx.body.write_text(publishmod.DRAFT_NOTE + "\n\nRefs #238.\n\nFindings: C-01.\n", encoding="utf-8")
        out, _ = fixmod.publish(fx.run)
        res = subprocess.run(["sh", str(out)], capture_output=True, text=True, env={**os.environ, **fx.env})
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(git(fx.bare, "rev-parse", "fix/c-01-calc"), sha)
        body = (fx.run / "fix" / "fix-c-01-calc.body.md").read_text(encoding="utf-8")
        self.assertTrue(body.startswith("Now includes the fix: the test fails at the base and passes with it; full "
                                        "suite: 3 of 3 pass.\n"))
        self.assertIn("Closes #238.", body)
        self.assertIn("Findings: C-01.", body)
        log = fx.log.read_text(encoding="utf-8")
        self.assertIn("pr ready 7 --repo o/r", log)
        self.assertIn("pr edit 7 --repo o/r --body-file", log)

    def test_publish_group_waits_for_every_member_or_partial(self):
        fx = Fixture()
        fx.start("audit/pr-2")
        s2 = fx.fix("C-02", "src/audit.py", "audit fixed1\n", "fix(audit): audit one", branch="audit/pr-2")
        fx.check("C-02")
        fx.review("C-02", s2)
        fixmod.done(fx.run, "C-02")
        out, lines = fixmod.publish(fx.run)
        cmds = out.read_text(encoding="utf-8")
        self.assertIn("# audit/pr-2: skipped: C-03 not done", cmds)
        self.assertNotIn("push origin", cmds)
        out, lines = fixmod.publish(fx.run, partial=True)
        cmds = out.read_text(encoding="utf-8")
        self.assertIn("push origin audit/pr-2", cmds)
        self.assertNotIn("gh pr ready", cmds)
        self.assertNotIn("--title", cmds)
        self.assertIn("-v fixed=C-02 -v all=0", cmds)
        self.assertIn("C-03 still has only the failing test, so this PR stays a draft", cmds)
        self.assertEqual(lines, ["audit/pr-2: partial (C-02)"])
        s3 = fx.fix("C-03", "src/audit.py", "audit fixed1 fixed2\n", "fix(audit): audit two", branch="audit/pr-2")
        fx.check("C-03")
        fx.review("C-03", s3)
        fixmod.done(fx.run, "C-03")
        out, _ = fixmod.publish(fx.run)
        cmds = out.read_text(encoding="utf-8")
        self.assertIn("--title 'fix(audit): audit one (+1 more)'", cmds)
        self.assertIn("gh pr ready", cmds)
        self.assertIn("-v all=1", cmds)
        self.assertEqual(subprocess.run(["sh", "-n", str(out)]).returncode, 0)

    def test_body_rewrite_keeps_the_audit_structure(self):
        awk = str(fixmod.BODY_AWK)

        def rewrite(body: str, fixed: str, all_: int) -> str:
            return subprocess.run(["awk", "-f", awk, "-v", f"draft={publishmod.DRAFT_NOTE}", "-v", "note=NOTE",
                                   "-v", f"fixed={fixed}", "-v", f"all={all_}"], input=body, capture_output=True,
                                  text=True, check=True).stdout
        partial = rewrite(DRAFT_BODY, "C-02", 0)
        self.assertTrue(partial.startswith("NOTE\n\nCloses #244.\nRefs #245.\n"))
        self.assertIn("Proposed fix (the branch holds only the failing test):", partial)
        self.assertIn("Shared files with sibling PRs:", partial)
        self.assertEqual(partial.count("\n"), DRAFT_BODY.count("\n"))
        full = rewrite(DRAFT_BODY.replace("\n", "\r\n"), "C-02 C-03", 1)
        self.assertIn("Closes #244.\nCloses #245.\n", full)
        edited = rewrite("Someone rewrote this.\n\nRefs #244.\nRefs #245.\n\nFindings: C-02.\n", "C-02", 0)
        self.assertTrue(edited.startswith("NOTE\n\nSomeone rewrote this.\n"))
        self.assertIn("Refs #244.\nRefs #245.", edited)

    def test_hygiene_covers_fix_but_not_the_worktrees(self):
        fx = Fixture()
        fx.start()
        (fx.wt() / "notes.md").write_text(TRAILER + "\n", encoding="utf-8")
        self.assertEqual(hygienemod.check_fix(fx.run), [])
        (fx.run / "fix" / "fix-c-01-calc" / "C-01.md").write_text("x\n\n" + TRAILER + "\n", encoding="utf-8")
        problems = hygienemod.check_fix(fx.run)
        self.assertEqual(len(problems), 1)
        self.assertIn("fix/fix-c-01-calc/C-01.md: LLM attribution", problems[0])
        self.assertIn("fix/fix-c-01-calc/C-01.md", "\n".join(hygienemod.check_run(fx.run)[0]))


class CliTest(unittest.TestCase):
    def test_cli_exit_codes(self):
        fx = Fixture()
        env = {**os.environ, **fx.env}
        ia = [sys.executable, str(SKILL / "ia.py"), "fix"]
        plan = subprocess.run([*ia, "plan", "--run", str(fx.run)], capture_output=True, text=True, env=env)
        self.assertEqual(plan.returncode, 0, plan.stderr)
        start = subprocess.run([*ia, "start", "--run", str(fx.run), "C-01"], capture_output=True, text=True, env=env)
        self.assertEqual(start.returncode, 0, start.stderr)
        chk = subprocess.run([*ia, "check", "--run", str(fx.run), "C-01"], capture_output=True, text=True, env=env)
        self.assertEqual(chk.returncode, 1)
        self.assertIn("FAIL no fix commit", chk.stdout)
        bad = subprocess.run([*ia, "start", "--run", str(fx.run), "C-99"], capture_output=True, text=True, env=env)
        self.assertEqual(bad.returncode, 2)
        pub = subprocess.run([*ia, "publish", "--run", str(fx.run)], capture_output=True, text=True, env=env)
        self.assertEqual(pub.returncode, 0, pub.stderr)
        self.assertIn("nothing was executed", pub.stdout)


if __name__ == "__main__":
    unittest.main()
