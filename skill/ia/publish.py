"""Optional publish preparation: issue and PR bodies plus the exact gh commands. Nothing is ever run.

`publish/commands.sh` is meant to run as prepared once the person reviews it: `set -eu`, absolute paths, `--repo` on
every gh command, issues first (their numbers captured into shell variables) and PR bodies completed at run time with
those numbers. Every PR is a draft that references its issues (`Refs #N.`) and never closes them: the branch holds only
the failing test. Pushing stays a commented line for the person to uncomment.
"""
from __future__ import annotations

import re
import shlex
import subprocess
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import findings as findingsmod
from . import hygiene as hygienemod
from . import run as runmod
from .cites import parse_cite
from .run import RunError, UsageError

REMINDER = ("Reminder: publishing on another team's repository is what the filter tries to avoid; "
            "review publish/ before running anything.")
MAX_PER_PR = 5
HEADER = "# Prepared by inherited-audit. Review before running. Nothing here has been executed."
BASE_BRANCH = "main"
DRAFT_NOTE = ("This branch only adds a failing test that reproduces the issue; it is meant to fail until a fix "
              "lands.")
# Labels as auditing-repos applies them: from report and dimension, plus ci for workflow findings.
LABELS = {("correctness", "bug"): ("bug",), ("correctness", "race"): ("bug",),
          ("correctness", "distributed"): ("bug", "resilience"), ("correctness", "security"): ("security",),
          ("correctness", "container"): ("security",), ("correctness", "supply-chain"): ("security", "supply-chain"),
          ("quality", "architecture"): ("architecture",), ("quality", "code"): ("clean-code",),
          ("quality", "docs"): ("documentation",), ("quality", "resilience"): ("resilience",),
          ("quality", "tests"): ("testing",)}
LABEL_ORDER = ("bug", "security", "supply-chain", "resilience", "architecture", "clean-code", "testing", "ci",
               "documentation")
LABEL_DEFS = {"bug": ("d73a4a", "Something isn't working"),
              "security": ("b60205", "Security or hardening concern"),
              "supply-chain": ("5319e7", "Dependency, lock, or build provenance"),
              "resilience": ("0e8a16", "Operational robustness in production"),
              "architecture": ("1d76db", "Structural or design shape"),
              "clean-code": ("0075ca", "Clean code and refactoring"),
              "testing": ("fbca04", "Tests, coverage, or quality gates"),
              "ci": ("c2e0c6", "Continuous integration and workflows"),
              "documentation": ("0075ca", "Improvements or additions to documentation")}
CONVENTIONAL = re.compile(r"^(feat|fix|test|docs|refactor|perf|build|ci|chore|style|revert)(\([\w./-]+\))?!?: \S")
# commitlint config-conventional header-max-length: a squash merge turns the PR title into the commit header.
MAX_TITLE = 100
_REMOTE = re.compile(r"^https?://(?:[^/@]*@)?([^/@]+)/([^/]+)/([^/]+?)(?:\.git)?/?$")


def gh_repo(remote: str) -> Optional[str]:
    """`owner/name` for a github.com remote, `host/owner/name` for another host, None for anything else."""
    m = _REMOTE.match(remote or "")
    if not m:
        return None
    host, owner, name = m.groups()
    return f"{owner}/{name}" if host.lower() == "github.com" else f"{host}/{owner}/{name}"


def has_userinfo(remote: str) -> bool:
    """True when the remote URL embeds credentials (`https://user:token@host/...`; `ssh://git@host` is not one)."""
    return hygienemod.has_credentials(remote)


def _cited(f: dict) -> List[str]:
    """The alias of every parseable cite, in evidence order."""
    out = []
    for ev in f.get("evidence") or []:
        if isinstance(ev, dict):
            try:
                out.append(parse_cite(ev.get("cite") or "", with_commit=False)[0])
            except ValueError:
                continue
    return out


