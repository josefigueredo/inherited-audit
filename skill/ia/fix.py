"""inherited-fix mechanics: take a published red-test branch, prove its fix on the PR's merge result and prepare the
commands that turn the draft PR into a fix PR. Nothing is pushed and no PR is touched: `fix/commands.sh` is for the
person.

The unit of work is the PR branch: a single-finding PR is the finding's own branch; a group PR is the `audit/pr-N`
branch whose history holds the finding's red-test commit, and its members are fixed one after another in one worktree.
Everything is proven on a throwaway merge of the PR base into the branch, never only on the audit's pinned base.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import baseline as baselinemod
from . import findings as findingsmod
from . import hygiene as hygienemod
from . import publish as publishmod
from . import run as runmod
from .run import RunError, UsageError

HEADER = "# Prepared by inherited-fix. Review before running. Nothing here has been executed."
SEVERITIES = ("high", "medium", "low")
CLOSED = ("moot", "blocked", "declined", "done")
# A closing keyword followed by an issue reference: the PR body closes the issue, a commit never does (a squash or a
# cherry-pick elsewhere would close it too early). `fix(scope):` is a subject prefix, not a keyword followed by `#N`.
CLOSING = re.compile(r"(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?):?\s+(?:[\w.-]+/[\w.-]+)?#\d+")
TEST_DIRS = {"test", "tests", "__tests__", "spec", "specs", "testing", "androidtest", "testfixtures"}
TEST_STEM = re.compile(r"^(?:test_.+|.+_test|.+Tests?|.+IT|.+\.(?:test|spec))$")
RED_COUNT = re.compile(r"(\d+) of (\d+) fail")
BODY_AWK = Path(__file__).with_name("fix_body.awk")


def _slug(branch: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", branch).strip("-")


def _fix(f: dict) -> dict:
    return f["fix"] if isinstance(f.get("fix"), dict) else {}


def _status(f: dict) -> str:
    return str(_fix(f).get("status") or "")


def _repos(manifest: dict) -> Dict[str, dict]:
    return {r["alias"]: r for r in manifest["repos"]}


def _repo_of(f: dict, repos: Dict[str, dict]) -> dict:
    alias = publishmod.route(f, repos)[0]
    if alias not in repos:
        raise RunError(f"{f['id']}: its first cite names no repo of this run ({alias or 'none'})")
    return repos[alias]


def _git(repo: Path, *args: str, check: bool = True) -> str:
    return runmod._git(Path(repo), *args, check=check).stdout.strip()


def _ok(repo: Path, *args: str) -> bool:
    return runmod._git(Path(repo), *args, check=False).returncode == 0


def _rel(path: str, subdir: str) -> str:
    """A repo-root path as the run cites it (relative to the repo's subdir), or "" when outside the subdir."""
    prefix = subdir.strip("/") + "/" if subdir.strip("/") else ""
    return path[len(prefix):] if path.startswith(prefix) else ""


def _full(path: str, subdir: str) -> str:
    return f"{subdir.strip('/')}/{path}" if subdir.strip("/") else path


def is_test_path(path: str) -> bool:
    parts = path.split("/")
    stem = parts[-1].split(".")[0] if not re.search(r"\.(test|spec)\.", parts[-1]) else parts[-1].rsplit(".", 1)[0]
    return any(p.lower() in TEST_DIRS for p in parts[:-1]) or bool(TEST_STEM.match(stem))


def candidates(items: List[dict]) -> List[dict]:
    """Findings a fix can start from: confirmed correctness findings with a red-test branch, not fixed yet."""
    return [f for f in items if f.get("report") == "correctness" and f.get("verdict") == "confirmed"
            and f.get("branch") and f.get("sha_test") and _status(f) != "done"]


def _group_refs(repo: Path) -> List[Tuple[str, str]]:
    """(local name, full ref) of every `audit/pr-N` branch, pushed ones first."""
    out = []
    for prefix, strip in (("refs/remotes/origin/audit/", "refs/remotes/origin/"), ("refs/heads/audit/", "refs/heads/")):
        for ref in _git(repo, "for-each-ref", "--format=%(refname)", prefix, check=False).splitlines():
            name = ref[len(strip):]
            if name not in [n for n, _ in out]:
                out.append((name, ref))
    return out


def unit_branch(repo: Path, f: dict, refs: Optional[List[Tuple[str, str]]] = None) -> str:
    """The PR branch of a finding: the `audit/pr-N` whose history holds its red-test commit (read-only git), or its
    own branch. Read from the branches themselves, not recomputed from the findings, which may have changed since."""
    for name, ref in _group_refs(repo) if refs is None else refs:
        if _ok(repo, "merge-base", "--is-ancestor", f["sha_test"], ref):
            return name
    return f["branch"]


def units(manifest: dict, items: List[dict]) -> List[dict]:
    """Candidates joined by PR branch: [{branch, repo, members}], in the order of their first member."""
    repos = _repos(manifest)
    refs: Dict[str, List[Tuple[str, str]]] = {}
    out: Dict[Tuple[str, str], dict] = {}
    for f in candidates(items):
        repo = _repo_of(f, repos)
        if repo["path"] not in refs:
            refs[repo["path"]] = _group_refs(Path(repo["path"]))
        branch = unit_branch(Path(repo["path"]), f, refs[repo["path"]])
        out.setdefault((repo["path"], branch), {"branch": branch, "repo": repo, "members": []})["members"].append(f)
    return sorted(out.values(), key=lambda u: findingsmod._id_key(u["members"][0]))


def gh_pr(repo: dict, branch: str) -> Optional[dict]:
    """The PR whose head is `branch` (read-only `gh pr list`), an open one first: {number, baseRefName, state}; None
    when gh is missing or fails, or there is no such PR."""
    slug = publishmod.gh_repo(repo.get("remote", ""))
    if not slug:
        return None
    try:
        res = subprocess.run(["gh", "pr", "list", "--repo", slug, "--head", branch, "--state", "all", "--json",
                              "number,baseRefName,state"], capture_output=True, text=True, stdin=subprocess.DEVNULL,
                             timeout=60)
        prs = json.loads(res.stdout) if res.returncode == 0 else []
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    prs = [p for p in prs if isinstance(p, dict) and p.get("number")]
    prs.sort(key=lambda p: p.get("state") != "OPEN")
    return prs[0] if prs else None


def plan(run: Path, ids: Optional[List[str]] = None, severity: Optional[str] = None,
         alias: Optional[str] = None) -> List[str]:
    """Lines describing each PR branch to fix: PR number and base (read-only gh), and each member's proposal."""
    run = Path(run)
    manifest = runmod.load(run)
    items = findingsmod.load_all(run)
    wanted = set(ids or [])
    unknown = sorted(wanted - {f["id"] for f in items})
    if unknown:
        raise UsageError(f"no finding {', '.join(unknown)} in {run}")
    lines = []
    shown = 0
    if not (manifest.get("fix") or {}).get("authorized_by"):
        lines.append("note: fix.authorized_by is not set: confirm with the person that the owner team agreed to "
                     f"receive fixes, then `ia.py set --run {run} fix.authorized_by=<who>`; `fix start` needs it")
    for unit in units(manifest, items):
        members = [f for f in unit["members"] if (not wanted or f["id"] in wanted)
                   and (not severity or f.get("severity") == severity)
                   and (not alias or unit["repo"]["alias"] == alias)]
        if not members:
            continue
        shown += 1
        pr = gh_pr(unit["repo"], unit["branch"])
        where = (f"PR #{pr['number']} ({pr.get('state', '?').lower()}) base {pr.get('baseRefName') or '?'}" if pr
                 else "PR ? (gh found none; pass --base-ref to start)")
        group = " (group: fixed in order, one worktree)" if len(unit["members"]) > 1 else ""
        lines.append(f"{unit['repo']['alias']} {unit['branch']}  {where}{group}")
        for f in unit["members"]:
            mark = "" if f in members else "  (in the same PR, not selected)"
            status = f" [{_status(f)}]" if _status(f) else ""
            proposal = publishmod._proposal(f) or "(no fix_summary)"
            lines.append(f"  {f['id']} {f.get('severity', '')}{status}{mark}: {proposal}")
            lines.append(f"    prod_files: {', '.join(f.get('prod_files') or []) or '(none named)'}")
    if not shown:
        lines.append("nothing to fix: no confirmed correctness finding with a red-test branch matches")
    return lines


# --- state of a PR branch being fixed ---------------------------------------------------------------------------

def _dir(run: Path, branch: str) -> Path:
    return Path(run) / "fix" / _slug(branch)


def _worktree(run: Path, branch: str) -> Path:
    return Path(run) / "fix" / f"wt-{_slug(branch)}"


def load_state(run: Path, branch: str) -> dict:
    path = _dir(run, branch) / "state.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise RunError(f"{branch} was not started; run `ia.py fix start --run {run} {branch}` first")


def _save_state(run: Path, state: dict) -> None:
    folder = _dir(run, state["branch"])
    folder.mkdir(parents=True, exist_ok=True)
    runmod.atomic_write(folder / "state.json", json.dumps(state, indent=2, ensure_ascii=False) + "\n")


def _state_of(run: Path, f: dict) -> dict:
    branch = _fix(f).get("unit")
    if not branch:
        raise RunError(f"{f['id']} was not started; run `ia.py fix start --run {run} {f['id']}` first")
    return load_state(run, branch)


# --- the suite on the merge result ------------------------------------------------------------------------------

def run_suite(repo: dict, plan_: dict, rev: str, base: str, timeout: int) -> dict:
    """Runs the plan's suite (and type-check, when the plan has one) on a throwaway merge of `base` into `rev`, in a
    detached worktree that is removed afterwards. A merge conflict is reported and the suite runs on `rev` alone."""
    repo_path = Path(repo["path"])
    env = {**os.environ, **baselinemod.BASE_ENV, **{str(k): str(v) for k, v in (plan_.get("env") or {}).items()}}
    chunks = baselinemod._Chunks()
    deadline = time.monotonic() + timeout
    tmp = Path(tempfile.mkdtemp(prefix="ia-fix-"))
    wt = tmp / "wt"
    out = {"exit": None, "conflict": False, "conflicted": [], "error": "", "cases": None, "files": {},
           "counts": {"passed": None, "failed": None, "total": None}, "typecheck": None, "text": ""}
    groups: List[int] = []
    added = False
    try:
        runmod._git(repo_path, "worktree", "add", "--detach", str(wt), rev)
        added = True
        if base:
            # nothing is committed: the merge only builds the tree the PR would have once merged
            m = runmod._git(wt, "-c", "user.name=ia", "-c", "user.email=ia@localhost", "merge", "--no-commit",
                            "--no-ff", base, check=False)
            chunks.add(f"git merge --no-commit --no-ff {base}", (m.stdout + m.stderr).encode("utf-8"))
            if m.returncode != 0:
                out["conflict"] = True
                out["conflicted"] = _git(wt, "diff", "--name-only", "--diff-filter=U", check=False).splitlines()
                runmod._git(wt, "merge", "--abort", check=False)
                chunks.add("merge conflict", f"the suite runs on {rev} alone\n".encode("utf-8"))
        cwd = baselinemod._worktree_cwd(repo_path, repo["subdir"], wt)
        deps = plan_.get("deps", "none")
        if deps == "symlink":
            baselinemod._link_deps(repo_path / repo["subdir"], cwd, list(plan_.get("deps_dirs") or []), chunks)
        steps: List[Tuple[str, List[str]]] = []
        if deps == "install" and plan_.get("install_cmd"):
            steps.append(("install", list(plan_["install_cmd"])))
        steps += [("pre", list(cmd)) for cmd in (plan_.get("pre") or [])]
        steps.append(("suite", list(plan_["test_cmd"])))
        if plan_.get("typecheck_cmd"):
            steps.append(("typecheck", list(plan_["typecheck_cmd"])))
        suite_text = ""
        for kind, cmd in steps:
            try:
                code, data, expired = baselinemod._exec(cmd, cwd, env, deadline, groups)
            except OSError as exc:
                out["error"] = f"could not start `{' '.join(cmd)}`: {exc}"
                chunks.add(" ".join(cmd), (out["error"] + "\n").encode("utf-8"))
                break
            chunks.add(" ".join(cmd), data)
            if expired:
                out["error"] = f"`{' '.join(cmd)}` timed out after {timeout}s"
                break
            if kind == "suite":
                out["exit"] = code
                suite_text = data.decode("utf-8", errors="replace")
            elif kind == "typecheck":
                out["typecheck"] = code
            elif code != 0:
                out["error"] = f"{kind} command `{' '.join(cmd)}` exited {code}"
                break
        if out["exit"] is not None:
            if plan_.get("junit"):  # read before the worktree goes
                cases = baselinemod.junit_cases(cwd, list(plan_["junit"]))
                if cases:
                    out["cases"], out["files"] = cases["cases"], cases["files"]
                counts = baselinemod.parse_junit(cwd, list(plan_["junit"]))
            else:
                counts = None
            parsed = counts or baselinemod.parse_summary(suite_text)
            out["counts"] = {k: parsed.get(k) for k in ("passed", "failed", "total")}
    finally:
        baselinemod._stop_groups(groups)
        if added:
            subprocess.run(["git", "worktree", "remove", "--force", str(wt)], cwd=str(repo_path),
                           capture_output=True, stdin=subprocess.DEVNULL)
        subprocess.run(["git", "worktree", "prune"], cwd=str(repo_path), capture_output=True, stdin=subprocess.DEVNULL)
        shutil.rmtree(tmp, ignore_errors=True)
    out["text"] = hygienemod.mask_text(chunks.text())
    return out


def _cases_of(path: str, cases: Dict[str, str], files: Dict[str, str]) -> Dict[str, str]:
    """The testcases of one test file: the runner's `file` attribute when it wrote one, otherwise the file's stem
    matched against the last segment of the classname (`$Inner` of a nested class stripped) or any of its segments."""
    stem = Path(path).name.split(".")[0]
    out = {}
    for name, status in cases.items():
        if files.get(name):
            if path.endswith(files[name]) or files[name].endswith(path):
                out[name] = status
            continue
        classname = name.rsplit(".", 1)[0] if "." in name else name
        segments = [s.split("$")[0] for s in classname.split(".")]
        if stem in segments:
            out[name] = status
    return out


def _passing(result: dict) -> List[str]:
    return sorted(n for n, s in (result["cases"] or {}).items() if s == "pass")


def _suite_line(counts: dict) -> str:
    if counts.get("total") is None:
        return "not parsed"
    return f"{counts['passed']} of {counts['total']} pass"


def _save_output(run: Path, rel: str, text: str) -> str:
    (Path(run) / "outputs").mkdir(exist_ok=True)
    (Path(run) / rel).write_text(text, encoding="utf-8", errors="replace")
    return rel


# --- start ------------------------------------------------------------------------------------------------------

def _resolve(run: Path, manifest: dict, target: str) -> dict:
    """The unit (PR branch) of a finding id or a branch name, with every member."""
    items = findingsmod.load_all(run)
    all_units = units(manifest, items)
    if findingsmod.ID_RE.match(target):
        f = next((x for x in items if x["id"] == target), None)
        if f is None:
            raise UsageError(f"no finding {target} in {run}")
        if f not in candidates(items):
            raise RunError(f"{target} cannot be fixed here: it needs report=correctness, verdict=confirmed, a branch "
                           "and sha_test, and must not be done already")
        unit = next(u for u in all_units if f in u["members"])
    else:
        found = [u for u in all_units if u["branch"] == target]
        if not found:
            raise UsageError(f"{target} is not the PR branch of any finding left to fix (see `ia.py fix plan`)")
        if len(found) > 1:
            raise UsageError(f"{target} exists in more than one repo; name a finding id instead")
        unit = found[0]
    return unit


def _check_branch(repo_path: Path, branch: str, base_ref: Optional[str]) -> str:
    """The local branch's tip, refusing a missing branch or one that is not equal to its upstream (read-only fetch)."""
    if not _ok(repo_path, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"):
        hint = (f"git -C {shlex.quote(str(repo_path))} branch {shlex.quote(branch)} origin/{branch}"
                if _ok(repo_path, "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}") else
                "it is not on the remote either")
        raise RunError(f"local branch {branch} not found in {repo_path}; create it from the pushed one: {hint}")
    tip = _git(repo_path, "rev-parse", f"refs/heads/{branch}")
    upstream = runmod._git(repo_path, "rev-parse", "--abbrev-ref", "--symbolic-full-name", f"{branch}@{{upstream}}",
                           check=False)
    if upstream.returncode != 0:
        if base_ref:
            return tip  # a sandbox clone without a remote (the --base-ref test aid)
        raise RunError(f"{branch} has no upstream: a fix starts from a published red-test branch (push it first, or "
                       f"pass --base-ref in a sandbox)")
    up = upstream.stdout.strip()
    remote, _, name = up.partition("/")
    runmod._git(repo_path, "fetch", "--quiet", remote, name, check=False)  # read-only for the branch: no pull, no push
    up_sha = _git(repo_path, "rev-parse", up, check=False)
    if up_sha != tip:
        raise RunError(f"{branch} ({tip[:10]}) differs from its upstream {up} ({up_sha[:10] or '?'}); make them equal "
                       "first (never by force), then start again")
    return tip


def _context(f: dict, repo: dict, plan_: dict, branch: str, base: str) -> str:
    tests = "\n".join(f"- `{t.get('path')}`: red {t.get('red') or '?'}. {t.get('note') or ''}".rstrip()
                      for t in f.get("tests") or [] if isinstance(t, dict))
    lines = [f"# {f['id']}: {f.get('title', '')}", "",
             f"- Repo: {repo['alias']} ({repo['path']}{'/' + repo['subdir'] if repo['subdir'] else ''})",
             f"- PR branch: `{branch}`; red-test commit `{f['sha_test']}`; proven against `{base}`",
             f"- Test command: `{' '.join(plan_.get('test_cmd') or [])}`", "",
             "## What happens", "", str(f.get("what_happens") or ""), "",
             "## Proposed fix (the starting point, not a mandate)", "",
             str(f.get("fix_summary") or "(none written)"), "",
             "## Production files in scope", ""]
    lines += [f"- `{p}`" for p in f.get("prod_files") or []] or ["(none named: name every file in fix.extra_files)"]
    lines += ["", "## The red test (frozen: never edit, skip, rename or weaken it)", "", tests or "(none)", "",
              "## Why it is red", "", str(f.get("red_reason") or "")]
    return hygienemod.mask_text("\n".join(lines), prose=True) + "\n"


def start(run: Path, target: str, base_ref: Optional[str] = None, timeout: int = 3600) -> List[str]:
    run = Path(run).resolve()
    manifest = runmod.load(run)
    if not (manifest.get("fix") or {}).get("authorized_by"):
        raise RunError("fix.authorized_by is not set: confirm with the person that the owner team agreed to receive "
                       f"fixes (or that the person takes that decision), then `ia.py set --run {run} "
                       "fix.authorized_by=<who>`")
    unit = _resolve(run, manifest, target)
    repo, branch = unit["repo"], unit["branch"]
    repo_path = Path(repo["path"])
    plan_ = (manifest["baseline"].get(repo["alias"]) or {}).get("plan") or {}
    if not plan_.get("test_cmd"):
        raise RunError(f"{repo['alias']} has no test_cmd in its plan; set one with `ia.py baseline --set`")
    runmod._check_clean(repo["alias"], repo_path)
    tip = _check_branch(repo_path, branch, base_ref)
    pr = gh_pr(repo, branch)  # read-only; with --base-ref only for the PR's real base, shown to the person
    if base_ref:
        base = base_ref
    else:
        if not pr or not pr.get("baseRefName"):
            raise RunError(f"no PR found for {branch} with gh (read-only `gh pr list`); the base it merges into is "
                           "unknown. Check gh auth, or pass --base-ref <ref>")
        base = f"origin/{pr['baseRefName']}"
        runmod._git(repo_path, "fetch", "--quiet", "origin", pr["baseRefName"])
    if not _ok(repo_path, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}"):
        raise RunError(f"base {base} not found in {repo_path}")
    wt = _worktree(run, branch)
    lines = []
    if wt.exists():
        if _git(wt, "rev-parse", "--abbrev-ref", "HEAD", check=False) != branch:
            raise RunError(f"{wt} exists but is not a worktree on {branch}; remove it and start again")
        lines.append(f"reusing worktree {wt}")
    else:
        wt.parent.mkdir(parents=True, exist_ok=True)
        runmod._git(repo_path, "worktree", "add", str(wt), branch)
        lines.append(f"worktree {wt} on {branch}")
    try:
        old = load_state(run, branch)
    except RunError:
        old = {}
    state = {"branch": branch, "alias": repo["alias"], "base": base, "pr": (pr or {}).get("number") or old.get("pr"),
             "pr_base": (pr or {}).get("baseRefName") or old.get("pr_base") or "", "base_ref": base_ref or "",
             "tip": old.get("tip") or tip, "last": old.get("last") or tip, "done": old.get("done") or {},
             "members": [f["id"] for f in unit["members"]]}
    folder = _dir(run, branch)
    folder.mkdir(parents=True, exist_ok=True)
    for f in unit["members"]:
        (folder / f"{f['id']}.md").write_text(_context(f, repo, plan_, branch, base), encoding="utf-8")
    if pr:
        lines.append(f"PR #{pr['number']} merges into {pr.get('baseRefName') or '?'}"
                     + (f"; --base-ref: merging the local ref {base_ref} instead" if base_ref else ""))
    lines.append(f"proving on a throwaway merge of {base} into {branch} ({tip[:10]}); suite: "
                 f"{' '.join(plan_['test_cmd'])}")
    result = run_suite(repo, plan_, state["last"], base, timeout)
    if result["error"] and result["exit"] is None:
        raise runmod.ToolError(f"the suite did not run: {result['error']}")
    compared = "names" if result["cases"] is not None else "counts"
    state["start"] = {"compared": compared, "passed": _passing(result), "counts": result["counts"],
                      "failed": sorted(n for n, s in (result["cases"] or {}).items() if s == "fail"),
                      "conflict": result["conflict"], "conflicted": result["conflicted"]}
    if result["conflict"]:
        lines.append(f"conflict: {branch} does not merge cleanly with {base} ({', '.join(result['conflicted'])}); the "
                     "suite ran on the branch alone. Decide with the person: rebase the red branch first, or fix on "
                     "the old base and leave the conflict to the PR")
    lines.append(f"suite at start: {_suite_line(result['counts'])} (compared later by {compared}"
                 + ("" if compared == "names" else ": the plan has no readable junit reports") + ")")
    for f in unit["members"]:
        if _status(f) in CLOSED:
            lines.append(f"  {f['id']}: {_status(f)} already")
            continue
        rel = _save_output(run, f"outputs/{f['id']}-fix-red.txt", result["text"])
        red = _red_names(f, result)
        status = "started"
        if result["cases"] is not None:
            mine = {n: s for t in _test_paths(f) for n, s in _cases_of(t, result["cases"], result["files"]).items()}
            if mine and all(s == "pass" for s in mine.values()):
                status = "moot"
        elif result["counts"]["failed"] == 0:
            lines.append(f"  {f['id']}: the suite has no failure on the merge result; by counts its red test may "
                         f"already pass upstream: check {rel} before fixing")
        changes = {"fix.status": status, "fix.unit": branch, "fix.reason": "" if status != "moot" else
                   f"its tests already pass on {base} (fixed upstream)"}
        findingsmod.update(run, f["id"], changes)
        state.setdefault("red", {})[f["id"]] = red
        lines.append(f"  {f['id']}: {status}" + (f" (red now: {len(red)} test{'s' if len(red) != 1 else ''})"
                                               if result["cases"] is not None and status == "started" else "")
                     + f"; context {folder / (f['id'] + '.md')}")
    _save_state(run, state)
    return lines


def _test_paths(f: dict) -> List[str]:
    return [t["path"] for t in f.get("tests") or [] if isinstance(t, dict) and t.get("path")]


def _red_names(f: dict, result: dict) -> List[str]:
    if result["cases"] is None:
        return []
    return sorted(n for t in _test_paths(f) for n, s in _cases_of(t, result["cases"], result["files"]).items()
                  if s == "fail")


def _red_count(f: dict) -> int:
    total = 0
    for t in f.get("tests") or []:
        m = RED_COUNT.search(str(t.get("red") or "")) if isinstance(t, dict) else None
        total += int(m.group(1)) if m else 0
    return total


# --- check ------------------------------------------------------------------------------------------------------

def check(run: Path, fid: str, allow_many: bool = False, timeout: int = 3600) -> Tuple[bool, List[str]]:
    """Mechanical checks of a member's fix commits; records `fix.check` and returns (passed, lines)."""
    run = Path(run).resolve()
    manifest = runmod.load(run)
    f = _finding(run, fid)
    state = _state_of(run, f)
    repo = _repos(manifest)[state["alias"]]
    wt = _worktree(run, state["branch"])
    if not wt.is_dir():
        raise RunError(f"worktree {wt} not found; run `ia.py fix start --run {run} {fid}` again")
    if _git(wt, "rev-parse", "--abbrev-ref", "HEAD") != state["branch"]:
        raise RunError(f"{wt} is not on {state['branch']}")
    runmod._check_clean(fid, wt)
    head = _git(wt, "rev-parse", "HEAD")
    last = state["last"]
    problems: List[str] = []
    commits = _git(wt, "rev-list", "--reverse", f"{last}..HEAD").splitlines() if head != last else []
    if not _ok(wt, "merge-base", "--is-ancestor", last, "HEAD"):
        problems.append(f"HEAD does not descend from {last[:10]} (the red test or the previous member's fix): never "
                        "rewrite the published commits")
        commits = []
    if not commits:
        problems.append(f"no fix commit on top of {last[:10]}")
    merges = _git(wt, "rev-list", "--merges", f"{last}..HEAD").splitlines() if commits else []
    if merges:
        problems.append(f"merge commit in the fix: {', '.join(m[:10] for m in merges)}; the fix is plain commits")
    if len(commits) > 1 and not allow_many:
        problems.append(f"{len(commits)} commits after {last[:10]}; one fix commit per finding (or --allow-many)")
    subdir = repo["subdir"]
    frozen = [_full(p, subdir) for g in state["members"] for p in _test_paths(_finding(run, g))]
    if frozen:
        edited = _git(wt, "diff", "--name-only", state["tip"], "HEAD", "--", *frozen).splitlines()
        problems += [f"red test changed: {p} (the test of commit 1 is the spec and stays byte-identical)"
                     for p in edited]
    allowed = set(f.get("prod_files") or []) | set(_fix(f).get("extra_files") or [])
    for line in (_git(wt, "diff", "--name-status", "--no-renames", last, "HEAD").splitlines() if commits else []):
        status, _, path = line.partition("\t")
        rel = _rel(path, subdir)
        if hygienemod._is_tooling(path):
            problems.append(f"tooling file in the fix: {path}")
        elif rel in allowed:
            continue
        elif is_test_path(rel or path) and status == "A":
            continue
        elif is_test_path(rel or path):
            problems.append(f"existing test file changed: {path} (only new tests may be added)")
        elif path not in frozen:
            problems.append(f"out of scope: {path} (not in prod_files; name it with its reason in fix.extra_files)")
    problems += _message_problems(wt, last, commits, (str(run),))
    if commits:
        problems += [p for p in hygienemod.check_branch(wt, last, state["branch"])
                     if hygienemod.R_ATTRIBUTION not in p]  # attribution is in _message_problems, once
    green = Path(run) / "outputs" / f"{fid}-green.txt"
    if not green.is_file():
        problems.append(f"outputs/{fid}-green.txt not found: run the finding's tests and save their output there")
    plan_ = (manifest["baseline"].get(repo["alias"]) or {}).get("plan") or {}
    if (Path(run) / "outputs" / f"{fid}-typecheck.txt").is_file() and not plan_.get("typecheck_cmd") \
            and not (Path(run) / "outputs" / f"{fid}-fix-typecheck.txt").is_file():
        problems.append(f"outputs/{fid}-fix-typecheck.txt not found: rerun the command recorded in "
                        f"outputs/{fid}-typecheck.txt on the fix and save it there (or set the plan's typecheck_cmd)")
    lines: List[str] = []
    record = {"passed": False, "sha": head, "suite": "", "compared": "", "conflict": False}
    if commits and not merges:
        result = run_suite(repo, plan_, head, state["base"], timeout)
        rel = _save_output(run, f"outputs/{fid}-fix-suite.txt", result["text"])
        if result["error"] and result["exit"] is None:
            problems.append(f"the suite did not run: {result['error']}")
        compare_problems, compared, greens = _compare(f, state, result)
        problems += compare_problems
        if result["typecheck"] not in (None, 0):
            problems.append(f"type-check failed (exit {result['typecheck']}); see {rel}")
        record.update({"suite": _suite_line(result["counts"]), "compared": compared, "conflict": result["conflict"],
                       "output": rel, "green": greens})
        lines.append(f"suite on the merge of {state['base']} + {head[:10]}: {record['suite']} (compared by "
                     f"{compared}{'' if compared == 'names' else ': no junit names'}); output {rel}")
        if result["conflict"]:
            lines.append(f"conflict with {state['base']}: {', '.join(result['conflicted'])} (reported, not a failure; "
                         "the suite ran on the branch alone)")
    record["passed"] = not problems
    if problems:
        record["problems"] = problems[:20]
    findingsmod.update(run, fid, {"fix.check": record})
    lines += [f"FAIL {p}" for p in problems]
    lines.append(f"check {fid}: " + ("passed" if not problems else f"{len(problems)} problem"
                                     + ("" if len(problems) == 1 else "s")))
    return not problems, lines


def _model_id(name: str) -> str:
    """`gpt-6-luna (codex exec read-only)` -> `gpt-6-luna`: the model id without the notes after it."""
    return re.split(r"[\s(]", name.strip().lower(), maxsplit=1)[0] if name.strip() else ""


def _finding(run: Path, fid: str) -> dict:
    path = Path(run) / "findings" / f"{fid}.json"
    if not findingsmod.ID_RE.match(fid or "") or not path.is_file():
        raise UsageError(f"no finding {fid} in {run}")
    return findingsmod._read(path)


def _message_problems(wt: Path, last: str, commits: List[str], extra: Tuple[str, ...] = ()) -> List[str]:
    out = []
    for sha in commits:
        subject = _git(wt, "log", "-1", "--format=%s", sha)
        body = _git(wt, "log", "-1", "--format=%B", sha)
        if not publishmod.CONVENTIONAL.match(subject):
            out.append(f"commit {sha[:10]}: subject is not a conventional commit: {subject[:80]}")
        if len(subject) > publishmod.MAX_TITLE:
            out.append(f"commit {sha[:10]}: subject is {len(subject)} characters (max {publishmod.MAX_TITLE})")
        m = CLOSING.search(body)
        if m:
            out.append(f"commit {sha[:10]}: closing keyword {m.group(0)!r}: closing belongs to the PR body")
        hit = hygienemod.local_path_hit(body, extra)
        if hit:
            out.append(f"commit {sha[:10]}: local path in the message ({hit}): it becomes public with the push; "
                       "quote commands relative to the repo root (./gradlew test --tests ...)")
    if commits:
        out += hygienemod._attribution_in_commits(wt, last, "HEAD")
    return out


def _compare(f: dict, state: dict, result: dict) -> Tuple[List[str], str, Dict[str, str]]:
    """No new failures against the start, and the member's red tests green: by junit names when both runs have them,
    by counts otherwise. Returns (problems, "names"|"counts", {test path: "n of n pass"})."""
    start = state.get("start") or {}
    greens: Dict[str, str] = {}
    if result["cases"] is not None and start.get("compared") == "names":
        now = set(_passing(result))
        problems = [f"new failure: {n}" for n in sorted(set(start.get("passed") or []) - now)][:10]
        red = (state.get("red") or {}).get(f["id"]) or []
        problems += [f"red test still not passing: {n}" for n in red if n not in now]
        for path in _test_paths(f):
            mine = _cases_of(path, result["cases"], result["files"])
            ok = sum(1 for s in mine.values() if s == "pass")
            if not mine:
                problems.append(f"no junit case found for {path}")
            elif ok != len(mine):
                problems.append(f"{path}: {len(mine) - ok} of {len(mine)} do not pass")
            greens[path] = f"{ok} of {len(mine)} pass" if mine else ""
        return problems, "names", greens
    c0, c1 = start.get("counts") or {}, result["counts"]
    if c1.get("total") is None or c0.get("total") is None:
        return ["the suite summary could not be read; compare it by hand and do not record the fix"], "counts", greens
    problems = []
    expected = max((c0.get("failed") or 0) - _red_count(f), 0)
    if (c1.get("failed") or 0) > expected:
        problems.append(f"by counts: {c1['failed']} failing now, expected at most {expected} (start {c0['failed']} "
                        f"minus {_red_count(f)} red)")
    if c1["total"] < c0["total"]:
        problems.append(f"by counts: {c1['total']} tests now, {c0['total']} at start (tests disappeared)")
    return problems, "counts", greens


# --- done -------------------------------------------------------------------------------------------------------

def done(run: Path, fid: str) -> List[str]:
    """Records the member's result and removes the worktree once every member of its PR branch is closed.

    - started: needs a passing `fix.check` and a review whose three claims are CONFIDENT, both on the current HEAD;
      sets fix.status=done, sha_fix, tests[].green, outputs.green and outputs.suite.
    - blocked or declined (set by `finding set` with fix.reason): resets the local branch to before this member's
      commits (nothing was pushed).
    - moot: nothing to record.
    """
    run = Path(run).resolve()
    f = _finding(run, fid)
    state = _state_of(run, f)
    wt = _worktree(run, state["branch"])
    status = _status(f)
    lines = []
    if status == "started":
        head = _git(wt, "rev-parse", "HEAD")
        chk = _fix(f).get("check") or {}
        review = _fix(f).get("review") or {}
        claims = review.get("claims") or {}
        why = []
        if not chk.get("passed") or chk.get("sha") != head:
            why.append(f"no passing `ia.py fix check` on HEAD {head[:10]}")
        if review.get("sha") != head:
            why.append(f"no review of HEAD {head[:10]} (fix.review.sha)")
        missing = [c for c in findingsmod.FIX_CLAIMS if (claims.get(c) or {}).get("state") != "CONFIDENT"]
        if missing:
            why.append("review claims not CONFIDENT: " + ", ".join(missing)
                       + " (one revision round, then fix.status=declined with fix.reason)")
        if not review.get("model"):
            why.append("fix.review.model is empty: record which agent reviewed")
        if why:
            raise RunError(f"{fid} cannot be recorded as done: " + "; ".join(why))
        tests = [dict(t, green=(chk.get("green") or {}).get(t.get("path"), t.get("green", "")))
                 if isinstance(t, dict) else t for t in f.get("tests") or []]
        findingsmod.update(run, fid, {"fix.status": "done", "sha_fix": head, "tests": tests,
                                      "outputs.green": f"outputs/{fid}-green.txt",
                                      "outputs.suite": chk.get("output") or f"outputs/{fid}-fix-suite.txt"})
        state["last"] = head
        state.setdefault("done", {})[fid] = head
        _save_state(run, state)
        lines.append(f"{fid}: done (sha_fix {head[:10]}, suite {chk.get('suite')})")
        contrast = (f.get("contrast") or {}).get("model") or ""
        if contrast and _model_id(contrast) == _model_id(review.get("model") or ""):
            lines.append(f"warning: {fid}: the reviewer ({review.get('model')}) is the model that already judged this "
                         f"finding in the audit's contrast ({contrast}); prefer one that has not, and say so to the "
                         "person")
    elif status in ("blocked", "declined"):
        if wt.is_dir():
            head = _git(wt, "rev-parse", "HEAD")
            if head != state["last"]:
                runmod._check_clean(fid, wt)
                runmod._git(wt, "reset", "--quiet", "--hard", state["last"])
                lines.append(f"{fid}: {status}; local {state['branch']} reset from {head[:10]} to {state['last'][:10]} "
                             "(nothing was pushed)")
        lines.append(f"{fid}: {status}: {_fix(f).get('reason')}")
    elif status in ("moot", "done"):
        lines.append(f"{fid}: {status}")
    else:
        raise RunError(f"{fid} has fix.status {status or 'empty'}; nothing to record")
    left = [m for m in state["members"] if _status(_finding(run, m)) not in CLOSED]
    if left:
        lines.append(f"worktree kept for {', '.join(left)}: {wt}")
    elif wt.is_dir():
        repo = _repos(runmod.load(run))[state["alias"]]
        runmod._check_clean(state["branch"], wt)
        runmod._git(Path(repo["path"]), "worktree", "remove", str(wt))
        lines.append(f"worktree removed: {wt}")
    return lines


# --- publish ----------------------------------------------------------------------------------------------------

def _pr_base(state: dict) -> str:
    """The base the PR merges into, as gh reported it; never the --base-ref test ref."""
    if state.get("pr_base"):
        return state["pr_base"]
    if state.get("base_ref"):
        return "unknown (gh found no PR)"
    return str(state.get("base") or "").replace("origin/", "", 1)


def _note(fixed: List[str], moot: List[str], pending: List[str], suite: str, base: str) -> str:
    if not pending:
        what = "the fix" if len(fixed) == 1 and not moot else f"the fix for {', '.join(fixed)}"
        note = (f"Now includes {what}: the test fails at the base and passes with it; full suite: {suite}." if
                len(fixed) == 1 else
                f"Now includes {what}: each test fails at the base and passes with it; full suite: {suite}.")
        if moot:
            note += f" {', '.join(moot)} already pass{'es' if len(moot) == 1 else ''} on {base} (fixed upstream)."
        return note
    return (f"Includes the fix for {', '.join(fixed)}; {', '.join(pending)} still "
            f"{'has' if len(pending) == 1 else 'have'} only the failing test, so this PR stays a draft. Full suite: "
            f"{suite}.")


def _fix_title(fixed: List[dict], repo: dict) -> str:
    subject = _git(Path(repo["path"]), "log", "-1", "--format=%s", fixed[0]["sha_fix"], check=False)
    title = hygienemod.mask_text(subject, prose=True) or f"fix: {publishmod._title(fixed[0])}"
    more = f" (+{len(fixed) - 1} more)" if len(fixed) > 1 else ""
    return title + more if more and len(title) + len(more) <= publishmod.MAX_TITLE else publishmod.cut_title(title)


def publish(run: Path, partial: bool = False) -> Tuple[Path, List[str]]:
    """Writes `<run>/fix/commands.sh` (never runs it): per PR branch with fixes, a fast-forward push, the PR found at
    run time, the body rewritten from the PR's current body, and, once every member is done or moot, the fix title
    and `gh pr ready`."""
    run = Path(run).resolve()
    manifest = runmod.load(run)
    repos = _repos(manifest)
    items = {f["id"]: f for f in findingsmod.load_all(run)}
    branches = []
    for f in items.values():
        unit = _fix(f).get("unit")
        if unit and unit not in branches:
            branches.append(unit)
    out = run / "fix"
    out.mkdir(exist_ok=True)
    awk = out / "body.awk"
    awk.write_text(BODY_AWK.read_text(encoding="utf-8"), encoding="utf-8")
    q = shlex.quote
    cmds = ["#!/bin/sh", "set -eu", HEADER,
            "# Each block pushes one PR branch fast-forward only (never forced), finds its open PR at run time,",
            "# rewrites the PR's current body (draft note -> fix note, Refs -> Closes) and, once every finding of",
            "# the PR is fixed, retitles it and marks it ready. Labels are left as they are.", ""]
    lines: List[str] = []
    for branch in branches:
        state = load_state(run, branch)
        repo = repos[state["alias"]]
        members = [items[m] for m in state["members"] if m in items]
        fixed = [f for f in members if _status(f) == "done"]
        moot = [f["id"] for f in members if _status(f) == "moot"]
        pending = [f["id"] for f in members if _status(f) not in ("done", "moot")]
        if not fixed:
            lines.append(f"{branch}: skipped, no finding done yet")
            continue
        if pending and not partial:
            cmds += [publishmod._comment(f"{branch}: skipped: {', '.join(pending)} not done (fix them, or "
                                         "`ia.py fix publish --partial` to push what is fixed and keep the draft)"), ""]
            lines.append(f"{branch}: skipped, {', '.join(pending)} not done")
            continue
        slug = publishmod.gh_repo(repo.get("remote", ""))
        if not slug:
            cmds += [publishmod._comment(f"{branch}: skipped, {repo['alias']} has no GitHub-style remote"), ""]
            continue
        path = q(repo["path"])
        suite = (_fix(fixed[-1]).get("check") or {}).get("suite") or "not measured"
        note = _note([f["id"] for f in fixed], moot, pending, suite, _pr_base(state))
        closes = " ".join(f["id"] for f in fixed) + ("" if pending else " " + " ".join(moot))
        body = out / f"{_slug(branch)}.body.md"
        cmds += [publishmod._comment(f"{branch} ({repo['alias']}): fixed {', '.join(f['id'] for f in fixed)}"
                                     + (f"; moot {', '.join(moot)}" if moot else "")
                                     + (f"; still red {', '.join(pending)}" if pending else "")
                                     + f"; PR base {_pr_base(state)}"
                                     + (f" (tested against local ref {state['base_ref']})"
                                        if state.get("base_ref") else "")),
                 f"git -C {path} fetch origin {q(branch)}",
                 f"git -C {path} merge-base --is-ancestor origin/{q(branch)} {q(branch)} || "
                 f"{{ echo {q(f'{branch}: the remote has commits the local branch lacks; stop')} >&2; exit 1; }}",
                 f"[ \"$(git -C {path} rev-parse {q(branch)})\" = {q(state['last'])} ] || "
                 f"{{ echo {q(f'{branch}: the local branch moved since the fix was recorded; check it')} >&2; "
                 "exit 1; }",
                 f"git -C {path} push origin {q(branch)}",
                 f"PR=$(gh pr list --repo {q(slug)} --head {q(branch)} --state open --json number --jq '.[0].number')",
                 f"[ -n \"$PR\" ] || {{ echo {q(f'no open PR with head {branch} in {slug}')} >&2; exit 1; }}",
                 f"gh pr view \"$PR\" --repo {q(slug)} --json body --jq .body | awk -f {q(str(awk))} "
                 f"-v draft={q(publishmod.DRAFT_NOTE)} -v note={q(note)} -v fixed={q(closes.strip())} "
                 f"-v all={0 if pending else 1} > {q(str(body))}",
                 f"gh pr edit \"$PR\" --repo {q(slug)} --body-file {q(str(body))}"]
        if not pending:
            cmds += [f"gh pr edit \"$PR\" --repo {q(slug)} --title {q(_fix_title(fixed, repo))}",
                     f"gh pr ready \"$PR\" --repo {q(slug)}"]
        else:
            cmds.append(publishmod._comment("partial: the title stays and the PR stays a draft while a test of this "
                                            "PR is red"))
        cmds.append(f"echo {q(f'{branch}: PR #')}\"$PR\"{q(' updated')}")
        cmds.append("")
        lines.append(f"{branch}: {'partial' if pending else 'ready'} ({', '.join(f['id'] for f in fixed)})")
    (out / "commands.sh").write_text("\n".join(cmds) + "\n", encoding="utf-8")
    problems = hygienemod.check_fix(run)
    if problems:
        raise RunError("fix/ does not pass hygiene; nothing should be run until it does:\n  " + "\n  ".join(problems))
    return out / "commands.sh", lines
