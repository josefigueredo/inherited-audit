from __future__ import annotations

import os
import shlex
import subprocess
import sys
import unittest
from pathlib import Path

from helpers import SKILL, git, make_dir, make_git_repo, run_cli, write_tree

from ia import findings as findingsmod
from ia import publish
from ia import run as runmod
from ia.run import UsageError
from test_branches import new_run

REMINDER = ("Reminder: publishing on another team's repository is what the filter tries to avoid; "
            "review publish/ before running anything.")


def make_run(publish_opt=True, remote="https://github.com/o/r", filtered=True):
    repo, _ = make_git_repo({"a.py": "x\n"}, remote=remote)
    run = new_run(repo)
    manifest = runmod.load(run)
    manifest["options"]["publish"] = publish_opt
    if filtered:
        manifest["filter"] = {"counts": {}, "start_here": []}
    runmod.save(run, manifest)
    return run


def add_c(run, files, title="Bug it's", branch=None, **extra):
    fid = findingsmod.add(run, {
        "report": "correctness", "category": "x", "dimension": "bug", "title": title, "verdict": "confirmed",
        "severity": "low", "confidence": "docs", "source": "t", "what_happens": "It breaks.",
        "branch": branch if branch is not None else "fix/" + files[0].replace(".py", ""),
        "prod_files": list(files), "evidence": [{"cite": f"BACK/{files[0]}:1-2", "from": 1, "to": 2, "note": ""}],
        **extra})
    findingsmod.update(run, fid, {"shown": True})
    return fid


def add_q(run, title="Quality one"):
    fid = findingsmod.add(run, {
        "report": "quality", "category": "x", "dimension": "code", "title": title, "verdict": "confirmed",
        "severity": "low", "confidence": "docs", "source": "t", "what_happens": "Meh.", "suggestion": "s",
        "effort": "S", "evidence": [{"cite": "BACK/a.py:3-4", "from": 3, "to": 4, "note": ""}]})
    findingsmod.update(run, fid, {"shown": True})
    return fid


