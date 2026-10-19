from __future__ import annotations

import contextlib
import io

import json
import unittest
from datetime import date
from pathlib import Path

from helpers import make_dir, make_git_repo, run_cli, write_tree

from ia import run


def init_cli(repo: Path, *extra: str, system: str = "demo"):
    return run_cli(["init", "--system", system, "--repo", f"BACK={repo}", *extra])


class InitTest(unittest.TestCase):
    def test_init_pins_head_sha_and_remote(self):
        repo, sha = make_git_repo({"a.txt": "x"}, remote="https://github.com/o/r.git")
        out = make_dir() / "run"
        run_dir = run.init_run("demo", [("BACK", repo, "")], out, "es", False, "unknown")
        manifest = run.load(run_dir)
        self.assertEqual(manifest["repos"][0]["sha"], sha)
        self.assertEqual(manifest["repos"][0]["remote"], "https://github.com/o/r")
        self.assertEqual(manifest["baseline"], {})
        self.assertEqual(list(manifest["steps"]), list(run.STEPS))
        self.assertTrue((run_dir / "findings").is_dir())
        self.assertTrue((run_dir / "outputs").is_dir())

    def test_credentialed_remote_is_stripped_flagged_and_never_printed(self):
        repo, _ = make_git_repo({"a.txt": "x"}, remote="https://user:tok123@github.com/o/r.git")
        out = make_dir() / "run"
        run_dir = run.init_run("demo", [("BACK", repo, "")], out, "es", False, "unknown")
        manifest = run.load(run_dir)
        self.assertEqual(manifest["repos"][0]["remote"], "https://github.com/o/r")
        self.assertIs(manifest["repos"][0]["remote_had_credentials"], True)
        self.assertNotIn("tok123", (run_dir / "manifest.json").read_text(encoding="utf-8"))
        status = run_cli(["status", "--run", str(run_dir)])
        self.assertNotIn("tok123", status.stdout + status.stderr)

    def test_status_masks_remote_of_an_old_manifest(self):
        repo, _ = make_git_repo({"a.txt": "x"})
        run_dir = run.init_run("demo", [("BACK", repo, "")], make_dir() / "run", "es", False, "unknown")
        manifest = run.load(run_dir)
        manifest["repos"][0]["remote"] = "https://user:tok123@github.com/o/r"
        run.save(run_dir, manifest)
        self.assertNotIn("tok123", run.status_text(run_dir))

    def test_git_https_remote_token_is_stripped_from_manifest_and_status(self):
        repo, _ = make_git_repo({"a.txt": "x"}, remote="git+https://tok123@github.com/o/r.git")
        run_dir = run.init_run("demo", [("BACK", repo, "")], make_dir() / "run", "es", False, "unknown")
        manifest = run.load(run_dir)
        self.assertIs(manifest["repos"][0]["remote_had_credentials"], True)
        self.assertNotIn("tok123", (run_dir / "manifest.json").read_text(encoding="utf-8"))
        manifest["repos"][0]["remote"] = "git+https://tok123@github.com/o/r"
        run.save(run_dir, manifest)
        self.assertNotIn("tok123", run.status_text(run_dir))

    def test_git_ssh_user_is_not_a_credential(self):
        self.assertFalse(run.remote_had_credentials("git+ssh://git@github.com/o/r"))
        self.assertFalse(run.remote_had_credentials("ssh://git@github.com/o/r"))
        self.assertTrue(run.remote_had_credentials("ssh://u:pw@github.com/o/r"))
        self.assertTrue(run.remote_had_credentials("https://tok@github.com/o/r"))
        self.assertEqual(run.normalise_remote("https://tok@github.com/o/r.git"), "https://github.com/o/r")

    def test_ssh_and_missing_remote_are_normalised(self):
        repo, _ = make_git_repo({"a.txt": "x"}, remote="git@github.com:o/r.git")
        self.assertEqual(run.normalise_remote(run.remote_of(repo)), "https://github.com/o/r")
        self.assertEqual(run.normalise_remote("git@host:o/r"), "https://host/o/r")
        bare, _ = make_git_repo({"a.txt": "x"})
        self.assertEqual(run.remote_of(bare), "")

    def test_init_refuses_dirty_repo(self):
        repo, _ = make_git_repo({"a.txt": "x"})
        (repo / "untracked.txt").write_text("u")
        with self.assertRaises(run.RunError) as ctx:
            run.init_run("demo", [("BACK", repo, "")], make_dir() / "run", "es", False, "unknown")
        self.assertIn("untracked.txt", str(ctx.exception))
        result = init_cli(repo, "--out", str(make_dir() / "run"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("untracked.txt", result.stderr)

    def test_init_refuses_modified_repo(self):
        repo, _ = make_git_repo({"a.txt": "x"})
        (repo / "a.txt").write_text("changed")
        result = init_cli(repo, "--out", str(make_dir() / "run"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("a.txt", result.stderr)

    def test_init_refuses_committable_out_dir(self):
        repo, _ = make_git_repo({"a.txt": "x"})
        result = init_cli(repo, "--out", str(repo / "audit"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("could be committed", result.stderr)

    def test_init_accepts_ignored_out_dir_inside_repo(self):
        repo, _ = make_git_repo({"a.txt": "x", ".gitignore": "audit/\n"})
        result = init_cli(repo, "--out", str(repo / "audit"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((repo / "audit" / "manifest.json").is_file())

    def test_default_out_dir_is_beside_first_repo(self):
        repo, _ = make_git_repo({"a.txt": "x"}, parent=make_dir() / "repo")
        result = init_cli(repo)
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = repo.parent / "demo-inherited-audit" / date.today().isoformat() / "manifest.json"
        self.assertTrue(expected.is_file())
        self.assertIn(str(expected.parent), result.stdout)

    def test_default_out_dir_uses_the_top_level_parent_for_a_subfolder_repo(self):
        repo, _ = make_git_repo({"api/a.txt": "x"}, parent=make_dir() / "repo")
        result = init_cli(repo / "api")
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = repo.parent / "demo-inherited-audit" / date.today().isoformat() / "manifest.json"
        self.assertTrue(expected.is_file())

    def test_system_name_must_be_safe_for_file_names(self):
        repo, _ = make_git_repo({"a.txt": "x"})
        for bad in ("../escape", "a/b", "a b", ".hidden", "-x", ""):
            out = make_dir() / "run"
            result = init_cli(repo, "--out", str(out), system=bad)
            self.assertEqual(result.returncode, 2, bad)
            self.assertIn("--system", result.stderr)
            self.assertFalse(out.exists(), bad)
        with self.assertRaises(run.UsageError):
            run.init_run("../x", [("BACK", repo, "")], make_dir() / "run", "es", False, "unknown")
        self.assertEqual(init_cli(repo, "--out", str(make_dir() / "run"), system="my-sys_2.0").returncode, 0)

    def test_init_refuses_to_overwrite_existing_run(self):
        repo, sha = make_git_repo({"a.txt": "x"})
        out = make_dir() / "run"
        run_dir = run.init_run("demo", [("BACK", repo, "")], out, "es", False, "unknown")
        run.set_step(run_dir, "baseline", "done")
        with self.assertRaises(run.RunError) as ctx:
            run.init_run("demo", [("BACK", repo, "")], out, "es", False, "unknown")
        self.assertIn("already exists", str(ctx.exception))
        self.assertIn("status", str(ctx.exception))
        result = init_cli(repo, "--out", str(out))
        self.assertEqual(result.returncode, 1)
        self.assertIn("already exists", result.stderr)
        self.assertEqual(run.load(run_dir)["steps"]["baseline"], "done")

    def test_duplicate_alias_is_usage_error(self):
        repo, _ = make_git_repo({"a.txt": "x"})
        result = run_cli(["init", "--system", "demo", "--repo", f"BACK={repo}", "--repo", f"BACK={repo}",
                          "--out", str(make_dir() / "run")])
        self.assertEqual(result.returncode, 2)
        self.assertIn("duplicate", result.stderr)

    def test_repo_spec_parsing(self):
        repo, _ = make_git_repo({"a.txt": "x"})
        alias, path, sub = run.parse_repo_spec(f"BACK={repo}")
        self.assertEqual((alias, path, sub), ("BACK", repo.resolve(), ""))
        alias, path, sub = run.parse_repo_spec(f"BACK={repo}:sub/dir")
        self.assertEqual((alias, path, sub), ("BACK", repo.resolve(), "sub/dir"))
        with self.assertRaises(run.UsageError):
            run.parse_repo_spec("nopath")

    def test_cli_subdir_is_stored(self):
        repo, _ = make_git_repo({"a.txt": "x"})
        out = make_dir() / "run"
        result = run_cli(["init", "--system", "demo", "--repo", f"BACK={repo}:sub/dir", "--out", str(out),
                          "--publish", "--host", "cursor", "--lang", "en"])
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = json.loads((out / "manifest.json").read_text())
        self.assertEqual(manifest["repos"][0]["subdir"], "sub/dir")
        self.assertEqual(manifest["options"], {"fix": False, "publish": True})
        self.assertEqual((manifest["host"], manifest["lang"]), ("cursor", "en"))


    def test_init_rejects_the_removed_fix_flag(self):
        repo, _ = make_git_repo({"a.txt": "x"})
        out = make_dir() / "run"
        result = run_cli(["init", "--system", "demo", "--repo", f"BACK={repo}", "--out", str(out), "--fix"])
        self.assertEqual(result.returncode, 2)
        self.assertIn("--fix", result.stderr)
        self.assertFalse((out / "manifest.json").exists())

    def test_legacy_manifest_with_fix_true_loads_as_false_with_a_warning(self):
        repo, _ = make_git_repo({"a.txt": "x"})
        out = make_dir() / "run"
        run_dir = run.init_run("demo", [("BACK", repo, "")], out, "en", False, "unknown")
        manifest = json.loads((run_dir / "manifest.json").read_text())
        manifest["options"]["fix"] = True
        (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        result = run_cli(["status", "--run", str(run_dir)])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr.strip().count("\n"), 0, result.stderr)
        self.assertIn("fixes are no longer applied", result.stderr)
        captured = io.StringIO()
        with contextlib.redirect_stderr(captured):
            self.assertFalse(run.load(run_dir)["options"]["fix"])
        self.assertIn("fixes are no longer applied", captured.getvalue())

    def test_init_normalises_path_to_toplevel_and_folds_into_subdir(self):
        repo, _ = make_git_repo({"api/src/a.txt": "x"})
        out = make_dir() / "run"
        result = run_cli(["init", "--system", "demo", "--repo", f"BACK={repo / 'api'}:src", "--out", str(out)])
        self.assertEqual(result.returncode, 0, result.stderr)
        entry = json.loads((out / "manifest.json").read_text())["repos"][0]
        self.assertEqual(entry["path"], str(repo.resolve()))
        self.assertEqual(entry["subdir"], "api/src")
        out2 = make_dir() / "run"
        self.assertEqual(run_cli(["init", "--system", "demo", "--repo", f"BACK={repo / 'api'}", "--out", str(out2)]).returncode, 0)
        entry2 = json.loads((out2 / "manifest.json").read_text())["repos"][0]
        self.assertEqual((entry2["path"], entry2["subdir"]), (str(repo.resolve()), "api"))


class RootAliasTest(unittest.TestCase):
    def init(self, specs, files):
        repo, _ = make_git_repo(files)
        out = make_dir() / "run"
        args = ["init", "--system", "demo", "--out", str(out)]
        for spec in specs:
            args += ["--repo", spec.format(repo=repo)]
        result = run_cli(args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads((out / "manifest.json").read_text())["repos"], result.stdout

    def test_root_alias_added_when_every_alias_has_a_subdir(self):
        repos, out = self.init(["BACK={repo}:api", "FRONT={repo}:web"], {"api/a.py": "x", "web/b.js": "x", "Dockerfile": "x"})
        self.assertEqual([r["alias"] for r in repos], ["BACK", "FRONT", "ROOT"])
        self.assertEqual(repos[2]["subdir"], "")
        self.assertEqual((repos[2]["path"], repos[2]["sha"]), (repos[0]["path"], repos[0]["sha"]))
        self.assertIn("ROOT", out)

    def test_no_root_alias_when_an_alias_covers_the_root(self):
        repos, _ = self.init(["BACK={repo}", "FRONT={repo}:web"], {"api/a.py": "x", "web/b.js": "x"})
        self.assertEqual([r["alias"] for r in repos], ["BACK", "FRONT"])

    def test_root_alias_avoids_taken_names(self):
        repos, _ = self.init(["ROOT={repo}:api"], {"api/a.py": "x"})
        self.assertEqual([r["alias"] for r in repos], ["ROOT", "ROOT2"])

    def test_one_root_per_repo(self):
        repo, _ = make_git_repo({"api/a.py": "x"})
        repo2, _ = make_git_repo({"a.py": "x"})
        out = make_dir() / "run"
        r = run_cli(["init", "--system", "demo", "--out", str(out), "--repo", f"A={repo}:api", "--repo", f"B={repo2}"])
        self.assertEqual(r.returncode, 0, r.stderr)
        aliases = [x["alias"] for x in json.loads((out / "manifest.json").read_text())["repos"]]
        self.assertEqual(aliases, ["A", "B", "ROOT"])

    def test_root_alias_needs_no_baseline(self):
        repo, _ = make_git_repo({"api/a.py": "x", "api/test_a.py": "x"})
        out = make_dir() / "run"
        self.assertEqual(run_cli(["init", "--system", "demo", "--out", str(out), "--repo", f"A={repo}:api"]).returncode, 0)
        manifest = run.load(out)
        manifest["baseline"]["A"] = {"result": {"measured": True, "parsed": True}}
        self.assertTrue(run.baselines_closed(manifest))


class ManifestTest(unittest.TestCase):
    def make_run(self) -> Path:
        repo, _ = make_git_repo({"a.txt": "x"})
        return run.init_run("demo", [("BACK", repo, "")], make_dir() / "run", "es", False, "unknown")

    def test_resume_refuses_newer_manifest_version(self):
        run_dir = self.make_run()
        manifest = run.load(run_dir)
        manifest["version"] = 2
        run.save(run_dir, manifest)
        with self.assertRaises(run.RunError) as ctx:
            run.load(run_dir)
        self.assertIn("newer", str(ctx.exception))

    def test_next_step_skips_done_and_skipped(self):
        manifest = {"steps": {s: "pending" for s in run.STEPS}}
        self.assertEqual(run.next_step(manifest), "baseline")
        manifest["steps"]["baseline"] = "done"
        manifest["steps"]["correctness"] = "skipped"
        self.assertEqual(run.next_step(manifest), "proof")
        for s in run.STEPS:
            manifest["steps"][s] = "done"
        self.assertIsNone(run.next_step(manifest))

    def test_set_step_persists_and_leaves_no_temp_files(self):
        run_dir = self.make_run()
        run.set_step(run_dir, "baseline", "in_progress")
        self.assertEqual(run.load(run_dir)["steps"]["baseline"], "in_progress")
        self.assertEqual(sorted(p.name for p in run_dir.iterdir()), ["findings", "manifest.json", "outputs"])

    def test_set_step_rejects_unknown_step_or_state(self):
        run_dir = self.make_run()
        with self.assertRaises(run.UsageError):
            run.set_step(run_dir, "nope", "done")
        with self.assertRaises(run.UsageError):
            run.set_step(run_dir, "baseline", "weird")
        self.assertEqual(run_cli(["step", "--run", str(run_dir), "nope", "done"]).returncode, 2)
        self.assertEqual(run_cli(["step", "--run", str(run_dir), "baseline", "weird"]).returncode, 2)
        self.assertEqual(run_cli(["step", "--run", str(run_dir), "baseline", "done"]).returncode, 0)


class StatusTest(unittest.TestCase):
    def test_status_prints_system_shas_steps_counts_and_next(self):
        repo, sha = make_git_repo({"a.txt": "x"})
        run_dir = run.init_run("demo", [("BACK", repo, "")], make_dir() / "run", "es", False, "unknown")
        run.set_step(run_dir, "baseline", "done")
        write_tree(run_dir / "findings", {
            "C-01.json": json.dumps({"id": "C-01", "verdict": "confirmed"}),
            "C-02.json": json.dumps({"id": "C-02", "verdict": "confirmed"}),
            "Q-01.json": json.dumps({"id": "Q-01", "verdict": "discarded"}),
        })
        result = run_cli(["status", "--run", str(run_dir)])
        self.assertEqual(result.returncode, 0, result.stderr)
        out = result.stdout
        self.assertIn("demo", out)
        self.assertIn(sha, out)
        self.assertIn("baseline", out)
        self.assertIn("confirmed: 2", out)
        self.assertIn("discarded: 1", out)
        self.assertIn("candidate: 0", out)
        self.assertIn("next: correctness", out)

    def test_status_without_findings_dir_counts_zero(self):
        repo, _ = make_git_repo({"a.txt": "x"})
        run_dir = run.init_run("demo", [("BACK", repo, "")], make_dir() / "run", "es", False, "unknown")
        (run_dir / "findings").rmdir()
        result = run_cli(["status", "--run", str(run_dir)])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("confirmed: 0", result.stdout)

    def test_status_names_corrupt_finding_file(self):
        repo, _ = make_git_repo({"a.txt": "x"})
        run_dir = run.init_run("demo", [("BACK", repo, "")], make_dir() / "run", "es", False, "unknown")
        write_tree(run_dir / "findings", {"C-01.json": "{not json", "C-02.json": "[1]"})
        with self.assertRaises(run.RunError) as ctx:
            run.verdict_counts(run_dir)
        self.assertIn("C-01.json", str(ctx.exception))
        result = run_cli(["status", "--run", str(run_dir)])
        self.assertEqual(result.returncode, 1)
        self.assertIn("C-01.json", result.stderr)
        (run_dir / "findings" / "C-01.json").unlink()
        result = run_cli(["status", "--run", str(run_dir)])
        self.assertEqual(result.returncode, 1)
        self.assertIn("C-02.json", result.stderr)

    def test_status_on_missing_run_fails_cleanly(self):
        result = run_cli(["status", "--run", str(make_dir() / "nope")])
        self.assertEqual(result.returncode, 1)
        self.assertIn("manifest", result.stderr)


class SetKeysTest(unittest.TestCase):
    def setUp(self):
        repo, _ = make_git_repo({"a.txt": "x"})
        self.run_dir = make_dir() / "run"
        run.init_run("demo", [("BACK", repo, "")], self.run_dir, "es", False, "unknown")

    def cli(self, *pairs):
        return run_cli(["set", "--run", str(self.run_dir), *pairs])

    def test_sets_every_allowed_key(self):
        r = self.cli("host=cursor", "lang=en", "options.publish=true", 'sections.correctness=["auth","orders"]',
                     'sections.quality=["api"]', 'strengths=["Clear module boundaries BACK/src/app.py:1"]',
                     "baseline.BACK.tests_branch=tests/back-coverage")
        self.assertEqual(r.returncode, 0, r.stderr)
        m = run.load(self.run_dir)
        self.assertEqual((m["host"], m["lang"], m["options"]["publish"]), ("cursor", "en", True))
        self.assertEqual(m["sections"], {"correctness": ["auth", "orders"], "quality": ["api"]})
        self.assertEqual(m["strengths"], ["Clear module boundaries BACK/src/app.py:1"])
        self.assertEqual(m["baseline"]["BACK"]["tests_branch"], "tests/back-coverage")
        self.assertFalse(m["options"]["fix"])
        self.assertEqual(sorted(p.name for p in self.run_dir.iterdir()), ["findings", "manifest.json", "outputs"])

    def test_author_model_is_a_settable_string(self):
        r = self.cli("author_model=claude-opus-4")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(run.load(self.run_dir)["author_model"], "claude-opus-4")
        self.assertEqual(self.cli("author_model=4").returncode, 0)
        self.assertEqual(run.load(self.run_dir)["author_model"], "4")
        self.assertEqual(self.cli("author_model=").returncode, 2)

    def test_tests_branch_keeps_the_plan(self):
        m = run.load(self.run_dir)
        m["baseline"]["BACK"] = {"plan": {"stack": "python"}}
        run.save(self.run_dir, m)
        self.assertEqual(self.cli("baseline.BACK.tests_branch=tests/x").returncode, 0)
        self.assertEqual(run.load(self.run_dir)["baseline"]["BACK"], {"plan": {"stack": "python"},
                                                                      "tests_branch": "tests/x"})

    def test_rejects_bad_keys_and_shapes_without_writing(self):
        before = (self.run_dir / "manifest.json").read_text()
        bad = ["host=vim", "options.publish=yes", "options.fix=true", "sections.correctness=auth",
               'sections.other=["x"]', 'strengths=[1]', "strengths=nice", "baseline.NOPE.tests_branch=x",
               "baseline.BACK.tests_branch=", "baseline.BACK.plan={}", "system=other", "lang=",
               "baseline.BACK.result.passed=-1", "baseline.BACK.result.passed=1.5", "baseline.BACK.result.total=x",
               "baseline.BACK.result.passed=true", "baseline.BACK.result.coverage=101", "baseline.BACK.result.coverage=-1",
               "baseline.BACK.result.measured=1", "baseline.BACK.result.runner=", "baseline.BACK.result.source=x",
               "baseline.NOPE.result.total=0",
               "nonsense", "steps.baseline=done"]
        for pair in bad:
            r = self.cli("host=cursor", pair)
            self.assertEqual(r.returncode, 2, pair)
            self.assertIn("error:", r.stderr)
        self.assertEqual((self.run_dir / "manifest.json").read_text(), before)

    def test_string_keys_are_not_json_parsed(self):
        r = self.cli("baseline.BACK.tests_branch=2024", "lang=3", "baseline.BACK.result.runner=null")
        self.assertEqual(r.returncode, 0, r.stderr)
        m = run.load(self.run_dir)
        self.assertEqual((m["baseline"]["BACK"]["tests_branch"], m["lang"]), ("2024", "3"))
        self.assertEqual(m["baseline"]["BACK"]["result"]["runner"], "null")

    def test_result_keys_set_source_manual_and_keep_existing_fields(self):
        m = run.load(self.run_dir)
        m["baseline"]["BACK"] = {"plan": {"stack": "python"}, "result": {"passed": None, "output": "o.txt"}}
        run.save(self.run_dir, m)
        r = self.cli("baseline.BACK.result.passed=5", "baseline.BACK.result.coverage=null",
                     "baseline.BACK.result.measured=false")
        self.assertEqual(r.returncode, 0, r.stderr)
        res = run.load(self.run_dir)["baseline"]["BACK"]["result"]
        self.assertEqual((res["passed"], res["coverage"], res["measured"], res["source"], res["output"]),
                         (5, None, False, "manual", "o.txt"))

    def test_requires_a_pair(self):
        self.assertEqual(run_cli(["set", "--run", str(self.run_dir)]).returncode, 2)


if __name__ == "__main__":
    unittest.main()
