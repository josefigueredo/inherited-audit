"""The pass prompts and the optional agent definitions: shape, mandatory topics, and nothing system-specific leaks."""
from __future__ import annotations

import os
import re
import unittest
from pathlib import Path
from typing import Dict

from helpers import ROOT, SKILL

PASSES = SKILL / "references" / "passes"
AGENTS = ROOT / "agents"
NAMES = ("baseline-inventory", "correctness-general", "races-distributed", "security", "supply-chain-container",
         "red-test-proof", "unit-tests", "e2e-infra", "quality-lenses", "contrast", "verify-high", "owner-prose")
SECTIONS = ("Scope", "Out of scope", "Inputs", "Method", "Evidence rules", "Output", "Done when")
# Generic markers only. Names of an audited system live outside the repo: IA_LEAK_TERMS points to a file with one
# regex per line (blank lines and `#` comments ignored), so the guard itself never names the system it protects.
LEAKS = {
    "Ref.": re.compile(r"\bRef\."),
    "sanitiz": re.compile(r"(?i)sanitiz"),
}


def _leak_patterns() -> Dict[str, "re.Pattern[str]"]:
    patterns = dict(LEAKS)
    terms = os.environ.get("IA_LEAK_TERMS")
    if terms:
        for line in Path(terms).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                patterns[line] = re.compile(line)
    return patterns


def _pass(name: str) -> str:
    path = PASSES / f"{name}.md"
    assert path.is_file(), f"references/passes/{name}.md is missing"
    return path.read_text(encoding="utf-8")


def _frontmatter(path: Path) -> Dict[str, str]:
    assert path.is_file(), f"{path.relative_to(ROOT)} is missing"
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert match, f"{path.relative_to(ROOT)} has no frontmatter"
    fields = {}
    for line in match.group(1).splitlines():
        if ":" in line and not line.startswith((" ", "\t")):
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip().strip("'\"")
    return fields


