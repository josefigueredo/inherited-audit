"""Module x pass coverage map: detection of modules, `ia coverage`, and the guard on `ia step ... done`."""
from __future__ import annotations

import unittest
from pathlib import Path

from helpers import SKILL, make_dir, make_git_repo, run_cli, write_tree

from ia import coverage
from ia import detect
from ia import findings as findingsmod
from ia import render as rendermod
from ia import run as runmod

ALL_TOPICS = ",".join(str(n) for n in range(1, coverage.RACES_TOPICS + 1))
FILES = {
    "src/modules/orders/a.ts": "x", "src/modules/users/b.ts": "x", "src/lib/c.ts": "x", "src/__tests__/t.ts": "x",
    "README.md": "x", ".gitignore": "out/\n",
}


def new_run(files=None, subdir=""):
    repo, _ = make_git_repo(files or FILES)
    out = repo / "out"
    spec = f"BACK={repo}" + (f":{subdir}" if subdir else "")
    res = run_cli(["init", "--system", "s", "--repo", spec, "--out", str(out), "--host", "claude-code"])
    assert res.returncode == 0, res.stderr
    res = run_cli(["detect", "--run", str(out)])
    assert res.returncode == 0, res.stderr
    return out


def add(run, pass_, module, result="found", topics=None, note=None):
    args = ["coverage", "add", "--run", str(run), "--pass", pass_, "--module", module, "--result", result]
    if topics:
        args += ["--topics", topics]
    if note:
        args += ["--note", note]
    return run_cli(args)


def fill_correctness(run, modules):
    for m in modules:
        assert add(run, "correctness-general", m).returncode == 0
        assert add(run, "security", m, "nothing").returncode == 0
        assert add(run, "races-distributed", m, "nothing", ALL_TOPICS).returncode == 0


MODS = ["BACK/src/lib", "BACK/src/modules/orders", "BACK/src/modules/users"]


class DetectModulesTest(unittest.TestCase):
    def test_containers_and_other_src_dirs_sorted_without_tests(self):
        root = write_tree(make_dir(), {
            "src/modules/orders/a.ts": "x", "src/modules/users/a.ts": "x", "src/features/f1/a.ts": "x",
            "src/app/shell/a.ts": "x", "src/components/btn/a.ts": "x", "src/lib/a.ts": "x", "src/routes/a.ts": "x",
            "src/__tests__/a.ts": "x", "src/tests/a.ts": "x", "src/test/a.ts": "x", "src/dist/a.js": "x",
            "src/.cache/a": "x", "src/loose.ts": "x", "tests/a.ts": "x", "node_modules/p/a.js": "x",
            "scripts/a.sh": "x"})
        self.assertEqual(detect.detect_modules(root), [
            "src/.", "src/app/shell", "src/components/btn", "src/features/f1", "src/lib", "src/modules/orders",
            "src/modules/users", "src/routes"])

    def test_without_src_uses_root_dirs_and_app_container(self):
        root = write_tree(make_dir(), {
            "app/users/a.py": "x", "app/orders/a.py": "x", "api/a.py": "x", "tests/a.py": "x", "build/a": "x",
            "node_modules/a/b": "x", ".github/w.yml": "x", "__pycache__/a": "x", "top.py": "x"})
        self.assertEqual(detect.detect_modules(root), [".", "api", "app/orders", "app/users"])

    def test_root_files_pseudo_module_only_with_visible_files(self):
        self.assertEqual(detect.detect_modules(write_tree(make_dir(), {"src/main.ts": "x", "src/lib/a.ts": "x"})),
                         ["src/.", "src/lib"])
        self.assertEqual(detect.detect_modules(write_tree(make_dir(), {"src/.eslintrc": "x", "src/lib/a.ts": "x",
                                                                       "main.ts": "x"})), ["src/lib"])
        self.assertEqual(detect.detect_modules(write_tree(make_dir(), {".env": "x", "lib/a.py": "x"})), ["lib"])
        self.assertEqual(detect.detect_root_modules(write_tree(make_dir(), {"Dockerfile": "x", "web/a.ts": "x"})),
                         ["."])

    def test_src_root_files_cell_is_accepted_by_coverage(self):
        out = new_run({**FILES, "src/main.ts": "x"})
        self.assertIn("BACK/src/.", coverage.modules_of(runmod.load(out)))
        res = add(out, "security", "BACK/src/.", "nothing", note="bootstrap")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(runmod.load(out)["coverage"]["security"]["BACK/src/."]["result"], "nothing")

    def test_empty_directories_are_not_modules(self):
        root = write_tree(make_dir(), {"src/real/a.ts": "x"})
        (root / "src" / "empty").mkdir()
        self.assertEqual(detect.detect_modules(root), ["src/real"])

    def test_detect_cli_writes_modules_relative_to_alias_root(self):
        out = new_run({"web/src/modules/m1/a.ts": "x", "web/src/lib/b.ts": "x", "other/z.ts": "x",
                       ".gitignore": "out/\n"}, subdir="web")
        self.assertEqual(runmod.load(out)["modules"], {"BACK": ["src/lib", "src/modules/m1"]})

    def test_detect_root_alias_lists_only_uncovered_root_dirs(self):
        out = new_run({"web/src/lib/b.ts": "x", "web/src/modules/m1/a.ts": "x", ".github/workflows/ci.yml": "x",
                       "infra/main.tf": "x", "scripts/run.sh": "x", "docs/a.md": "x", "Dockerfile": "x",
                       ".gitignore": "out/\n"}, subdir="web")
        mods = runmod.load(out)["modules"]
        self.assertEqual(mods["ROOT"], [".", ".github", "infra", "scripts"])
        self.assertEqual(mods["BACK"], ["src/lib", "src/modules/m1"])

    def test_detect_root_alias_without_those_dirs_has_no_modules(self):
        out = new_run({"web/src/lib/b.ts": "x", "app/z.ts": "x", ".gitignore": "out/\n"}, subdir="web")
        self.assertEqual(runmod.load(out)["modules"], {"BACK": ["src/lib"]})

    def test_detect_rerun_keeps_coverage(self):
        out = new_run()
        add(out, "security", "BACK/src/lib", "nothing")
        self.assertEqual(run_cli(["detect", "--run", str(out)]).returncode, 0)
        self.assertIn("BACK/src/lib", runmod.load(out)["coverage"]["security"])