def route(f: dict, repos: Dict[str, dict]) -> Tuple[str, str]:
    """The alias a finding's issue (and PR) goes to, plus a note for commands.sh ("" when there is nothing to review).

    A finding with a branch goes to the repo of its first cite, which is where its branch lives (the same rule
    merge-check uses): its PR can only reference an issue of its own repo. Without a branch, `publish_repo` wins;
    otherwise the most cited alias, the synthetic ROOT not counting unless it is the only one, ties going to the
    first cited of the tied ones.
    """
    cited = _cited(f)
    explicit = f.get("publish_repo") or ""
    if f.get("branch"):
        alias = cited[0] if cited else ""
        same = explicit == alias or (explicit in repos and alias in repos
                                     and repos[explicit]["path"] == repos[alias]["path"])
        if not explicit or same:
            return alias, ""
        return alias, (f"{f['id']}: publish_repo {explicit} ignored: its branch {f['branch']} is in {alias} (the "
                       "first cite), and the PR can only reference an issue of its own repo")
    if explicit:
        return explicit, ""
    counted = [a for a in cited if not (repos.get(a) or {}).get("root")] or cited
    if not counted:
        return "", ""
    counts = Counter(counted)
    top = max(counts.values())
    alias = next(a for a in counted if counts[a] == top)
    if len(counts) == 1:
        return alias, ""
    ranked = sorted(counts, key=lambda a: (-counts[a], counted.index(a)))
    listed = ", ".join(f"{a} {counts[a]}" for a in ranked)
    return alias, (f"{f['id']}: cites {listed}; goes to {alias} by majority (set publish_repo if the fix belongs to "
                   "another repo)")


def labels(f: dict) -> List[str]:
    """The labels of a finding's issue, in LABEL_ORDER."""
    out = set(LABELS.get((f.get("report"), f.get("dimension")), ()))
    cites = [str(e.get("cite") or "") for e in f.get("evidence") or [] if isinstance(e, dict)]
    if re.match(r"CI\b", str(f.get("title") or "")) or any(".github/workflows/" in c for c in cites):
        out.add("ci")
    return [name for name in LABEL_ORDER if name in out]


def _pr_labels(group: List[dict]) -> List[str]:
    """Every member's labels plus testing: the branch only adds a test."""
    out = {name for f in group for name in labels(f)} | {"testing"}
    return [name for name in LABEL_ORDER if name in out]


def _label_flag(names: List[str]) -> str:
    return f" --label {shlex.quote(','.join(names))}" if names else ""


def _files(f: dict) -> List[str]:
    paths = [t.get("path") for t in f.get("tests") or [] if isinstance(t, dict) and t.get("path")]
    return sorted(set(paths + [p for p in f.get("prod_files") or [] if p]))


def _keys(f: dict) -> List[Tuple[str, str]]:
    alias = route(f, {})[0]  # only branched findings are grouped: their repo needs no manifest
    return [(alias, p) for p in _files(f)]