class PassesTest(unittest.TestCase):
    def test_every_pass_has_required_sections(self):
        for name in NAMES:
            text = _pass(name)
            for section in SECTIONS:
                self.assertRegex(text, rf"(?m)^## {re.escape(section)}$", f"{name}.md has no `## {section}`")

    def test_races_pass_covers_mandatory_topics(self):
        text = _pass("races-distributed").lower()
        for topic in ("lock", "transaction", "idempoten", "replica", "in-memory", "worker", "queue", "retry",
                      "timeout", "cancel"):
            self.assertIn(topic, text, f"races-distributed.md does not cover {topic!r}")
        self.assertTrue("boot" in text or "startup" in text, "races-distributed.md does not cover boot/startup")

    def test_e2e_pass_requires_control_routes_and_disposable_db(self):
        text = _pass("e2e-infra")
        for needle in ("/__rules", "/__faults", "/__requests", "docker compose"):
            self.assertIn(needle, text, f"e2e-infra.md does not require {needle!r}")
        self.assertTrue("disposable" in text or "per-run database" in text,
                        "e2e-infra.md does not require a disposable or per-run database")

    def test_red_test_pass_lists_invalid_reds(self):
        text = _pass("red-test-proof").lower()
        for needle in ("import", "setup", "mock", "never bend a test"):
            self.assertIn(needle, text, f"red-test-proof.md does not mention {needle!r}")

    def test_owner_prose_bans_jargon_and_requires_inference_labels(self):
        text = _pass("owner-prose").lower()
        for needle in ("forbidden", "jargon", "blame", "inference", "exploit", "lang"):
            self.assertIn(needle, text, f"owner-prose.md does not mention {needle!r}")
        self.assertRegex(text, r"rg -n", "owner-prose.md has no runnable forbidden-terms check")

    def test_owner_prose_covers_every_rendered_prose_field(self):
        text = _pass("owner-prose")
        for field in ("audience.title", "audience.what_happens", "audience.fix_summary", "red_reason",
                      "tests[].note", "evidence[].note"):
            self.assertIn(field, text, f"owner-prose.md does not cover {field}")
        self.assertIn("red for the right reason", text.lower())
        self.assertNotRegex(text, r"\|baseline\||\|worker\|", "forbidden terms must be audit phrases, not domain words")

    def test_examples_do_not_echo_the_reference_system(self):
        races = _pass("races-distributed").lower()
        self.assertNotIn("owner", races)
        self.assertNotIn("members", races)
        lenses = _pass("quality-lenses").lower()
        self.assertNotIn("chat", lenses)
        self.assertNotIn("3800", lenses)

    def test_red_test_pass_skips_non_code_dimensions_and_typechecks(self):
        text = _pass("red-test-proof")
        self.assertIn("supply-chain", text)
        self.assertIn("container", text)
        self.assertNotIn("hand them back untouched", text)
        self.assertIn("tsc --noEmit", text)
        self.assertIn("merge --no-ff", text)

    def test_no_system_specifics_leak(self):
        roots = [SKILL, AGENTS]
        patterns = _leak_patterns()
        scanned = 0
        for root in roots:
            self.assertTrue(root.is_dir(), f"{root.relative_to(ROOT)} is missing")
            for path in sorted(root.rglob("*")):
                if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
                    continue
                try:
                    text = path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    continue
                scanned += 1
                for label, pattern in patterns.items():
                    hit = pattern.search(text)
                    self.assertIsNone(hit, f"{path.relative_to(ROOT)} contains {label!r}: "
                                           f"{text[max(0, hit.start() - 30):hit.end() + 30]!r}" if hit else "")
        self.assertGreater(scanned, 0)

    def test_every_pass_referenced_from_skill_md(self):
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        named = set(re.findall(r"references/passes/([\w-]+)\.md", text))
        for name in NAMES:
            self.assertIn(name, named, f"SKILL.md does not name references/passes/{name}.md")
        for name in sorted(named):
            self.assertTrue((PASSES / f"{name}.md").is_file(), f"SKILL.md names passes/{name}.md, which is missing")
        on_disk = {p.stem for p in PASSES.glob("*.md")} if PASSES.is_dir() else set()
        self.assertEqual(on_disk - named, set(), "pass files that SKILL.md never names")

    def test_every_pass_path_under_skill_exists(self):
        for path in sorted(SKILL.rglob("*.md")):
            for name in re.findall(r"references/passes/([\w-]+)\.md", path.read_text(encoding="utf-8")):
                self.assertTrue((PASSES / f"{name}.md").is_file(),
                                f"{path.relative_to(ROOT)} names passes/{name}.md, which is missing")

    def test_agent_definitions_frontmatter(self):
        claude = _frontmatter(AGENTS / "claude" / "ia-auditor.md")
        self.assertEqual(claude.get("name"), "ia-auditor")
        self.assertTrue(claude.get("description"))
        self.assertIn(claude.get("model"), {"opus", "inherit"})
        cursor = _frontmatter(AGENTS / "cursor" / "ia-auditor.md")
        self.assertEqual(cursor.get("name"), "ia-auditor")
        self.assertTrue(cursor.get("description"))
        self.assertEqual(cursor.get("readonly"), "true")
        self.assertEqual(cursor.get("model"), "inherit")


class ContrastScopeTextTest(unittest.TestCase):
    def test_contrast_pass_asks_for_scope(self):
        text = _pass("contrast")
        for token in ("contrast.scope=severity", "contrast.scope=finding", "contrast.rebutted"):
            self.assertIn(token, text)

    def test_skill_and_schema_explain_scope_and_rebuttal(self):
        skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        schema = (SKILL / "references" / "schema.md").read_text(encoding="utf-8")
        for text in (skill, schema):
            for token in ("scope", "rebutted"):
                self.assertIn(token, text)
        self.assertIn("author_model", schema)
        self.assertIn("author_model", skill)


QUALITY_REGEXES = ("useState[<(]", r": any\b", "as Record<string, unknown>", r"\.message\.includes",
                   r"\.slice\(0, \d+\)", 'role="dialog"', "<button", "<Button", r"console\.log", "'use client'",
                   r"process\.env")


