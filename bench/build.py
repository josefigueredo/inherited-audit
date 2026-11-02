#!/usr/bin/env python3
"""Build the bench system as a git repo whose HEAD is always the same commit.

    python3 bench/build.py <dir>      <dir> must not exist or be empty; prints the HEAD sha

The tree is bench/seeded/ without caches. Author, committer, dates and message are fixed, and the person's global
and system git config are left out (their hooks, signing and templates would change or refuse the commit), so the
sha matches `sha` in bench/key.json on any machine. This only touches the new repo in <dir>; it is the same
isolation the test fixtures use, not a way around anyone's identity rules for real repos.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

SEEDED = Path(__file__).resolve().parent / "seeded"
SKIP = {"__pycache__", ".DS_Store"}
ENV = {
    "GIT_AUTHOR_NAME": "Shop Team", "GIT_AUTHOR_EMAIL": "shop@example.com",
    "GIT_AUTHOR_DATE": "2026-11-02T12:00:00+00:00",
    "GIT_COMMITTER_NAME": "Shop Team", "GIT_COMMITTER_EMAIL": "shop@example.com",
    "GIT_COMMITTER_DATE": "2026-11-02T12:00:00+00:00",
    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
}


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=True,
                         env={**os.environ, **ENV})
    return out.stdout.strip()


def build(target: Path) -> str:
    target = Path(target)
    if target.exists() and any(target.iterdir()):
        raise SystemExit(f"{target} is not empty")
    target.mkdir(parents=True, exist_ok=True)
    for src in sorted(SEEDED.rglob("*")):
        rel = src.relative_to(SEEDED)
        if any(part in SKIP for part in rel.parts) or src.suffix == ".pyc" or not src.is_file():
            continue
        dst = target / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        os.chmod(dst, 0o644)
    _git(target, "init", "-q", "-b", "main")
    _git(target, "add", "-A")
    _git(target, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "Import the shop backend")
    return _git(target, "rev-parse", "HEAD")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    print(build(Path(sys.argv[1])))
