"""SKILL.md follows the Agent Skills format and names what ia really has."""
from __future__ import annotations

import argparse
import re
import unittest

from helpers import SKILL
from ia import cli
from skillspec import check_skill

SKILL_MD = (SKILL / "SKILL.md").read_text(encoding="utf-8")
FIX_SKILL = SKILL.parent / "fix-skill"
FIX_MD = "\n".join(p.read_text(encoding="utf-8") for p in sorted(FIX_SKILL.rglob("*.md")))


class SkillSpecTest(unittest.TestCase):
    def test_skill_md_conforms_under_its_published_name(self):
        self.assertEqual(check_skill(SKILL, published_name="inherited-audit"), [])

    def test_every_flag_in_the_skill_exists_in_the_cli(self):
        options = set()

        def collect(parser):
            for a in parser._actions:
                options.update(a.option_strings)
                for sub in (a.choices.values() if isinstance(a, argparse._SubParsersAction) else ()):
                    collect(sub)  # nested actions such as `coverage add` count too

        collect(cli.parser())
        for flag in set(re.findall(r"(--[a-z][a-z-]+)", SKILL_MD)):
            self.assertIn(flag, options, f"SKILL.md mentions {flag}, which no ia command has")

    def test_fix_skill_conforms_and_names_only_real_flags_and_actions(self):
        self.assertEqual(check_skill(FIX_SKILL, published_name="inherited-fix"), [])
        self.assertLess(len((FIX_SKILL / "SKILL.md").read_text(encoding="utf-8").splitlines()), 250)
        fix = next(a for a in cli.parser()._actions if isinstance(a, argparse._SubParsersAction)).choices["fix"]
        options, actions = set(), set()
        for a in fix._actions:
            for name, sub in (a.choices.items() if isinstance(a, argparse._SubParsersAction) else ()):
                actions.add(name)
                for b in sub._actions:
                    options.update(b.option_strings)
        self.assertEqual(actions, {"plan", "start", "check", "done", "publish"})
        quoted = {"--amend", "--tests"}  # git and gradle flags quoted in fix.md
        for flag in set(re.findall(r"(--[a-z][a-z-]+)", FIX_MD)) - quoted:
            self.assertIn(flag, options, f"fix-skill mentions {flag}, which `ia.py fix` does not have")
        for action in re.findall(r"`fix (\w+)", FIX_MD):
            self.assertIn(action, actions)
        self.assertIn("0 ok, 1 the command found problems, 2 usage error, 3 an external tool failed or is missing, "
                      "4 ia itself failed", FIX_MD.replace("\n", " "))

    def test_exit_codes_in_skill_match_cli(self):
        self.assertIn("0 ok, 1 the command found problems, 2 usage error, 3 an external tool failed or is missing, "
                      "4 ia itself failed", SKILL_MD)
        self.assertEqual((cli.OK, cli.FINDINGS, cli.USAGE, cli.FAILED, cli.INTERNAL), (0, 1, 2, 3, 4))


class SkillShapeTest(unittest.TestCase):
    """SKILL.md stays an instruction sheet: numbered steps in ia's order, no project history, rare paths elsewhere."""

    def test_every_step_has_one_numbered_heading_in_ia_order(self):
        from ia import run as runmod
        headings = re.findall(r"(?m)^### Step ([0-9]+(?:\.[0-9]+|[a-z])?): `([a-z]+)`$", SKILL_MD)
        self.assertEqual([name for _, name in headings], list(runmod.STEPS))
        numbers = [num for num, _ in headings]
        self.assertEqual(len(numbers), len(set(numbers)), f"repeated step numbers: {numbers}")

    def test_no_history_of_the_removed_fix_flag(self):
        for gone in ("old fix flag", "options.fix", "is gone"):
            self.assertNotIn(gone, SKILL_MD)

    def test_rare_host_modes_live_in_a_reference(self):
        modes = (SKILL / "references" / "host-modes.md").read_text(encoding="utf-8")
        self.assertIn("references/host-modes.md", SKILL_MD)
        for needle in ("ia.py finding add", "contrast.same_family", "coverage status", "--force-open"):
            self.assertIn(needle, modes)
        self.assertNotIn("A contrast\nline", SKILL_MD)
        self.assertLess(len(SKILL_MD.splitlines()), 390)  # a ratchet: it was 400 before the host modes moved out


class ScopeDocsTest(unittest.TestCase):
    """The skill is not tied to a frontend plus a backend: any set of repos, with the stacks detect knows named."""

    def read(self, rel: str) -> str:
        return (SKILL.parent / rel).read_text(encoding="utf-8")

    def test_description_is_not_limited_to_frontend_and_backend(self):
        description = SKILL_MD.split("description:", 1)[1].split("\n", 1)[0]
        self.assertNotIn("frontend and backend", description)
        for word in ("services", "CLIs", "libraries", "Java", "Kotlin", "Go"):
            self.assertIn(word, description)

    def test_checklist_names_every_detected_stack(self):
        text = self.read("skill/references/checklist.md")
        for stack in ("TypeScript/JavaScript", "Python", "Java/Kotlin", "Go"):
            self.assertIn(stack, text)

    def test_readme_is_not_limited_to_front_and_back(self):
        self.assertNotIn("(front y back)", self.read("README.md"))

    def test_exit_code_tables_list_4_and_signals(self):
        for rel in ("docs/referencia.md", "docs/instalacion-detallada.md"):
            text = self.read(rel)
            self.assertRegex(text, r"\| 4 \|", rel)
            self.assertIn("128", text, rel)


if __name__ == "__main__":
    unittest.main()
