from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skill"
sys.path.insert(0, str(SKILL))
sys.path.insert(0, str(ROOT / "tests"))

_TEMP = []

GIT_ENV = {
    "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com", "GIT_AUTHOR_DATE": "2026-10-18T12:00:00+00:00",
    "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.com", "GIT_COMMITTER_DATE": "2026-10-18T12:00:00+00:00",
    # Hermetic: the person's global and system config (core.hooksPath, commit.gpgsign, init templates) never reach
    # the fixture repos, so the suite gives the same result on a developer machine as in CI.
    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
}


def make_dir() -> Path:
    tmp = tempfile.TemporaryDirectory()
    _TEMP.append(tmp)
    return Path(tmp.name)


def run_cli(args: List[str], cwd: "Path | None" = None) -> subprocess.CompletedProcess:
    """Runs skill/ia.py as a user would."""
    return subprocess.run([sys.executable, str(SKILL / "ia.py"), *args], capture_output=True, text=True,
                          cwd=str(cwd) if cwd else None)


def write_tree(root: Path, files: Dict[str, "str | bytes"]) -> Path:
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
    return root


def git(repo: Path, *args: str) -> str:
    out = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=True,
                         env={**os.environ, **GIT_ENV})
    return out.stdout.strip()


def make_git_repo(files: Dict[str, "str | bytes"], remote: Optional[str] = None,
                  parent: "Path | None" = None) -> Tuple[Path, str]:
    """A committed repo (fixed author and date) in a temp dir, or in `parent` if given; returns its path and the HEAD sha."""
    if parent is not None:
        parent.mkdir(parents=True, exist_ok=True)
    repo = write_tree(parent if parent is not None else make_dir(), files)
    git(repo, "init", "-q", "-b", "main")
    if remote:
        git(repo, "remote", "add", "origin", remote)
    git(repo, "add", "-A")
    git(repo, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "init")
    return repo, git(repo, "rev-parse", "HEAD")
