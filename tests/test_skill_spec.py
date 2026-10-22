"""SKILL.md follows the Agent Skills format and names what ia really has."""
from __future__ import annotations

import argparse
import re
import unittest

from helpers import SKILL
from ia import cli
from skillspec import check_skill

SKILL_MD = (SKILL / "SKILL.md").read_text(encoding="utf-8")


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

    def test_exit_codes_in_skill_match_cli(self):
        self.assertIn("0 ok, 1 the command found problems, 2 usage error, 3 an external tool failed or is missing, "
                      "4 ia itself failed", SKILL_MD)
        self.assertEqual((cli.OK, cli.FINDINGS, cli.USAGE, cli.FAILED, cli.INTERNAL), (0, 1, 2, 3, 4))


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
