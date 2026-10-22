"""Branch integration: prove the per-finding finding branches (red tests only) combine, using `git merge-tree` (no worktree touched)."""
from __future__ import annotations

import re
import subprocess
from itertools import combinations
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import findings as findingsmod
from . import run as runmod
from .cites import parse_cite
from .run import RunError, ToolError

MIN_VERSION = (2, 38)


def git_supports_merge_tree(version_text: Optional[str] = None) -> bool:
    """True when git is >= 2.38 (`merge-tree --write-tree`). `version_text` is the `git --version` output, for tests."""
    if version_text is None:
        try:
            version_text = subprocess.run(["git", "--version"], capture_output=True, text=True,
                                          stdin=subprocess.DEVNULL).stdout
        except (OSError, ValueError) as exc:
            raise ToolError(f"git is not available: {exc}")
    m = re.search(r"(\d+)\.(\d+)", version_text)
    return bool(m) and (int(m.group(1)), int(m.group(2))) >= MIN_VERSION


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                              stdin=subprocess.DEVNULL)
    except (OSError, ValueError) as exc:
        raise ToolError(f"git is not available: {exc}")


def branch_exists(repo: Path, branch: str) -> bool:
    return _git(repo, "rev-parse", "--verify", "--quiet", f"{branch}^{{commit}}").returncode == 0


def pairwise(repo: Path, branches: List[str]) -> List[Tuple[str, str, bool, List[str]]]:
    out: List[Tuple[str, str, bool, List[str]]] = []
    for a, b in combinations(branches, 2):
        res = _git(repo, "merge-tree", "--write-tree", "--name-only", a, b)
        if res.returncode == 0:
            out.append((a, b, True, []))
        elif res.returncode == 1:
            lines = res.stdout.splitlines()[1:]  # first line is the tree OID
            paths: List[str] = []
            for line in lines:
                if not line.strip():
                    break
                paths.append(line)
            out.append((a, b, False, paths))
        else:
            raise ToolError(f"git merge-tree {a} {b} failed in {repo}: {res.stderr.strip()}")
    return out


def collect(manifest: dict, found: List[dict]) -> Dict[str, List[str]]:
    """Branches per repo path: confirmed findings' branches (repo = alias of the first cite) plus tests branches."""
    by_alias = {r["alias"]: r["path"] for r in manifest["repos"]}
    groups: Dict[str, List[str]] = {}

    def add(path: str, branch: str) -> None:
        if branch not in groups.setdefault(path, []):
            groups[path].append(branch)

    for f in found:
        branch = f.get("branch")
        evidence = f.get("evidence") or []
        if f.get("verdict") != "confirmed" or not branch or not evidence or not isinstance(evidence[0], dict):
            continue
        try:
            alias, _ = parse_cite(evidence[0].get("cite") or "", with_commit=False)
        except ValueError:
            continue
        if alias in by_alias:
            add(by_alias[alias], branch)
    for alias, path in by_alias.items():
        tb = (manifest.get("baseline") or {}).get(alias, {})
        tb = tb.get("tests_branch") if isinstance(tb, dict) else None
        if isinstance(tb, str) and tb:
            add(path, tb)
    return groups


def check_run(run: Path, version_text: Optional[str] = None) -> Tuple[List[str], bool]:
    """Lines to print and whether everything is fine (no conflicts, no missing branch)."""
    manifest = runmod.load(run)
    if not git_supports_merge_tree(version_text):
        raise ToolError("git >= 2.38 is required for `merge-tree --write-tree`; upgrade git")
    lines: List[str] = []
    ok = True
    for path, names in collect(manifest, findingsmod.load_all(run)).items():
        lines.append(f"repo {path}")
        if len(names) < 2:
            lines.append("  nothing to compare (fewer than 2 branches)")
            continue
        missing = [n for n in names if not branch_exists(Path(path), n)]
        if missing:
            ok = False
            lines += [f"  MISSING branch: {n}" for n in missing]
            continue
        for a, b, clean, paths in pairwise(Path(path), names):
            if clean:
                lines.append(f"  {a}  x  {b}: clean")
            else:
                ok = False
                lines.append(f"  {a}  x  {b}: CONFLICT in {', '.join(paths) or '(unknown paths)'}")
    if not lines:
        lines.append("no confirmed findings with a branch: nothing to compare")
    return lines, ok