def pr_groups(items: List[dict]) -> List[List[dict]]:
    """Confirmed, shown correctness findings with a branch, joined by shared files of one repo, in chunks of 5."""
    cands = [f for f in items if f.get("report") == "correctness" and f.get("verdict") == "confirmed"
             and f.get("shown") is True and f.get("branch")]
    parent = list(range(len(cands)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    owner: Dict[Tuple[str, str], int] = {}
    for i, f in enumerate(cands):
        for key in _keys(f):
            if key in owner:
                parent[find(i)] = find(owner[key])
            else:
                owner[key] = i
    buckets: Dict[int, List[dict]] = {}
    for i, f in enumerate(cands):
        buckets.setdefault(find(i), []).append(f)
    groups = []
    for members in buckets.values():
        for start in range(0, len(members), MAX_PER_PR):
            groups.append(members[start:start + MAX_PER_PR])
    return sorted(groups, key=lambda g: findingsmod._id_key(g[0]))


def _title(f: dict) -> str:
    aud = f.get("audience") if isinstance(f.get("audience"), dict) else {}
    return hygienemod.mask_text(str(aud.get("title") or f.get("title") or f["id"]), prose=True)


def _issue_body(f: dict) -> str:
    aud = f.get("audience") if isinstance(f.get("audience"), dict) else {}
    prose = hygienemod.mask_text(str(aud.get("what_happens") or f.get("what_happens") or ""), prose=True)
    lines = [f"# {_title(f)}", "", prose, "", "Evidence:", ""]
    lines += [f"- {e['cite']}" for e in f.get("evidence") or [] if isinstance(e, dict) and e.get("cite")]
    return "\n".join(lines) + "\n"


def cut_title(title: str) -> str:
    """`title` within MAX_TITLE characters, cut at a word boundary with an ellipsis."""
    if len(title) <= MAX_TITLE:
        return title
    return title[:MAX_TITLE - 1].rsplit(" ", 1)[0] + "\u2026"


def _subject(f: dict, repo: Optional[dict]) -> str:
    """The subject of the finding's red-test commit when it is a conventional commit; "" otherwise (read-only git)."""
    sha = f.get("sha_test") or ""
    if not sha or not repo:
        return ""
    try:
        res = subprocess.run(["git", "-C", repo["path"], "log", "-1", "--format=%s", sha], capture_output=True,
                             text=True, errors="replace", stdin=subprocess.DEVNULL)
    except (OSError, ValueError):
        return ""
    subject = res.stdout.strip() if res.returncode == 0 else ""
    return subject if CONVENTIONAL.match(subject) else ""


def _pr_title(group: List[dict], repo: Optional[dict]) -> str:
    """The conventional subject of the first member's red-test commit (`test: <title>` without one); a group keeps
    " (+N more)" only while it fits MAX_TITLE."""
    subject = _subject(group[0], repo)
    title = hygienemod.mask_text(subject, prose=True) if subject else f"test: {_title(group[0])}"
    more = f" (+{len(group) - 1} more)" if len(group) > 1 else ""
    return title + more if more and len(title) + len(more) <= MAX_TITLE else cut_title(title)


def _proposal(f: dict) -> str:
    aud = f.get("audience") if isinstance(f.get("audience"), dict) else {}
    return " ".join(hygienemod.mask_text(str(aud.get("fix_summary") or f.get("fix_summary") or ""), prose=True).split())


def _pr_static_body(group: List[dict], shared: List[str]) -> str:
    """The part of a PR body known now; commands.sh prepends DRAFT_NOTE and the `Refs #N.` lines at run time."""
    lines = ["Findings: " + ", ".join(f["id"] for f in group) + ".", "", "Shared files with sibling PRs:", ""]
    lines += [f"- {p}" for p in shared] if shared else ["none"]
    proposals = [(f["id"], _proposal(f)) for f in group]
    proposals = [(fid, text) for fid, text in proposals if text]
    if proposals:
        lines += ["", "Proposed fix (the branch holds only the failing test):", ""]
        lines += [f"- {fid}: {text}" for fid, text in proposals]
    return "\n".join(lines) + "\n"


def _var(fid: str) -> str:
    return "I_" + re.sub(r"[^A-Za-z0-9]", "_", fid)


def _comment(text: str) -> str:
    return "# " + " ".join(str(text).split())


def _issue_lines(f: dict, repo: Optional[dict], body: Path) -> Tuple[List[str], bool]:
    target = gh_repo(repo.get("remote", "")) if repo else None
    if not target:
        why = "unknown repo alias" if repo is None else f"{repo['alias']} has no GitHub-style remote"
        return [_comment(f"{f['id']}: skipped, {why}; no issue is created")], False
    q = shlex.quote
    var = _var(f["id"])
    # The assignment carries gh's exit status (set -e stops on a failure); then keep the number after the last '/'.
    return [_comment(f"{f['id']}: {_title(f)}"),
            f"{var}=$(gh issue create --repo {q(target)} --title {q(_title(f))}{_label_flag(labels(f))} "
            f"--body-file {q(str(body))})",
            f"{var}=${{{var}##*/}}",
            f'echo "{f["id"]} -> issue #${{{var}}}"'], True


def _pr_lines(n: int, group: List[dict], repo: Optional[dict], out: Path, created: set) -> List[str]:
    q = shlex.quote
    ids = ", ".join(f["id"] for f in group)
    target = gh_repo(repo.get("remote", "")) if repo else None
    if not target:
        why = "unknown repo alias" if repo is None else f"{repo['alias']} has no GitHub-style remote"
        return [_comment(f"PR {n} ({ids}): skipped, {why}")]
    repo_path = repo["path"]
    lines = [_comment(f"PR {n}: {ids}")]
    if len(group) == 1:
        head = group[0]["branch"]
    else:
        head = f"audit/pr-{n}"
        wt = out / f"wt-pr-{n}"
        lines += [_comment(f"group branch {head}: {group[0]['branch']} plus a --no-ff merge of every other member, "
                           "in a throwaway worktree so your checkout is not touched"),
                  f"git -C {q(repo_path)} branch {q(head)} {q(group[0]['branch'])}",
                  f"git -C {q(repo_path)} worktree add {q(str(wt))} {q(head)}"]
        lines += [f"git -C {q(str(wt))} merge --no-ff --no-edit {q(f['branch'])}" for f in group[1:]]
        lines.append(f"git -C {q(repo_path)} worktree remove {q(str(wt))}")
    lines += [_comment("push it yourself when you are sure (uncomment the next line):"),
              f"# git -C {q(repo_path)} push -u origin {q(head)}"]
    final = out / f"pr-{n}.body.md"
    refs = [f"Refs #${{{_var(f['id'])}}}." for f in group if f["id"] in created]
    # unquoted heredoc: only the ${I_...} issue numbers expand; DRAFT_NOTE holds no shell syntax
    lines += [f"cat > {q(str(final))} <<IA_BODY", DRAFT_NOTE, ""]
    lines += refs + ([""] if refs else [])
    lines.append("IA_BODY")
    lines.append(f"cat {q(str(out / f'pr-{n}.md'))} >> {q(str(final))}")
    lines.append(_comment(f"a draft: the branch only adds the failing test; replace {BASE_BRANCH} with the repo's "
                          "default branch if it differs"))
    lines.append(f"gh pr create --draft --repo {q(target)} --head {q(head)} --base {BASE_BRANCH} "
                 f"--title {q(_pr_title(group, repo))}{_label_flag(_pr_labels(group))} --body-file {q(str(final))}")
    return lines


def _label_lines(used: Dict[str, List[str]]) -> List[str]:
    """One `gh label create` per label and target repo, before any issue: a label missing halfway would stop the
    script after some issues exist, and running it again duplicates them. `|| true` keeps a label the repo already has;
    no --force, so the team's colors stay."""
    if not used:
        return []
    q = shlex.quote
    lines = [_comment("Labels first, each one this file uses, per repo; one that already exists is left as it is.")]
    for target, names in used.items():
        for name in [n for n in LABEL_ORDER if n in names]:
            color, desc = LABEL_DEFS[name]
            lines.append(f"gh label create {q(name)} --repo {q(target)} --color {color} --description {q(desc)} "
                         "|| true")
    return lines + [""]


def prepare_publish(run: Path) -> Path:
    run = Path(run).resolve()
    manifest = runmod.load(run)
    if not (manifest.get("options") or {}).get("publish"):
        raise UsageError("publishing was not enabled for this run; run `ia init` with --publish to prepare issue "
                         "and PR bodies")
    if not isinstance(manifest.get("filter"), dict):
        raise RunError(f"the run has not been filtered; run `ia.py filter --run {run}` first")
    repos = {r["alias"]: r for r in manifest["repos"]}
    items = findingsmod.load_all(run)
    shown = [f for f in items if f.get("shown") is True]
    out = run / "publish"
    out.mkdir(exist_ok=True)
    cmds = ["#!/bin/sh", "set -eu", HEADER,
            "# Before running: push every PR head branch (uncomment the push lines below, or push them yourself).",
            "# A PR needs its head branch on the remote; otherwise the script stops at the first PR after the",
            "# issues already exist, and running it again creates them twice.",
            "# Issues first: each number is captured so each draft PR body can reference it with Refs #N.", ""]
    flagged: Dict[str, List[str]] = {}
    for r in manifest["repos"]:
        if r.get("remote_had_credentials") or has_userinfo(r.get("remote", "")):
            flagged.setdefault(r["path"], []).append(r["alias"])
    for aliases in flagged.values():
        cmds += [_comment(f"WARNING: the remote of {', '.join(aliases)} carries credentials; they were dropped here and "
                          "never copied into this file. Rotate that credential and remove it from the remote URL."), ""]
    created: set = set()
    used: Dict[str, List[str]] = {}

    def use(repo: Optional[dict], names: List[str]) -> None:
        target = gh_repo(repo.get("remote", "")) if repo else None
        if target:
            used.setdefault(target, [])
            used[target] += [n for n in names if n not in used[target]]

    body_cmds: List[str] = []
    for f in shown:
        body = out / f"issue-{f['id']}.md"
        body.write_text(_issue_body(f), encoding="utf-8")
        alias, note = route(f, repos)
        lines, ok = _issue_lines(f, repos.get(alias), body)
        body_cmds += ([_comment(note)] if note else []) + lines
        if ok:
            created.add(f["id"])
            use(repos.get(alias), labels(f))
    groups = pr_groups(items)
    keys_of = [{k for f in g for k in _keys(f)} for g in groups]
    for n, group in enumerate(groups, 1):
        others = set().union(*[s for i, s in enumerate(keys_of) if i != n - 1]) if len(groups) > 1 else set()
        shared = sorted(p for _, p in keys_of[n - 1] & others)
        (out / f"pr-{n}.md").write_text(_pr_static_body(group, shared), encoding="utf-8")
        repo = repos.get(route(group[0], repos)[0])
        body_cmds.append("")
        body_cmds += _pr_lines(n, group, repo, out, created)
        use(repo, _pr_labels(group))
    cmds += _label_lines(used) + body_cmds
    (out / "commands.sh").write_text("\n".join(cmds) + "\n", encoding="utf-8")
    return out