class PublishTest(unittest.TestCase):
    def test_publish_refused_when_option_false(self):
        run = make_run(publish_opt=False)
        with self.assertRaises(UsageError) as ctx:
            publish.prepare_publish(run)
        self.assertIn("--publish", str(ctx.exception))
        result = run_cli(["publish", "--run", str(run)])
        self.assertEqual(result.returncode, 2)
        self.assertIn("--publish", result.stderr)
        self.assertFalse((run / "publish").exists())

    def test_publish_refused_before_filter_exit_1(self):
        run = make_run(filtered=False)
        with self.assertRaises(runmod.RunError) as ctx:
            publish.prepare_publish(run)
        self.assertNotIsInstance(ctx.exception, UsageError)
        result = run_cli(["publish", "--run", str(run)])
        self.assertEqual(result.returncode, 1)
        self.assertIn("ia.py filter", result.stderr)
        self.assertFalse((run / "publish").exists())

    def test_publish_writes_bodies_and_commands_without_running_gh(self):
        run = make_run()
        c1 = add_c(run, ["a.py"], title="Bug it's here")
        c2 = add_c(run, ["b.py"], title="Second")
        q1 = add_q(run)
        hidden = add_c(run, ["h.py"], title="Hidden")
        findingsmod.update(run, hidden, {"shown": False})
        env = {**os.environ, "PATH": "/nonexistent"}
        result = subprocess.run([sys.executable, str(SKILL / "ia.py"), "publish", "--run", str(run)],
                                capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(REMINDER, result.stdout)
        out = (run / "publish").resolve()
        issue = (out / f"issue-{c1}.md").read_text(encoding="utf-8")
        self.assertTrue(issue.startswith("# Bug it's here\n"))
        self.assertIn("It breaks.", issue)
        self.assertIn("- BACK/a.py:1-2", issue)
        self.assertFalse((out / f"issue-{hidden}.md").exists())
        self.assertTrue((out / f"issue-{q1}.md").is_file())
        cmds = (out / "commands.sh").read_text(encoding="utf-8")
        self.assertTrue(cmds.startswith("#!/bin/sh\nset -eu\n"))
        self.assertIn("# Prepared by inherited-audit. Review before running. Nothing here has been executed.", cmds)
        self.assertNotIn("\ncd ", cmds)
        self.assertIn("# Before running: push every PR head branch", cmds)
        self.assertLess(cmds.index("# Before running: push"), cmds.index("gh issue create"))
        self.assertEqual(cmds.count("gh issue create"), 3)
        title = shlex.quote("Bug it's here")
        self.assertIn(f"I_C_01=$(gh issue create --repo o/r --title {title} --label bug --body-file "
                      f"{shlex.quote(str(out / ('issue-' + c1 + '.md')))})", cmds)
        self.assertIn("I_C_01=${I_C_01##*/}", cmds)
        self.assertLess(cmds.index(f"# {c1}: Bug it's here"), cmds.index("I_C_01=$("))
        self.assertLess(cmds.rindex("gh issue create"), cmds.index("gh pr create"))
        self.assertEqual(cmds.count("gh pr create"), 2)
        self.assertIn("gh pr create --draft --repo o/r --head fix/a --base main --title ", cmds)
        self.assertIn(f"--body-file {shlex.quote(str(out / 'pr-1.body.md'))}", cmds)
        self.assertIn("Refs #${I_C_01}.", cmds)
        self.assertNotIn("Closes", cmds)
        self.assertNotIn("close it", cmds)
        self.assertIn("# git -C ", cmds)
        self.assertIn(" push -u origin fix/a", cmds)
        for line in cmds.splitlines():
            if line.startswith("gh "):
                self.assertIn("--repo o/r", line)
        self.assertTrue((out / "pr-1.md").is_file() and (out / "pr-2.md").is_file())
        self.assertIn(c2, (out / "pr-2.md").read_text(encoding="utf-8"))
        self.assertEqual(subprocess.run(["sh", "-n", str(out / "commands.sh")]).returncode, 0)

    def test_commands_run_as_prepared_with_stub_gh_and_git(self):
        run = make_run()
        c1 = add_c(run, ["shared.py"], title="One $(touch pwned) `x`")
        c2 = add_c(run, ["shared.py"], title="Two")
        stubs = make_dir()
        log = stubs / "log.txt"
        (stubs / "gh").write_text('#!/bin/sh\necho "gh $*" >> "%s"\n'
                                  'case "$1 $2" in "issue create") n=$(wc -l < "%s"); '
                                  'echo "https://github.com/o/r/issues/$((40 + n))";; esac\n' % (log, log))
        (stubs / "git").write_text('#!/bin/sh\necho "git $*" >> "%s"\n' % log)
        for name in ("gh", "git"):
            (stubs / name).chmod(0o755)
        publish.prepare_publish(run)
        out = (run / "publish").resolve()
        cwd = make_dir()
        res = subprocess.run(["sh", str(out / "commands.sh")], capture_output=True, text=True,
                             env={**os.environ, "PATH": f"{stubs}:/usr/bin:/bin"}, cwd=str(cwd))
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        calls = log.read_text(encoding="utf-8")
        self.assertIn("git -C ", calls)
        self.assertIn(" branch audit/pr-1 fix/shared", calls)
        self.assertIn("merge --no-ff --no-edit fix/shared", calls)
        self.assertNotIn(" push ", calls)
        self.assertIn("gh pr create --draft --repo o/r --head audit/pr-1 --base main", calls)
        pr_call = next(line for line in calls.splitlines() if line.startswith("gh pr create"))
        self.assertIn(" --draft", pr_call)
        body = (out / "pr-1.body.md").read_text(encoding="utf-8")
        self.assertEqual(body.splitlines()[0], publish.DRAFT_NOTE)
        self.assertRegex(body, r"\n\nRefs #4\d\.\nRefs #4\d\.\n")
        self.assertNotIn("Closes", body)
        self.assertIn(f"Findings: {c1}, {c2}.", body)
        self.assertFalse((cwd / "pwned").exists())
        self.assertFalse((out / "pwned").exists())

    def test_group_branch_is_merged_in_a_worktree_not_the_checkout(self):
        run = make_run()
        add_c(run, ["s.py"])
        add_c(run, ["s.py"])
        publish.prepare_publish(run)
        cmds = (run / "publish" / "commands.sh").read_text(encoding="utf-8")
        self.assertIn(" worktree add ", cmds)
        self.assertIn(" worktree remove ", cmds)
        merge = next(line for line in cmds.splitlines() if " merge --no-ff" in line)
        self.assertIn("wt-pr-1", merge)
        self.assertIn("# git -C ", cmds)
        self.assertIn("push -u origin audit/pr-1", cmds)

    def test_repo_without_remote_skips_issue_and_pr_with_a_comment(self):
        run = make_run(remote=None)
        add_c(run, ["a.py"])
        publish.prepare_publish(run)
        cmds = (run / "publish" / "commands.sh").read_text(encoding="utf-8")
        self.assertNotIn("gh issue create", cmds)
        self.assertNotIn("gh pr create", cmds)
        self.assertIn("skipped", cmds)
        self.assertNotIn("${I_", cmds)
        self.assertEqual(subprocess.run(["sh", "-n", str(run / "publish" / "commands.sh")]).returncode, 0)

    def test_gh_repo_from_remote(self):
        self.assertEqual(publish.gh_repo("https://github.com/o/r"), "o/r")
        self.assertEqual(publish.gh_repo("https://gitlab.example.com/o/r"), "gitlab.example.com/o/r")
        self.assertIsNone(publish.gh_repo(""))
        self.assertIsNone(publish.gh_repo("/srv/git/r"))

    def test_credentialed_remote_is_stripped_and_warned(self):
        self.assertEqual(publish.gh_repo("https://user:tok@github.com/o/r.git"), "o/r")
        self.assertEqual(publish.gh_repo("https://tok@gitlab.example.com/o/r"), "gitlab.example.com/o/r")
        run = make_run(remote="https://user:tok@github.com/o/r.git")
        add_c(run, ["a.py"])
        publish.prepare_publish(run)
        cmds = (run / "publish" / "commands.sh").read_text(encoding="utf-8")
        self.assertIn("--repo o/r", cmds)
        self.assertNotIn("tok", cmds)
        self.assertIn("# WARNING", cmds)
        self.assertEqual(subprocess.run(["sh", "-n", str(run / "publish" / "commands.sh")]).returncode, 0)

    def test_flag_in_manifest_triggers_warning_with_stripped_remote(self):
        run = make_run()
        manifest = runmod.load(run)
        manifest["repos"][0]["remote_had_credentials"] = True
        runmod.save(run, manifest)
        add_c(run, ["a.py"])
        publish.prepare_publish(run)
        self.assertIn("# WARNING", (run / "publish" / "commands.sh").read_text(encoding="utf-8"))

    def test_ssh_userinfo_with_password_counts_as_credentials(self):
        self.assertTrue(publish.has_userinfo("ssh://u:pw@h.example/o/r"))
        self.assertFalse(publish.has_userinfo("ssh://git@h.example/o/r"))
        self.assertFalse(publish.has_userinfo("git+ssh://git@h.example/o/r"))
        self.assertTrue(publish.has_userinfo("https://tok@h.example/o/r"))
        self.assertTrue(publish.has_userinfo("git+https://tok@h.example/o/r"))

    def test_prose_is_masked_in_issue_body_and_commands_for_any_dimension(self):
        run = make_run()
        key = "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7VJTUt9Us8cKj\n-----END PRIVATE KEY-----"
        add_c(run, ["a.py"], what_happens=f"Leaks {key} and AKIAABCDEFGHIJKLMNOP.",
              audience={"title": "Title AKIAABCDEFGHIJKLMNOP", "what_happens": "", "fix_summary": ""})
        publish.prepare_publish(run)
        text = "".join(p.read_text(encoding="utf-8") for p in (run / "publish").iterdir())
        self.assertNotIn("MIIEvQIBADANBg", text)
        self.assertNotIn("AKIAABCDEFGHIJKLMNOP", text)

    def test_draft_note_is_exact_and_every_pr_is_a_draft(self):
        self.assertEqual(publish.DRAFT_NOTE, "This branch only adds a failing test that reproduces the issue; it is "
                                             "meant to fail until a fix lands.")
        run = make_run()
        add_c(run, ["a.py"])
        add_c(run, ["b.py"])
        publish.prepare_publish(run)
        cmds = (run / "publish" / "commands.sh").read_text(encoding="utf-8")
        prs = [line for line in cmds.splitlines() if line.startswith("gh pr create")]
        self.assertEqual(len(prs), 2)
        for line in prs:
            self.assertIn(" --draft", line)
        self.assertEqual(cmds.count(publish.DRAFT_NOTE), 2)

    def test_final_pr_body_opens_with_the_note_then_refs_then_the_static_body(self):
        stubs = make_dir()
        (stubs / "gh").write_text("#!/bin/sh\necho https://github.com/o/r/issues/7\n")
        (stubs / "git").write_text("#!/bin/sh\nexit 0\n")
        for name in ("gh", "git"):
            (stubs / name).chmod(0o755)
        run = make_run()
        fid = add_c(run, ["a.py"])
        publish.prepare_publish(run)
        out = (run / "publish").resolve()
        res = subprocess.run(["sh", str(out / "commands.sh")], capture_output=True, text=True,
                             env={**os.environ, "PATH": f"{stubs}:/usr/bin:/bin"}, cwd=str(make_dir()))
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        body = (out / "pr-1.body.md").read_text(encoding="utf-8")
        self.assertTrue(body.startswith(publish.DRAFT_NOTE + "\n\nRefs #7.\n\nFindings: " + fid), body)

    def test_credential_warning_once_per_repo_path(self):
        repo, _ = make_git_repo({"api/a.py": "x\n", "web/b.py": "y\n"}, remote="https://user:tok@github.com/o/r.git")
        out = make_dir() / "run"
        res = run_cli(["init", "--system", "demo", "--out", str(out), "--publish",
                       "--repo", f"BACK={repo}:api", "--repo", f"FRONT={repo}:web"])
        self.assertEqual(res.returncode, 0, res.stderr)
        manifest = runmod.load(out)
        self.assertEqual(len(manifest["repos"]), 3)  # BACK, FRONT and ROOT share one repo
        manifest["filter"] = {"counts": {}, "start_here": []}
        runmod.save(out, manifest)
        publish.prepare_publish(out)
        cmds = (out / "publish" / "commands.sh").read_text(encoding="utf-8")
        self.assertEqual(cmds.count("# WARNING"), 1, cmds)
        self.assertIn("BACK, FRONT, ROOT", cmds)
        self.assertNotIn("tok", cmds)

    def test_clean_remote_has_no_warning(self):
        run = make_run()
        add_c(run, ["a.py"])
        publish.prepare_publish(run)
        self.assertNotIn("WARNING", (run / "publish" / "commands.sh").read_text(encoding="utf-8"))

    def test_same_path_in_two_repos_does_not_join_groups(self):
        repo, _ = make_git_repo({"a.py": "x\n"}, remote="https://github.com/o/r")
        run = new_run(repo, aliases=("BACK", "FRONT"))
        manifest = runmod.load(run)
        manifest["options"]["publish"] = True
        manifest["filter"] = {"counts": {}, "start_here": []}
        runmod.save(run, manifest)
        b = add_c(run, ["a.py"])
        f = findingsmod.add(run, {**findingsmod.load_all(run)[0], "id": None,
                                  "evidence": [{"cite": "FRONT/a.py:1-2", "from": 1, "to": 2, "note": ""}]})
        groups = publish.pr_groups(findingsmod.load_all(run))
        self.assertEqual([[x["id"] for x in g] for g in groups], [[b], [f]])

    def test_pr_groups_have_1_to_5_findings_and_list_shared_files(self):
        run = make_run()
        chain = [add_c(run, ["f1.py", "f2.py"]), add_c(run, ["f2.py", "f3.py"]), add_c(run, ["f3.py"]),
                 add_c(run, ["f4.py"]), add_c(run, ["f4.py"]), add_c(run, ["f4.py"]), add_c(run, ["f4.py"])]
        # chain[0..2] and chain[3..6] are two groups (3 and 4 findings)
        solo = add_c(run, ["z.py"])
        groups = publish.pr_groups(findingsmod.load_all(run))
        self.assertEqual([[f["id"] for f in g] for g in groups], [chain[:3], chain[3:], [solo]])
        for g in groups:
            self.assertTrue(1 <= len(g) <= 5)
        publish.prepare_publish(run)
        body = (run / "publish" / "pr-1.md").read_text(encoding="utf-8")
        self.assertTrue(body.startswith(f"Findings: {chain[0]}, {chain[1]}, {chain[2]}.\n"), body)  # static part
        cmds = (run / "publish" / "commands.sh").read_text(encoding="utf-8")
        closes = "".join(f"Refs #${{I_{c.replace('-', '_')}}}.\n" for c in chain[:3])
        self.assertIn(closes, cmds)
        self.assertIn("Shared files with sibling PRs", body)
        self.assertIn("none", body)
        self.assertEqual(len(list((run / "publish").glob("pr-*.md"))), 3)

    def test_pr_body_carries_the_proposal_and_uses_the_red_test_branch(self):
        run = make_run()
        c = add_c(run, ["a.py"], fix_summary="Clamp the coupon at 100%.")
        d = add_c(run, ["a.py"], title="Second", audience={"title": "", "what_happens": "",
                                                          "fix_summary": "Reject negative totals."})
        publish.prepare_publish(run)
        body = (run / "publish" / "pr-1.md").read_text(encoding="utf-8")
        self.assertIn(f"{c}: Clamp the coupon at 100%.", body)
        self.assertIn(f"{d}: Reject negative totals.", body)
        cmds = (run / "publish" / "commands.sh").read_text(encoding="utf-8")
        self.assertIn("audit/pr-1", cmds)

    def test_pr_body_proposal_is_masked(self):
        run = make_run()
        add_c(run, ["a.py"], fix_summary="Rotate AKIAABCDEFGHIJKLMNOP now.")
        publish.prepare_publish(run)
        body = (run / "publish" / "pr-1.md").read_text(encoding="utf-8")
        self.assertNotIn("AKIAABCDEFGHIJKLMNOP", body)

    def test_big_group_is_split_in_chunks_of_five_and_lists_shared_files(self):
        run = make_run()
        ids = [add_c(run, ["shared.py"]) for _ in range(7)]
        groups = publish.pr_groups(findingsmod.load_all(run))
        self.assertEqual([[f["id"] for f in g] for g in groups], [ids[:5], ids[5:]])
        publish.prepare_publish(run)
        for n in (1, 2):
            body = (run / "publish" / f"pr-{n}.md").read_text(encoding="utf-8")
            self.assertIn("- shared.py", body)
            self.assertNotIn("none", body.split("Shared files with sibling PRs")[1])

    def test_pr_excludes_unshown_unbranched_and_non_correctness(self):
        run = make_run()
        add_c(run, ["a.py"], branch="")
        add_q(run)
        c = add_c(run, ["b.py"])
        groups = publish.pr_groups(findingsmod.load_all(run))
        self.assertEqual([[f["id"] for f in g] for g in groups], [[c]])

    def test_audience_title_preferred(self):
        run = make_run()
        c = add_c(run, ["a.py"], title="Internal", audience={"title": "For the team", "what_happens": "",
                                                                "fix_summary": ""})
        publish.prepare_publish(run)
        self.assertTrue((run / "publish" / f"issue-{c}.md").read_text(encoding="utf-8").startswith("# For the team\n"))


def multi_run(**layout):
    """A filtered publish run with one repo per alias, each with its own github remote (`o/<alias lowercase>`)."""
    args = ["init", "--system", "s", "--out", str(make_dir() / "run")]
    for alias, files in layout.items():
        repo, _ = make_git_repo(files, remote=f"https://github.com/o/{alias.lower()}")
        args += ["--repo", f"{alias}={repo}"]
    assert run_cli(args).returncode == 0
    run = Path(args[4])
    manifest = runmod.load(run)
    manifest["options"]["publish"] = True
    manifest["filter"] = {"counts": {}, "start_here": []}
    runmod.save(run, manifest)
    return run


def cites(*aliases):
    return [{"cite": f"{a}/a.py:1-2", "from": 1, "to": 2, "note": ""} for a in aliases]


def add_cross(run, evidence, report="quality", branch="", **extra):
    base = {"category": "x", "title": "Cross", "verdict": "confirmed", "severity": "low", "confidence": "docs",
            "source": "t", "what_happens": "It breaks.", "evidence": evidence}
    if report == "quality":
        base.update(report="quality", dimension="code", suggestion="s", effort="S")
    else:
        base.update(report="correctness", dimension="bug", branch=branch, prod_files=["a.py"])
    base.update(extra)
    fid = findingsmod.add(run, base)
    findingsmod.update(run, fid, {"shown": True})
    return fid


def issue_repo(cmds, fid):
    line = next(x for x in cmds.splitlines() if x.startswith(f"I_{fid.replace('-', '_')}=$(gh issue create"))
    return shlex.split(line.split("$(", 1)[1])[4]


class PublishRepoTest(unittest.TestCase):
    """Which repo each issue and PR goes to when a finding cites more than one."""

    def publish(self, run):
        publish.prepare_publish(run)
        return (run / "publish" / "commands.sh").read_text(encoding="utf-8")

    def test_unbranched_finding_goes_to_the_most_cited_repo_with_a_review_comment(self):
        run = multi_run(API={"a.py": "x\n"}, BFF={"a.py": "x\n"}, MCP={"a.py": "x\n"})
        q = add_cross(run, cites("BFF", "BFF", "MCP", "MCP", "API", "API", "API"))
        cmds = self.publish(run)
        self.assertEqual(issue_repo(cmds, q), "o/api")
        self.assertIn(f"# {q}: cites API 3, BFF 2, MCP 2; goes to API by majority (set publish_repo if the fix "
                      "belongs to another repo)", cmds)

    def test_tie_goes_to_the_first_cited_of_the_tied_repos(self):
        run = multi_run(API={"a.py": "x\n"}, BFF={"a.py": "x\n"}, MFE={"a.py": "x\n"})
        q = add_cross(run, cites("MFE", "BFF", "API", "API", "BFF"))
        self.assertEqual(issue_repo(self.publish(run), q), "o/bff")

    def test_single_repo_finding_has_no_review_comment(self):
        run = multi_run(API={"a.py": "x\n"}, BFF={"a.py": "x\n"})
        q = add_cross(run, cites("BFF", "BFF"))
        cmds = self.publish(run)
        self.assertEqual(issue_repo(cmds, q), "o/bff")
        self.assertNotIn("by majority", cmds)

    def test_root_alias_does_not_count_unless_it_is_the_only_one(self):
        repo, _ = make_git_repo({"api/a.py": "x\n", "web/a.py": "x\n", "Dockerfile": "x\n"},
                                remote="https://github.com/o/mono")
        run = make_dir() / "run"
        self.assertEqual(run_cli(["init", "--system", "s", "--out", str(run), "--repo", f"API={repo}:api",
                                  "--repo", f"WEB={repo}:web"]).returncode, 0)
        manifest = runmod.load(run)
        self.assertTrue(any(r.get("root") for r in manifest["repos"]))
        manifest["options"]["publish"] = True
        manifest["filter"] = {"counts": {}, "start_here": []}
        runmod.save(run, manifest)
        q = add_cross(run, cites("ROOT", "ROOT", "ROOT", "WEB", "API", "WEB"))
        only_root = add_cross(run, cites("ROOT", "ROOT"))
        cmds = self.publish(run)
        self.assertIn(f"# {q}: cites WEB 2, API 1; goes to WEB by majority", cmds)
        self.assertEqual(issue_repo(cmds, only_root), "o/mono")
        self.assertNotIn(f"# {only_root}: cites", cmds)

    def test_publish_repo_wins_without_a_review_comment(self):
        run = multi_run(API={"a.py": "x\n"}, BFF={"a.py": "x\n"})
        q = add_cross(run, cites("BFF", "API", "API"), publish_repo="BFF")
        cmds = self.publish(run)
        self.assertEqual(issue_repo(cmds, q), "o/bff")
        self.assertNotIn(f"# {q}: cites", cmds)

    def test_publish_repo_must_be_a_repo_of_the_run(self):
        run = multi_run(API={"a.py": "x\n"}, BFF={"a.py": "x\n"})
        with self.assertRaises(findingsmod.FindingError) as ctx:
            add_cross(run, cites("API"), publish_repo="NOPE")
        self.assertIn("publish_repo", str(ctx.exception))
        q = add_cross(run, cites("API"))
        with self.assertRaises(findingsmod.FindingError) as ctx:
            findingsmod.update(run, q, {"publish_repo": "NOPE"})
        self.assertIn("API, BFF", str(ctx.exception))
        self.assertEqual(findingsmod.update(run, q, {"publish_repo": "BFF"})["publish_repo"], "BFF")
        result = run_cli(["finding", "set", "--run", str(run), q, "publish_repo=NOPE"])
        self.assertEqual(result.returncode, 1)
        self.assertIn("publish_repo", result.stderr)

    def test_branched_finding_goes_to_its_branch_repo_not_the_majority(self):
        run = multi_run(API={"a.py": "x\n"}, BFF={"a.py": "x\n"}, MFE={"a.py": "x\n"})
        c = add_cross(run, cites("MFE", "API", "API", "API", "MFE", "BFF"), report="correctness", branch="fix/c")
        cmds = self.publish(run)
        self.assertEqual(issue_repo(cmds, c), "o/mfe")
        self.assertIn("gh pr create --draft --repo o/mfe --head fix/c", cmds)
        self.assertNotIn("by majority", cmds)

    def test_publish_repo_on_a_branched_finding_is_ignored_with_a_comment(self):
        run = multi_run(API={"a.py": "x\n"}, MFE={"a.py": "x\n"})
        c = add_cross(run, cites("MFE", "API"), report="correctness", branch="fix/c", publish_repo="API")
        cmds = self.publish(run)
        self.assertEqual(issue_repo(cmds, c), "o/mfe")
        self.assertIn(f"# {c}: publish_repo API ignored: its branch fix/c is in MFE (the first cite), and the PR "
                      "can only reference an issue of its own repo", cmds)

    def test_group_of_branched_findings_shares_the_branch_repo(self):
        run = multi_run(API={"a.py": "x\n"}, MFE={"a.py": "x\n"})
        a = add_cross(run, cites("MFE", "API", "API"), report="correctness", branch="fix/a")
        b = add_cross(run, cites("MFE", "API", "API", "API"), report="correctness", branch="fix/b")
        groups = publish.pr_groups(findingsmod.load_all(run))
        self.assertEqual([[f["id"] for f in g] for g in groups], [[a, b]])
        cmds = self.publish(run)
        self.assertEqual({issue_repo(cmds, a), issue_repo(cmds, b)}, {"o/mfe"})
        self.assertIn("gh pr create --draft --repo o/mfe --head audit/pr-1", cmds)

    def test_each_created_issue_prints_its_number(self):
        run = multi_run(API={"a.py": "x\n"}, BFF={"a.py": "x\n"})
        q = add_cross(run, cites("API"))
        c = add_cross(run, cites("BFF"), report="correctness", branch="fix/c")
        cmds = self.publish(run)
        self.assertIn(f'echo "{q} -> issue #${{I_{q.replace("-", "_")}}}"', cmds)
        stubs = make_dir()
        (stubs / "gh").write_text('#!/bin/sh\ncase "$1 $2" in "issue create") '
                                  'echo "https://github.com/o/r/issues/7";; esac\n')
        (stubs / "git").write_text("#!/bin/sh\n")
        for name in ("gh", "git"):
            (stubs / name).chmod(0o755)
        res = subprocess.run(["sh", str(run / "publish" / "commands.sh")], capture_output=True, text=True,
                             env={**os.environ, "PATH": f"{stubs}:/usr/bin:/bin"}, cwd=str(make_dir()))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn(f"{q} -> issue #7\n", res.stdout)
        self.assertIn(f"{c} -> issue #7\n", res.stdout)


def red_commit(repo, branch, subject):
    """A branch with one commit whose subject is `subject`; returns its sha."""
    git(repo, "checkout", "-q", "-b", branch, "main")
    write_tree(repo, {f"t_{branch.replace('/', '_')}.py": "x\n"})
    git(repo, "add", "-A")
    git(repo, "-c", "commit.gpgsign=false", "commit", "-q", "-m", subject)
    sha = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "main")
    return sha