class PassUpgradesTest(unittest.TestCase):
    """Iteration 2: race topics by module, real-library proofs, measurement regexes, the no-subagent path."""

    def test_races_delivers_a_topic_by_module_table(self):
        text = _pass("races-distributed")
        self.assertRegex(text, r"(?i)topic × module")
        self.assertRegex(text, r"\| *Topic *\|")
        self.assertIn("--pass races-distributed --module", text)
        self.assertIn("--topics 1,2,3,4,5,6,7,8,9,10", text)
        self.assertRegex(text, r"--result found\|nothing|--result nothing|--result found")

    def test_races_gives_a_starting_search_per_topic(self):
        text = _pass("races-distributed")
        block = text.split("### Starting searches")[1].split("\n## ")[0]
        topics = re.findall(r"(?m)^- \*\*Topic (\d+)\b", block)
        self.assertEqual(topics, [str(n) for n in range(1, 11)], "one starting search per topic, 1 to 10, in order")
        for needle in ("new (Map|Set|CircuitBreaker|LRU)", "catch", "jobId", "CREATE TABLE|ALTER TABLE",
                       "count\\(|COUNT\\(", "migration"):
            self.assertIn(needle, block, f"starting searches do not include {needle!r}")

    def test_races_topic_three_catches_decorator_style_reruns(self):
        block = _pass("races-distributed").split("- **Topic 3**")[1].split("- **Topic 4**")[0]
        self.assertIn(r"(\.(apply|call))?\(", block, "topic 3 misses `original.apply(...)` / `.call(...)` reruns")
        self.assertIn("descriptor.value", block)
        self.assertIn("method", block)

    def test_races_coverage_and_search_clarifications(self):
        text = _pass("races-distributed")
        self.assertIn("replaces the whole cell", text)
        self.assertIn("registers it", text)
        self.assertIn("rg -n -i 'Date", text)
        for folder in ("drizzle/", "alembic/", "prisma/migrations"):
            self.assertIn(folder, text)

    def test_never_mock_the_suspect_library(self):
        for name in ("red-test-proof", "races-distributed"):
            text = _pass(name).lower()
            self.assertIn("never mock the suspect library", text, f"{name}.md lacks the never-mock rule")
            self.assertIn("in-memory server", text)
            self.assertIn("closed port", text)

    def test_red_test_proof_typechecks_commit_one_and_handles_no_runner(self):
        text = _pass("red-test-proof")
        self.assertIn("commit 1", text)
        self.assertRegex(text, r"(?i)type-check[^.]*commit 1|commit 1[^.]*type-check")
        self.assertIn("tests[].note", text)
        self.assertRegex(text, r"(?i)no test runner")
        self.assertRegex(text, r"(?i)minimal runner config")
        self.assertRegex(text, r"(?i)never break the build")

    def test_unit_tests_handles_no_runner(self):
        text = _pass("unit-tests")
        self.assertRegex(text, r"(?i)no test runner")
        self.assertRegex(text, r"(?i)never break the build")

    def test_quality_lenses_has_the_measurement_regex_table(self):
        text = _pass("quality-lenses")
        for regex in QUALITY_REGEXES:
            self.assertIn(f"`{regex}", text, f"quality-lenses.md has no measurement regex {regex!r}")
        self.assertIn("outside `ui/`", text)
        self.assertRegex(text, r"(?i)cites the regex")
        self.assertIn("up to 12 per lens", text)
        self.assertNotIn("8 to 12", text)

    def test_host_modes_has_the_no_subagent_path(self):
        skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertRegex(skill, r"(?m)^## No subagents on this host$")
        text = (SKILL / "references" / "host-modes.md").read_text(encoding="utf-8")
        self.assertRegex(text, r"(?m)^## No subagents on this host$")
        section = text.split("## No subagents on this host")[1].split("\n## ")[0].lower()
        for needle in ("sequentially", "module by module", "coverage status", "read-only cli", "different model",
                       "orchestrator", "rerun", "contrast", "family"):
            self.assertIn(needle, section, f"the no-subagent section does not mention {needle!r}")

    def test_verify_high_and_checklist_know_the_no_subagent_path(self):
        verify = _pass("verify-high").lower()
        self.assertIn("no subagents", verify)
        self.assertIn("read-only cli", verify)
        self.assertIn("rerun by the orchestrator", verify)
        checklist = (SKILL / "references" / "checklist.md").read_text(encoding="utf-8").lower()
        self.assertIn("read-only cli", checklist)
        self.assertIn("never mock the suspect library", checklist)


if __name__ == "__main__":
    unittest.main()
