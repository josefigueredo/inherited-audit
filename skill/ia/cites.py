"""Citation check: every evidence cite must resolve at the pinned base SHA, not in the worktree."""
from __future__ import annotations

import re
import subprocess
from typing import Dict, List, Optional, Tuple, Union
from urllib.parse import urlparse

from .run import ToolError


COMMIT_SUFFIX = re.compile(r"^(.+)@([0-9a-fA-F]{7,40})$")


def parse_cite(cite: str, with_commit: bool = True) -> Tuple:
    """`ALIAS/path[@commit]` -> (alias, path, commit or None); with `with_commit=False` -> (alias, path), the commit
    suffix dropped (for callers that only need the alias or the path)."""
    alias, sep, rest = cite.partition("/")
    if not sep or not alias or not rest:
        raise ValueError(f"not ALIAS/path: {cite!r}")
    m = COMMIT_SUFFIX.match(rest)
    path, commit = (m.group(1), m.group(2)) if m else (rest, None)
    return (alias, path, commit) if with_commit else (alias, path)


def strip_commit(cite: str) -> str:
    """`ALIAS/path@commit` -> `ALIAS/path`; anything else unchanged."""
    alias, sep, rest = cite.partition("/")
    m = COMMIT_SUFFIX.match(rest) if sep else None
    return f"{alias}/{m.group(1)}" if m else cite


def at_commit(repo: dict, commit: Optional[str]) -> dict:
    """The repo entry read at `commit` instead of the pinned sha (unchanged when there is no commit)."""
    return {**repo, "sha": commit} if commit else repo


def _repo_path(repo: dict, path: str) -> str:
    return f"{repo['subdir'].strip('/')}/{path}" if repo.get("subdir") else path


def _git(repo: dict, *args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["git", "-C", repo["path"], *args], capture_output=True, stdin=subprocess.DEVNULL)
    except (OSError, ValueError) as exc:
        raise ToolError(f"git is not available: {exc}")


def _blob(repo: dict, path: str) -> Union[str, None]:
    """Raw text of the object at the pinned sha, or None when git cannot read it as a blob."""
    result = _git(repo, "cat-file", "blob", f"{repo['sha']}:{_repo_path(repo, path)}")
    if result.returncode != 0:
        return None
    return result.stdout.decode("utf-8", errors="replace")


def _kind(repo: dict, path: str) -> Optional[str]:
    kind = _git(repo, "cat-file", "-t", f"{repo['sha']}:{_repo_path(repo, path)}")
    return kind.stdout.decode().strip() if kind.returncode == 0 else None


def blob_text(repo: dict, path: str) -> Optional[str]:
    """Text of `path` (relative to the repo's subdir) at the pinned sha, never the worktree; None if not a file there."""
    if _kind(repo, path) != "blob":
        return None
    return _blob(repo, path)


def _line_count(repo: dict, path: str) -> Union[int, str, None]:
    """Lines of the file at the pinned sha; None when absent there, "dir" when it is not a blob."""
    kind = _kind(repo, path)
    if kind is None:
        return None
    if kind != "blob":
        return "dir"
    text = _blob(repo, path)
    return None if text is None else len(text.splitlines())


def commit_problem(repo: dict, commit: str) -> Optional[str]:
    """Why `commit` cannot back a history cite of `repo`, or None when it is an ancestor of (or equal to) the base."""
    found = _git(repo, "rev-parse", "--verify", "--quiet", f"{commit}^{{commit}}")
    if found.returncode != 0:
        return f"commit {commit[:7]} not found"
    full = found.stdout.decode().strip()
    if _git(repo, "merge-base", "--is-ancestor", full, repo["sha"]).returncode != 0:
        return f"commit {commit[:7]} is not an ancestor of or equal to the base {repo['sha'][:7]}"
    return None


def resolve_commit(repo: dict, commit: str) -> str:
    """Full sha of an (abbreviated) commit; the input when git cannot resolve it."""
    found = _git(repo, "rev-parse", "--verify", "--quiet", f"{commit}^{{commit}}")
    return found.stdout.decode().strip() if found.returncode == 0 else commit


def check_cites(manifest: dict, findings: List[dict]) -> List[str]:
    repos: Dict[str, dict] = {r["alias"]: r for r in manifest["repos"]}
    counts: Dict[Tuple[str, str, Optional[str]], Union[int, str, None]] = {}
    commits: Dict[Tuple[str, str], Optional[str]] = {}
    problems: List[str] = []
    for f in findings:
        for ev in f.get("evidence") or []:
            if not isinstance(ev, dict):
                problems.append(f"{f.get('id')}: evidence entry is not an object")
                continue
            cite, start, end = ev.get("cite"), ev.get("from"), ev.get("to")
            where = f"{f.get('id')}: {cite}"
            try:
                alias, path, commit = parse_cite(cite if isinstance(cite, str) else "")
            except ValueError:
                problems.append(f"{where}: not ALIAS/path")
                continue
            ints = all(isinstance(n, int) and not isinstance(n, bool) for n in (start, end))
            if not ints:
                problems.append(f"{where}: from/to must be integers")
                continue
            where = f"{where}:{start}-{end}"
            if alias not in repos:
                problems.append(f"{where}: unknown alias")
                continue
            if start < 1:
                problems.append(f"{where}: from must be >= 1")
                continue
            if start > end:
                problems.append(f"{where}: from > to")
                continue
            repo = repos[alias]
            if commit:
                if (alias, commit) not in commits:
                    commits[(alias, commit)] = commit_problem(repo, commit)
                if commits[(alias, commit)]:
                    problems.append(f"{where}: {commits[(alias, commit)]}")
                    continue
            key = (alias, path, commit)
            at = at_commit(repo, commit)
            if key not in counts:
                counts[key] = _line_count(at, path)
            total = counts[key]
            if total == "dir":
                problems.append(f"{where}: path is a directory at {at['sha'][:7]}")
            elif total is None:
                problems.append(f"{where}: path not found at {at['sha'][:7]}")
            elif end > total:
                problems.append(f"{where}: range past end of file ({total} lines)")
    return problems


def link_for(repo: dict, path: str, start: int, end: int, commit: Optional[str] = None) -> Optional[str]:
    """Blob URL pinned to the sha (GitHub style; GitLab style when the host says gitlab), or None without remote."""
    remote = re.sub(r"^(https?://)[^/@]*@", r"\1", repo.get("remote") or "")
    if not remote:
        return None
    host = urlparse(remote).hostname or ""
    blob = "/-/blob/" if "gitlab" in host.lower() else "/blob/"
    anchor = f"#L{start}" if start == end else f"#L{start}-L{end}"
    sha = resolve_commit(repo, commit) if commit else repo["sha"]
    return f"{remote}{blob}{sha}/{_repo_path(repo, path)}{anchor}"
