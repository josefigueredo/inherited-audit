from __future__ import annotations

import re
import unittest

from helpers import SKILL, make_dir, make_git_repo, run_cli

from ia import detect
from ia import run as runmod

REFS = SKILL / "references"


def make_run():
    repo, _ = make_git_repo({"a.py": "x = 1\n"})
    run = make_dir() / "run"
    runmod.init_run("sys", [("BACK", repo, "")], run, "es", False, "claude-code")
    manifest = runmod.load(run)
    manifest["workers"] = {"claude-code": [dict(w) for w in detect.worker_status("claude-code", [])]}
    runmod.save(run, manifest)
    return run


def row(run, step, worker):
    rows = runmod.load(run)["workers"]["claude-code"]
    return next(r for r in rows if r["step"] == step and r["worker"] == worker)


class SetWorkerAvailabilityTest(unittest.TestCase):
    def test_records_plugin_row_true(self):
        run = make_run()
        r = run_cli(["set", "--run", str(run), "workers.claude-code.quality.feature-dev:code-architect.available=true"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIs(row(run, "quality", "feature-dev:code-architect")["available"], True)

    def test_worker_name_with_slash_dots_and_spaces(self):
        run = make_run()
        key = "workers.claude-code.correctness-bugs./code-review per module.available=false"
        r = run_cli(["set", "--run", str(run), key])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIs(row(run, "correctness-bugs", "/code-review per module")["available"], False)

    def test_only_available_changes(self):
        run = make_run()
        before = dict(row(run, "e2e", "Playwright"))
        run_cli(["set", "--run", str(run), "workers.claude-code.e2e.Playwright.available=true"])
        after = dict(row(run, "e2e", "Playwright"))
        before["available"] = True
        self.assertEqual(before, after)

    def test_rejects_unknown_host_step_worker_and_non_bool(self):
        run = make_run()
        for key in ("workers.nope.quality.feature-dev:code-architect.available=true",
                    "workers.claude-code.nostep.feature-dev:code-architect.available=true",
                    "workers.claude-code.quality.nobody.available=true",
                    "workers.claude-code.quality.feature-dev:code-architect.available=yes",
                    "workers.claude-code.quality.feature-dev:code-architect.available=1",
                    "workers.claude-code.quality.feature-dev:code-architect.available=null",
                    "workers.claude-code.quality.feature-dev:code-architect.install=x"):
            r = run_cli(["set", "--run", str(run), key])
            self.assertEqual(r.returncode, 2, key + r.stdout + r.stderr)
        self.assertIsNone(row(run, "quality", "feature-dev:code-architect")["available"])

    def test_malformed_workers_manifest_is_usage_error(self):
        run = make_run()
        manifest = runmod.load(run)
        manifest["workers"] = {"claude-code": None}
        runmod.save(run, manifest)
        r = run_cli(["set", "--run", str(run), "workers.claude-code.quality.x.available=true"])
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_rejects_before_detect(self):
        repo, _ = make_git_repo({"a.py": "x = 1\n"})
        run = make_dir() / "run"
        runmod.init_run("sys", [("BACK", repo, "")], run, "es", False, "claude-code")
        r = run_cli(["set", "--run", str(run), "workers.claude-code.quality.x.available=true"])
        self.assertEqual(r.returncode, 2)
        self.assertIn("detect", r.stdout + r.stderr)

    def test_atomic_with_other_keys(self):
        run = make_run()
        r = run_cli(["set", "--run", str(run), "lang=en", "workers.claude-code.quality.nobody.available=true"])
        self.assertEqual(r.returncode, 2)
        self.assertEqual(runmod.load(run)["lang"], "es")


class RecipesDocTest(unittest.TestCase):
    def test_codex_recipe_exact(self):
        text = (REFS / "workers.md").read_text(encoding="utf-8")
        self.assertIn('codex exec -s read-only --skip-git-repo-check -o <file> "<prompt>" < /dev/null', text)
        self.assertIn("log header", text)
        self.assertIn('codex exec -s read-only --skip-git-repo-check -o <file> "<prompt>" < /dev/null',
                      (REFS / "passes" / "contrast.md").read_text(encoding="utf-8"))

    def test_measurement_recipes_documented(self):
        text = (REFS / "workers.md").read_text(encoding="utf-8")
        for needle in ("depcruise", "-p typescript@5 depcruise", "--ts-config", "--include-only", "--output-type json", "0 modules cruised",
                       "knip", "jscpd", "--min-tokens 50", "ia.py set --run <run-dir> 'workers."):
            self.assertIn(needle, text)
        self.assertRegex(text, r"(?i)failed measurement")

    def test_quality_lenses_points_to_recipes_and_fallback(self):
        text = (REFS / "passes" / "quality-lenses.md").read_text(encoding="utf-8")
        self.assertIn("workers.md", text)
        self.assertRegex(text, r"(?i)failed measurement")


if __name__ == "__main__":
    unittest.main()