def flag_value(line, flag):
    tokens = shlex.split(line.split("$(", 1)[-1].rstrip(")"))
    return tokens[tokens.index(flag) + 1] if flag in tokens else None


def issue_line(cmds, fid):
    return next(x for x in cmds.splitlines() if x.startswith(f"I_{fid.replace('-', '_')}=$(gh issue create"))


def pr_line(cmds, n=1):
    return [x for x in cmds.splitlines() if x.startswith("gh pr create")][n - 1]


class PublishLabelsTest(unittest.TestCase):
    def publish(self, run):
        publish.prepare_publish(run)
        return (run / "publish" / "commands.sh").read_text(encoding="utf-8")

    def test_issue_labels_come_from_report_and_dimension(self):
        run = multi_run(API={"a.py": "x\n"})
        cases = {
            add_cross(run, cites("API"), report="correctness", branch="fix/a"): "bug",
            add_cross(run, cites("API"), report="correctness", branch="fix/b",
                      dimension="distributed"): "bug,resilience",
            add_cross(run, cites("API"), report="correctness", branch="fix/c",
                      dimension="supply-chain"): "security,supply-chain",
            add_cross(run, cites("API"), report="correctness", branch="fix/d", dimension="container"): "security",
            add_cross(run, cites("API")): "clean-code",
            add_cross(run, cites("API"), dimension="docs"): "documentation",
            add_cross(run, cites("API"), dimension="tests"): "testing",
            add_cross(run, cites("API"), dimension="architecture"): "architecture",
        }
        cmds = self.publish(run)
        for fid, expected in cases.items():
            self.assertEqual(flag_value(issue_line(cmds, fid), "--label"), expected, fid)

    def test_ci_label_from_title_or_workflow_cite(self):
        run = multi_run(API={"a.py": "x\n"})
        by_title = add_cross(run, cites("API"), title="CI runs without a lockfile")
        by_cite = add_cross(run, [{"cite": "API/.github/workflows/ci.yml:1-2", "from": 1, "to": 2, "note": ""}],
                            dimension="resilience")
        not_ci = add_cross(run, cites("API"), title="CIDR ranges are parsed twice")
        cmds = self.publish(run)
        self.assertEqual(flag_value(issue_line(cmds, by_title), "--label"), "clean-code,ci")
        self.assertEqual(flag_value(issue_line(cmds, by_cite), "--label"), "resilience,ci")
        self.assertEqual(flag_value(issue_line(cmds, not_ci), "--label"), "clean-code")

    def test_pr_labels_are_the_union_plus_testing(self):
        run = make_run()
        add_c(run, ["s.py"])
        add_c(run, ["s.py"], dimension="distributed")
        cmds = self.publish(run)
        self.assertEqual(flag_value(pr_line(cmds), "--label"), "bug,resilience,testing")

    def test_labels_are_created_per_repo_before_any_issue_without_force(self):
        run = multi_run(API={"a.py": "x\n"}, BFF={"a.py": "x\n"})
        add_cross(run, cites("API"), report="correctness", branch="fix/a")
        add_cross(run, cites("BFF"), dimension="docs")
        cmds = self.publish(run)
        lines = cmds.splitlines()
        creates = [x for x in lines if x.startswith("gh label create")]
        first_issue = next(i for i, x in enumerate(lines) if "gh issue create" in x)
        self.assertTrue(all(lines.index(x) < first_issue for x in creates))
        self.assertTrue(all(x.endswith(" || true") and "--force" not in x for x in creates))
        made = {(shlex.split(x)[3], flag_value(x, "--repo")) for x in creates}
        self.assertEqual(made, {("bug", "o/api"), ("testing", "o/api"), ("documentation", "o/bff")})
        bug = next(x for x in creates if " bug " in x)
        self.assertEqual(flag_value(bug, "--color"), "d73a4a")
        self.assertEqual(flag_value(bug, "--description"), "Something isn't working")
        self.assertEqual(subprocess.run(["sh", "-n", str(run / "publish" / "commands.sh")]).returncode, 0)