class CoverageAddTest(unittest.TestCase):
    def test_add_records_cell_and_last_write_wins(self):
        out = new_run()
        res = add(out, "security", "BACK/src/lib", "found", note="first")
        self.assertEqual(res.returncode, 0, res.stderr)
        add(out, "security", "BACK/src/lib", "nothing", note="second")
        cell = runmod.load(out)["coverage"]["security"]["BACK/src/lib"]
        self.assertEqual((cell["result"], cell["note"]), ("nothing", "second"))

    def test_topics_are_stored_sorted_and_unique(self):
        out = new_run()
        add(out, "races-distributed", "BACK/src/lib", "found", "3,1,3,2")
        self.assertEqual(runmod.load(out)["coverage"]["races-distributed"]["BACK/src/lib"]["topics"], [1, 2, 3])

    def test_bad_input_is_usage_error(self):
        out = new_run()
        for args in (("security", "BACK/src/nope", "found", None), ("nope", "BACK/src/lib", "found", None),
                     ("security", "BACK/src/lib", "maybe", None), ("races-distributed", "BACK/src/lib", "found", "0"),
                     ("races-distributed", "BACK/src/lib", "found", "11"),
                     ("races-distributed", "BACK/src/lib", "found", "a,b")):
            res = add(out, *args)
            self.assertEqual(res.returncode, 2, (args, res.stderr))
        self.assertNotIn("coverage", runmod.load(out))

    def test_module_names_known_ones_in_the_error(self):
        out = new_run()
        res = add(out, "security", "BACK/src/nope")
        self.assertIn("BACK/src/lib", res.stderr)

    def test_run_without_modules_is_told_to_detect(self):
        repo, _ = make_git_repo({"a.txt": "x", ".gitignore": "out/\n"})
        run_cli(["init", "--system", "s", "--repo", f"BACK={repo}", "--out", str(repo / "out")])
        res = add(repo / "out", "security", "BACK/src/lib")
        self.assertEqual(res.returncode, 2)
        self.assertIn("detect", res.stderr)


