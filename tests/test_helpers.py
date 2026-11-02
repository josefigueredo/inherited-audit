"""The test helpers build their git repos the same way on every machine, whatever the person's git config says."""
from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest import mock

from helpers import git, make_dir, make_git_repo


def hostile_global_config() -> Path:
    """A global git config whose core.hooksPath rejects every commit, like an identity-checking pre-commit hook."""
    root = make_dir()
    hooks = root / "hooks"
    hooks.mkdir()
    pre_commit = hooks / "pre-commit"
    pre_commit.write_text("#!/bin/sh\necho 'rejected by a global hook' >&2\nexit 1\n", encoding="utf-8")
    pre_commit.chmod(0o755)
    config = root / "gitconfig"
    config.write_text(f"[core]\n\thooksPath = {hooks}\n[commit]\n\tgpgsign = true\n", encoding="utf-8")
    return config


class HermeticGitTest(unittest.TestCase):
    def test_make_git_repo_ignores_a_global_hooks_path(self):
        with mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": str(hostile_global_config())}):
            repo, sha = make_git_repo({"a.txt": "a\n"})
        self.assertRegex(sha, r"^[0-9a-f]{40}$")
        self.assertEqual(git(repo, "log", "-1", "--format=%ae"), "test@example.com")

    def test_git_ignores_the_system_config(self):
        with mock.patch.dict(os.environ, {"GIT_CONFIG_SYSTEM": str(hostile_global_config())}):
            repo, _ = make_git_repo({"a.txt": "a\n"})
            (repo / "b.txt").write_text("b\n", encoding="utf-8")
            git(repo, "add", "-A")
            git(repo, "commit", "-q", "-m", "second")
        self.assertEqual(git(repo, "rev-list", "--count", "HEAD"), "2")


if __name__ == "__main__":
    unittest.main()