class PublishTitlesTest(unittest.TestCase):
    def setUp(self):
        self.run = multi_run(API={"a.py": "x\n"})
        self.repo = Path(runmod.load(self.run)["repos"][0]["path"])

    def publish(self):
        publish.prepare_publish(self.run)
        return (self.run / "publish" / "commands.sh").read_text(encoding="utf-8")

    def red(self, branch, subject, title="Cross"):
        sha = red_commit(self.repo, branch, subject)
        return add_cross(self.run, cites("API"), report="correctness", branch=branch, sha_test=sha, title=title)

    def test_pr_title_is_the_conventional_subject_of_the_red_test_commit(self):
        self.red("fix/a", "test(orders): reproduce the double charge")
        self.assertEqual(flag_value(pr_line(self.publish()), "--title"), "test(orders): reproduce the double charge")

    def test_non_conventional_subject_or_no_sha_falls_back_to_test_title(self):
        self.red("fix/a", "Add a failing test", title="Orders charge twice")
        self.assertEqual(flag_value(pr_line(self.publish()), "--title"), "test: Orders charge twice")
        run = make_run()
        add_c(run, ["a.py"], title="No sha here")
        publish.prepare_publish(run)
        cmds = (run / "publish" / "commands.sh").read_text(encoding="utf-8")
        self.assertEqual(flag_value(pr_line(cmds), "--title"), "test: No sha here")

    def test_group_suffix_only_while_the_title_fits_100_chars(self):
        a = red_commit(self.repo, "fix/a", "test: short subject")
        for branch, sha in (("fix/a", a), ("fix/b", "")):
            findingsmod.update(self.run, add_cross(self.run, cites("API"), report="correctness", branch=branch),
                               {"sha_test": sha, "prod_files": ["shared.py"]})
        self.assertEqual(flag_value(pr_line(self.publish()), "--title"), "test: short subject (+1 more)")

    def test_long_group_title_drops_the_suffix_and_long_subject_is_cut(self):
        long = "test: " + " ".join(["word"] * 19)  # 100 chars
        self.assertEqual(len(long), 100)
        a = red_commit(self.repo, "fix/a", long)
        for branch, sha in (("fix/a", a), ("fix/b", "")):
            findingsmod.update(self.run, add_cross(self.run, cites("API"), report="correctness", branch=branch),
                               {"sha_test": sha, "prod_files": ["shared.py"]})
        self.assertEqual(flag_value(pr_line(self.publish()), "--title"), long)
        self.assertEqual(publish.cut_title(long + " more words"), "test: " + " ".join(["word"] * 18) + "…")
        self.assertLessEqual(len(publish.cut_title("x" * 300)), 100)


if __name__ == "__main__":
    unittest.main()