class StatusTest(unittest.TestCase):
    def test_status_prints_grid_and_open_cells(self):
        out = new_run()
        add(out, "security", "BACK/src/lib", "nothing")
        add(out, "races-distributed", "BACK/src/lib", "found", "1,2")
        res = run_cli(["coverage", "status", "--run", str(out)])
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("BACK/src/lib", res.stdout)
        self.assertIn("open cells", res.stdout)
        self.assertIn("BACK/src/modules/orders  correctness-general", res.stdout)
        self.assertIn("races-distributed: topics missing 3,4,5,6,7,8,9,10", res.stdout)

    def test_status_filters_by_pass(self):
        out = new_run()
        res = run_cli(["coverage", "status", "--run", str(out), "--pass", "quality-lenses"])
        self.assertIn("quality-lenses", res.stdout)
        self.assertNotIn("security", res.stdout)

    def test_status_with_nothing_open(self):
        out = new_run()
        fill_correctness(out, MODS)
        res = run_cli(["coverage", "status", "--run", str(out), "--pass", "security"])
        self.assertIn("open cells: none", res.stdout)


class StepGuardTest(unittest.TestCase):
    def test_correctness_done_refuses_listing_open_cells(self):
        out = new_run()
        res = run_cli(["step", "--run", str(out), "correctness", "done"])
        self.assertEqual(res.returncode, 1)
        self.assertIn("BACK/src/modules/orders", res.stderr)
        self.assertIn("security", res.stderr)
        self.assertNotEqual(runmod.load(out)["steps"]["correctness"], "done")

    def test_correctness_done_passes_when_every_cell_is_filled(self):
        out = new_run()
        fill_correctness(out, MODS)
        res = run_cli(["step", "--run", str(out), "correctness", "done"])
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(runmod.load(out)["steps"]["correctness"], "done")

    def test_races_cell_needs_every_topic(self):
        out = new_run()
        fill_correctness(out, MODS)
        add(out, "races-distributed", "BACK/src/lib", "nothing", "1,2,3")
        res = run_cli(["step", "--run", str(out), "correctness", "done"])
        self.assertEqual(res.returncode, 1)
        self.assertIn("BACK/src/lib", res.stderr)
        self.assertIn("4,5,6,7,8,9,10", res.stderr)
        add(out, "races-distributed", "BACK/src/lib", "found", ALL_TOPICS)
        self.assertEqual(run_cli(["step", "--run", str(out), "correctness", "done"]).returncode, 0)

    def test_root_alias_needs_only_security_and_quality_lenses(self):
        out = new_run({"web/src/lib/b.ts": "x", ".github/workflows/ci.yml": "x", "Dockerfile": "x",
                       ".gitignore": "out/\n"}, subdir="web")
        fill_correctness(out, ["BACK/src/lib"])
        res = run_cli(["step", "--run", str(out), "correctness", "done"])
        self.assertEqual(res.returncode, 1)
        self.assertIn("ROOT/.github  security", res.stderr)
        self.assertNotIn("ROOT/.github  correctness-general", res.stderr)
        self.assertNotIn("ROOT/.github  races-distributed", res.stderr)
        for m in ("ROOT/.", "ROOT/.github"):
            self.assertEqual(add(out, "security", m, "nothing").returncode, 0)
        status = run_cli(["coverage", "status", "--run", str(out), "--pass", "races-distributed"]).stdout
        self.assertIn("open cells: none", status)
        self.assertEqual(run_cli(["step", "--run", str(out), "correctness", "done"]).returncode, 0)
        add(out, "quality-lenses", "BACK/src/lib")
        res = run_cli(["step", "--run", str(out), "quality", "done"])
        self.assertEqual(res.returncode, 1)
        self.assertIn("ROOT/.  quality-lenses", res.stderr)
        for m in ("ROOT/.", "ROOT/.github"):
            add(out, "quality-lenses", m)
        self.assertEqual(run_cli(["step", "--run", str(out), "quality", "done"]).returncode, 0)

    def test_races_cell_without_topics_stays_open(self):
        out = new_run()
        fill_correctness(out, MODS)
        add(out, "races-distributed", "BACK/src/lib", "nothing")
        self.assertEqual(run_cli(["step", "--run", str(out), "correctness", "done"]).returncode, 1)

    def test_quality_needs_only_quality_lenses(self):
        out = new_run()
        res = run_cli(["step", "--run", str(out), "quality", "done"])
        self.assertEqual(res.returncode, 1)
        self.assertNotIn("security", res.stderr)
        for m in MODS:
            add(out, "quality-lenses", m, "found")
        self.assertEqual(run_cli(["step", "--run", str(out), "quality", "done"]).returncode, 0)

    def test_in_progress_and_other_steps_are_not_guarded(self):
        out = new_run()
        for step, state in (("correctness", "in_progress"), ("proof", "done"), ("tests", "done")):
            self.assertEqual(run_cli(["step", "--run", str(out), step, state]).returncode, 0, step)

    def test_force_open_closes_and_records_waiver(self):
        out = new_run()
        res = run_cli(["step", "--run", str(out), "correctness", "done", "--force-open", "frontend out of scope"])
        self.assertEqual(res.returncode, 0, res.stderr)
        manifest = runmod.load(out)
        self.assertEqual(manifest["steps"]["correctness"], "done")
        waiver = manifest["coverage_waivers"][0]
        self.assertEqual((waiver["step"], waiver["reason"]), ("correctness", "frontend out of scope"))
        self.assertIn("BACK/src/lib / security", waiver["open"])

    def test_force_open_needs_a_reason(self):
        out = new_run()
        res = run_cli(["step", "--run", str(out), "correctness", "done", "--force-open", "  "])
        self.assertEqual(res.returncode, 2)

    def test_force_open_with_nothing_open_records_nothing(self):
        out = new_run()
        fill_correctness(out, MODS)
        run_cli(["step", "--run", str(out), "correctness", "done", "--force-open", "why not"])
        self.assertNotIn("coverage_waivers", runmod.load(out))

    def test_iteration_1_manifest_without_modules_closes(self):
        repo, _ = make_git_repo({"a.txt": "x", ".gitignore": "out/\n"})
        out = repo / "out"
        run_cli(["init", "--system", "s", "--repo", f"BACK={repo}", "--out", str(out)])
        self.assertNotIn("modules", runmod.load(out))
        self.assertEqual(run_cli(["step", "--run", str(out), "correctness", "done"]).returncode, 0)
        self.assertEqual(run_cli(["coverage", "status", "--run", str(out)]).returncode, 0)

    def test_proof_done_warns_about_candidates_but_closes(self):
        out = new_run()
        findingsmod.add(out, {"report": "correctness", "category": "bug", "dimension": "bug", "title": "T",
                              "verdict": "candidate", "severity": "high", "confidence": "unverified",
                              "source": "p", "what_happens": "w",
                              "evidence": [{"cite": "BACK/src/lib/c.ts", "from": 1, "to": 1, "note": "n"}]})
        res = run_cli(["step", "--run", str(out), "proof", "done"])
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("warning", res.stderr)
        self.assertIn("C-01", res.stderr)
        self.assertEqual(runmod.load(out)["steps"]["proof"], "done")

    def test_proof_done_warning_lists_only_correctness_candidates(self):
        out = new_run()
        base = {"category": "bug", "verdict": "candidate", "severity": "high", "confidence": "unverified",
                "source": "p", "what_happens": "w", "title": "T",
                "evidence": [{"cite": "BACK/src/lib/c.ts", "from": 1, "to": 1, "note": "n"}]}
        findingsmod.add(out, {**base, "report": "quality", "dimension": "code", "suggestion": "s", "effort": "S"})
        res = run_cli(["step", "--run", str(out), "proof", "done"])
        self.assertEqual((res.returncode, res.stderr), (0, ""))
        findingsmod.add(out, {**base, "report": "correctness", "dimension": "bug"})
        res = run_cli(["step", "--run", str(out), "proof", "done"])
        self.assertIn("1 correctness findings", res.stderr)
        self.assertIn("C-01", res.stderr)
        self.assertNotIn("Q-01", res.stderr)

    def test_proof_done_without_candidates_is_silent(self):
        out = new_run()
        res = run_cli(["step", "--run", str(out), "proof", "done"])
        self.assertEqual(res.returncode, 0)
        self.assertEqual(res.stderr, "")


