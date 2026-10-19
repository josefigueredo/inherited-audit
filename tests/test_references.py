"""SKILL.md and its core references name only what exists, and the references cover what the CLI tracks."""
from __future__ import annotations

import re
import unittest

from helpers import SKILL
from ia import cli, detect, run

REFS = SKILL / "references"


def _read(path) -> str:
    return path.read_text(encoding="utf-8")


def _skill_md() -> str:
    return _read(SKILL / "SKILL.md")


def _host_section(text: str, host: str) -> str:
    """The `## ... (`host`)` section of workers.md, up to the next `## ` heading."""
    match = re.search(rf"^## [^\n]*\(`{re.escape(host)}`\)\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    assert match, f"workers.md has no section for {host}"
    return match.group(1)


class ReferencesTest(unittest.TestCase):
    def test_every_reference_path_in_skill_md_exists(self):
        text = _skill_md()
        paths = set(re.findall(r"((?:references|assets)/[\w./-]+)", text))
        self.assertTrue(paths, "SKILL.md names no reference")
        for path in sorted(paths):
            path = path.rstrip(".,;:)")
            if path.startswith("references/") and not path.endswith(".md"):
                continue
            self.assertTrue((SKILL / path).exists(), f"SKILL.md names {path}, which does not exist")

    def test_core_references_exist(self):
        for name in ("checklist", "rubric", "schema", "workers", "verification-rules"):
            self.assertTrue((REFS / f"{name}.md").is_file(), f"references/{name}.md is missing")

    def test_every_ia_command_in_skill_md_exists(self):
        text = _skill_md()
        commands = set(re.findall(r"ia\.py ([a-z][a-z-]*)", text))
        self.assertTrue(commands, "SKILL.md names no ia command")
        registered = {name for name, _ in cli.COMMANDS}
        for name in sorted(commands):
            self.assertIn(name, registered, f"SKILL.md mentions `ia.py {name}`, which is not a subcommand")
        actions = set(cli.parser()._subparsers._group_actions[0].choices["finding"]._subparsers
                      ._group_actions[0].choices)
        used = set(re.findall(r"ia\.py finding ([a-z][a-z-]*)", text))
        self.assertTrue(used, "SKILL.md names no finding action")
        for action in sorted(used):
            self.assertIn(action, actions, f"SKILL.md mentions `ia.py finding {action}`, which is not an action")

    def test_skill_md_is_at_most_400_lines(self):
        self.assertLessEqual(len(_skill_md().splitlines()), 400)

    def test_skill_md_names_every_pass(self):
        text = _skill_md()
        for name in ("baseline-inventory", "correctness-general", "races-distributed", "security",
                     "supply-chain-container", "red-test-proof", "unit-tests", "e2e-infra", "quality-lenses",
                     "contrast", "verify-high", "owner-prose"):
            self.assertIn(f"references/passes/{name}.md", text)

    def test_workers_md_matches_detect_table(self):
        text = _read(REFS / "workers.md")
        for host, rows in detect.WORKERS.items():
            section = _host_section(text, host)
            for row in rows:
                if row["install"]:  # an empty install means there is nothing to install
                    self.assertIn(row["install"], section, f"[{host}] {row['worker']}: install command missing")
                self.assertIn(row["worker"], section, f"[{host}] worker {row['worker']!r} missing")

    def test_checklist_names_every_step(self):
        text = _read(REFS / "checklist.md")
        for step in run.STEPS:
            self.assertRegex(text, rf"`{re.escape(step)}`", f"checklist.md does not name step {step}")

    def test_rubric_defines_three_levels(self):
        text = _read(REFS / "rubric.md")
        for level in ("High", "Medium", "Low"):
            self.assertRegex(text, rf"\*\*{level}[:*]", f"rubric.md does not define {level}")
        # the same rule the reports print
        for phrase in ("exposes data or credentials to the wrong people", "corrupts data",
                       "breaks a whole feature", "minor information exposure",
                       "robustness, observability or a visible inconsistency without loss"):
            self.assertIn(phrase, text)

    def test_verification_rules_has_eleven_numbered_rules(self):
        text = _read(REFS / "verification-rules.md")
        numbers = [int(n) for n in re.findall(r"^## (\d+)\.", text, re.M)]
        self.assertEqual(numbers, list(range(1, 12)))

    def test_schema_documents_required_fields_and_manifest_keys(self):
        text = _read(REFS / "schema.md")
        for field in ("id", "report", "category", "dimension", "title", "verdict", "severity", "confidence",
                      "source", "what_happens", "evidence", "branch", "sha_test", "tests", "red_reason",
                      "suggestion", "effort", "prod_files", "contrast", "audience", "exclude", "shown"):
            self.assertIn(f"`{field}`", text, f"schema.md does not document {field}")
        for key in ("strengths", "sections", "tests_branch", "plan", "result"):
            self.assertIn(key, text)


if __name__ == "__main__":
    unittest.main()
