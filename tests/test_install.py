from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path
from typing import List

from helpers import ROOT, make_dir

SCRIPT = ROOT / "install.sh"


def run_install(home: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "HOME": str(home)}
    return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, env=env)


def skill_link(home: Path) -> Path:
    return home / ".claude" / "skills" / "inherited-audit"


class InstallTest(unittest.TestCase):
    def test_links_only_the_skill_folder_into_claude_skills(self) -> None:
        home = make_dir()
        out = run_install(home)
        self.assertEqual(out.returncode, 0, out.stderr)
        link = skill_link(home)
        self.assertTrue(link.is_symlink())
        self.assertEqual(link.resolve(), (ROOT / "skill").resolve())
        self.assertTrue((link / "SKILL.md").is_file())
        for repo_only in ("eval", "docs", "tests", "agents", "install.sh"):
            self.assertFalse((link / repo_only).exists(), repo_only)

    def test_never_touches_agents_skills_nor_agent_folders_by_default(self) -> None:
        home = make_dir()
        self.assertEqual(run_install(home).returncode, 0)
        self.assertFalse((home / ".agents").exists())
        self.assertFalse((home / ".claude" / "agents").exists())
        self.assertFalse((home / ".cursor").exists())

    def test_rerun_is_idempotent(self) -> None:
        home = make_dir()
        self.assertEqual(run_install(home).returncode, 0)
        out = run_install(home)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(skill_link(home).resolve(), (ROOT / "skill").resolve())

    def test_refuses_to_replace_a_real_directory(self) -> None:
        home = make_dir()
        link = skill_link(home)
        link.mkdir(parents=True)
        (link / "mine.txt").write_text("keep", encoding="utf-8")
        out = run_install(home)
        self.assertEqual(out.returncode, 1)
        self.assertIn("refusing", out.stderr)
        self.assertFalse(link.is_symlink())
        self.assertEqual((link / "mine.txt").read_text(encoding="utf-8"), "keep")

    def test_agents_flag_links_both_agent_definitions(self) -> None:
        home = make_dir()
        out = run_install(home, "--agents")
        self.assertEqual(out.returncode, 0, out.stderr)
        pairs: List[tuple] = [
            (home / ".claude" / "agents" / "ia-auditor.md", ROOT / "agents" / "claude" / "ia-auditor.md"),
            (home / ".cursor" / "agents" / "ia-auditor.md", ROOT / "agents" / "cursor" / "ia-auditor.md"),
        ]
        for path, source in pairs:
            self.assertTrue(path.is_symlink(), path)
            self.assertEqual(path.resolve(), source.resolve())
        self.assertEqual(run_install(home, "--agents").returncode, 0)

    def test_agents_flag_refuses_to_replace_a_real_file(self) -> None:
        home = make_dir()
        target = home / ".cursor" / "agents" / "ia-auditor.md"
        target.parent.mkdir(parents=True)
        target.write_text("mine", encoding="utf-8")
        out = run_install(home, "--agents")
        self.assertEqual(out.returncode, 1)
        self.assertFalse(target.is_symlink())
        self.assertEqual(target.read_text(encoding="utf-8"), "mine")

    def test_cursor_flag_links_the_skill_only_into_cursor_skills(self) -> None:
        home = make_dir()
        out = run_install(home, "--cursor")
        self.assertEqual(out.returncode, 0, out.stderr)
        link = home / ".cursor" / "skills" / "inherited-audit"
        self.assertTrue(link.is_symlink())
        self.assertEqual(link.resolve(), (ROOT / "skill").resolve())
        self.assertFalse((home / ".claude").exists())
        self.assertFalse((home / ".agents").exists())
        self.assertIn("skill: %s -> " % link, out.stdout)
        self.assertNotIn("Claude", out.stdout + out.stderr)

    def test_cursor_flag_with_agents_links_only_the_cursor_definition(self) -> None:
        home = make_dir()
        out = run_install(home, "--cursor", "--agents")
        self.assertEqual(out.returncode, 0, out.stderr)
        path = home / ".cursor" / "agents" / "ia-auditor.md"
        self.assertEqual(path.resolve(), (ROOT / "agents" / "cursor" / "ia-auditor.md").resolve())
        self.assertFalse((home / ".claude").exists())
        self.assertIn("agents: ia-auditor linked for Cursor\n", out.stdout)

    def test_cursor_flag_warns_when_claude_skills_also_has_it(self) -> None:
        home = make_dir()
        self.assertEqual(run_install(home).returncode, 0)
        out = run_install(home, "--cursor")
        self.assertEqual(out.returncode, 1)
        self.assertIn("twice", out.stderr)
        self.assertFalse(os.path.lexists(home / ".cursor" / "skills" / "inherited-audit"))
        self.assertTrue(skill_link(home).is_symlink())

    def test_default_warns_when_cursor_skills_also_has_it(self) -> None:
        home = make_dir()
        self.assertEqual(run_install(home, "--cursor").returncode, 0)
        out = run_install(home)
        self.assertEqual(out.returncode, 1)
        self.assertIn("twice", out.stderr)
        self.assertFalse(os.path.lexists(skill_link(home)))

    def test_help_and_unknown_argument(self) -> None:
        home = make_dir()
        out = run_install(home, "-h")
        self.assertEqual(out.returncode, 0)
        self.assertIn("--agents", out.stdout)
        self.assertIn("--cursor", out.stdout)
        self.assertFalse((home / ".claude").exists())
        bad = run_install(home, "--nope")
        self.assertEqual(bad.returncode, 2)
        self.assertIn("unknown argument", bad.stderr)


if __name__ == "__main__":
    unittest.main()