class NotApplicableTest(unittest.TestCase):
    def test_not_applicable_needs_a_note(self):
        out = new_run()
        res = add(out, "races-distributed", "BACK/src/lib", "n/a")
        self.assertEqual(res.returncode, 2)
        self.assertIn("--note", res.stderr)

    def test_not_applicable_closes_a_races_cell_without_topics(self):
        out = new_run()
        fill_correctness(out, MODS)
        res = add(out, "races-distributed", "BACK/src/lib", "n/a", note="pure UI helpers: no I/O, no shared state")
        self.assertEqual(res.returncode, 0, res.stderr)
        res = run_cli(["step", "--run", str(out), "correctness", "done"])
        self.assertEqual(res.returncode, 0, res.stderr)
        cell = runmod.load(out)["coverage"]["races-distributed"]["BACK/src/lib"]
        self.assertEqual(cell, {"result": "n/a", "note": "pure UI helpers: no I/O, no shared state"})

    def test_not_applicable_refuses_topics(self):
        out = new_run()
        res = add(out, "races-distributed", "BACK/src/lib", "n/a", topics="1,2", note="x")
        self.assertEqual(res.returncode, 2)

    def test_status_shows_not_applicable(self):
        out = new_run()
        add(out, "security", "BACK/src/lib", "n/a", note="generated code")
        res = run_cli(["coverage", "status", "--run", str(out), "--pass", "security"])
        self.assertIn("n/a", res.stdout.splitlines()[2])

    def test_render_lists_not_applicable_cells_with_their_note(self):
        repo = {"alias": "BACK", "path": "/r", "sha": "a" * 40, "remote": "", "subdir": ""}
        manifest = {"repos": [repo], "filter": {}, "modules": {"BACK": ["src/lib"]},
                    "coverage": {"races-distributed": {"BACK/src/lib": {"result": "n/a", "note": "no shared state"}},
                                 "security": {"BACK/src/lib": {"result": "nothing"}}}}
        html = rendermod._how(manifest, "correctness", [], rendermod.LABELS["es"])
        self.assertIn(rendermod.LABELS["es"]["how_not_applicable"], html)
        self.assertIn("BACK/src/lib", html)
        self.assertIn("no shared state", html)
        quality = rendermod._how(manifest, "quality", [], rendermod.LABELS["en"])
        self.assertNotIn("no shared state", quality)


class RenderWaiverTest(unittest.TestCase):
    def test_waivers_are_shown_in_how_it_was_done(self):
        manifest = {"repos": [], "filter": {}, "coverage_waivers": [
            {"step": "correctness", "reason": "frontend out of scope", "open": ["BACK/src/lib / security"]}]}
        html = rendermod._how(manifest, "correctness", [], rendermod.LABELS["es"])
        self.assertIn("frontend out of scope", html)
        self.assertIn("BACK/src/lib / security", html)

    def test_no_waivers_adds_nothing(self):
        manifest = {"repos": [], "filter": {}}
        html = rendermod._how(manifest, "correctness", [], rendermod.LABELS["es"])
        self.assertNotIn("frontend", html)


class DocsTest(unittest.TestCase):
    def read(self, rel):
        return (SKILL / rel).read_text(encoding="utf-8")

    def test_skill_md_teaches_the_coverage_map(self):
        text = self.read("SKILL.md")
        for needle in ("ia.py coverage add", "ia.py coverage status", "--force-open", "--topics", "`n/a`"):
            self.assertIn(needle, text)

    def test_not_applicable_is_documented_wherever_results_are(self):
        for rel in ("references/checklist.md", "references/schema.md", "references/passes/races-distributed.md"):
            self.assertIn("n/a", self.read(rel), rel)

    def test_checklist_and_schema_describe_it(self):
        self.assertIn("coverage", self.read("references/checklist.md"))
        schema = self.read("references/schema.md")
        for key in ("`modules`", "`coverage`", "`coverage_waivers`"):
            self.assertIn(key, schema)

    def test_races_topic_count_matches_the_pass_file(self):
        import re
        text = self.read("references/passes/races-distributed.md")
        scope = text.split("## Scope")[1].split("## Out of scope")[0]
        self.assertEqual(len(re.findall(r"^\d+\. \*\*", scope, re.M)), coverage.RACES_TOPICS)


if __name__ == "__main__":
    unittest.main()
