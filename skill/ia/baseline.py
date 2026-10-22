"""Baseline: run each repo's test suite at the pinned SHA in a detached worktree and record the numbers."""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import run as runmod

TAIL_LINES = 200
PLAN_KEYS = ("stack", "test_cmd", "coverage_cmd", "measure", "measured", "env", "pre", "deps", "deps_dirs", "junit",
             "install_cmd")
DEPS_MODES = ("symlink", "install", "none")
# Non-interactive runs: npx must not download a missing package on its own (the plan's env can override).
BASE_ENV = {"CI": "1", "npm_config_yes": "false", "NO_COLOR": "1", "FORCE_COLOR": "0"}
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")

_VITEST = re.compile(r"^\s*Tests\s{2,}(.*?)\s*\((\d+)\)\s*$")
_JEST = re.compile(r"^\s*Tests:\s+(.*)$")
_PYTEST = re.compile(r"^[=\s]*((?:\d+ [A-Za-z]+(?:, )?)+)\s+in\s+[\d.]+s")
_UNITTEST_RAN = re.compile(r"^Ran (\d+) tests? in ")
_UNITTEST_BAD = re.compile(r"(?:^|[(,]\s*)(failures|errors)=(\d+)")
_UNITTEST_FAILED = re.compile(r"^FAILED \((.*)\)")
_COUNT = re.compile(r"(\d+) ([A-Za-z]+)")
_MAVEN = re.compile(r"^(?:\[(?:INFO|WARNING|ERROR)\]\s+)?Tests run: (\d+), Failures: (\d+), Errors: (\d+), "
                    r"Skipped: (\d+)\s*$")
_GRADLE = re.compile(r"^(\d+) tests? completed(?:, (\d+) failed)?(?:, (\d+) skipped)?")
_COVER_ALL = re.compile(r"^\s*All files\s*\|\s*([\d.]+)")
_COVER_TOTAL = re.compile(r"^TOTAL\b.*?([\d.]+)%\s*$")


def _counts(chunk: str) -> Dict[str, int]:
    found: Dict[str, int] = {}
    for number, word in _COUNT.findall(chunk):
        found[word.lower()] = found.get(word.lower(), 0) + int(number)
    return found


def parse_summary(text: str) -> dict:
    """Reads the runner summary from the last lines of a test output."""
    result = {"passed": None, "failed": None, "total": None, "coverage": None, "runner": None}
    every = _ANSI.sub("", text).splitlines()
    lines = every[-TAIL_LINES:]
    for line in lines:
        m = _COVER_ALL.match(line) or _COVER_TOTAL.match(line)
        if m:
            result["coverage"] = float(m.group(1))
    # Maven prints one summary per module of a reactor build, anywhere in the output: add them all up.
    maven = [tuple(map(int, m.groups())) for m in map(_MAVEN.match, every) if m]
    if maven:
        run, failures, errors, skipped = (sum(col) for col in zip(*maven))
        result.update(passed=max(run - failures - errors - skipped, 0), failed=failures + errors, runner="maven")
        result["total"] = result["passed"] + result["failed"]
        return result
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i]
        m = _GRADLE.match(line)
        if m:
            done, failed, skipped = int(m.group(1)), int(m.group(2) or 0), int(m.group(3) or 0)
            passed = max(done - failed - skipped, 0)
            result.update(passed=passed, failed=failed, total=passed + failed, runner="gradle")
            return result
        m = _JEST.match(line)
        if m:
            c = _counts(m.group(1))
            failed, passed = c.get("failed", 0), c.get("passed", 0)
            result.update(passed=passed, failed=failed, total=c.get("total", passed + failed), runner="jest")
            return result
        m = _VITEST.match(line)
        if m:
            c = _counts(m.group(1))
            result.update(passed=c.get("passed", 0), failed=c.get("failed", 0), total=int(m.group(2)),
                          runner="vitest")
            return result
        m = _PYTEST.match(line)
        if m:
            c = _counts(m.group(1))
            failed = c.get("failed", 0) + c.get("error", 0) + c.get("errors", 0)
            passed = c.get("passed", 0)
            result.update(passed=passed, failed=failed, total=passed + failed, runner="pytest")
            return result
        m = _UNITTEST_RAN.match(line)
        if m:
            total, failed = int(m.group(1)), 0
            for follow in lines[i + 1:]:
                f = _UNITTEST_FAILED.match(follow)
                if f:
                    failed = sum(int(n) for _, n in _UNITTEST_BAD.findall(f.group(1)))
                    break
            result.update(passed=max(total - failed, 0), failed=failed, total=total, runner="unittest")
            return result
    return result


JUNIT_MAX_BYTES = 50 * 1024 * 1024


def _int(value: Optional[str]) -> int:
    try:
        return int(float(value or 0))
    except ValueError:
        return 0


def parse_junit(cwd: Path, globs: List[str]) -> Optional[dict]:
    """Counts summed over the JUnit XML reports under `cwd` that match `globs`; None when none could be read.

    The files come from the audited repo's build: anything with a DTD or entity declaration (an XML bomb or an
    external entity), past the size cap, outside `cwd` or not well formed is listed in `skipped_files`, never parsed.
    Only leaf <testsuite> elements count, so a <testsuites> or nested aggregate is not added twice.
    """
    import xml.etree.ElementTree as ET  # local: only JUnit-producing stacks need it

    base = Path(cwd).resolve()
    paths: List[Path] = []
    for pattern in globs:
        for path in sorted(Path(cwd).glob(pattern)):
            if path.is_file() and path not in paths:
                paths.append(path)
    if not paths:
        return None
    run = failures = errors = skipped = 0
    read, refused = 0, []
    for path in paths:
        rel = path.relative_to(cwd).as_posix()
        try:
            path.resolve().relative_to(base)
            if path.stat().st_size > JUNIT_MAX_BYTES:
                raise ValueError("too large")
            data = path.read_bytes()
            if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
                raise ValueError("declares a DTD or entities")
            root = ET.fromstring(data)
        except (OSError, ValueError, ET.ParseError):
            refused.append(rel)
            continue
        suites = [s for s in root.iter("testsuite") if s.find(".//testsuite") is None]
        for suite in suites:
            run += _int(suite.get("tests"))
            failures += _int(suite.get("failures"))
            errors += _int(suite.get("errors"))
            skipped += _int(suite.get("skipped") or suite.get("disabled"))
        read += 1
    if not read:
        return None
    passed = max(run - failures - errors - skipped, 0)
    return {"passed": passed, "failed": failures + errors, "total": passed + failures + errors, "runner": "junit-xml",
            "files": read, "skipped_files": refused}


def _empty_result(**over) -> dict:
    result = {"passed": None, "failed": None, "total": None, "coverage": None, "runner": None, "exit_code": None,
              "output": None, "timed_out": False, "measured": False}
    result.update(over)
    return result


class _Chunks:
    """Collects the merged output of every command run for one repo, labelled by command."""

    def __init__(self) -> None:
        self.parts: List[bytes] = []

    def add(self, label: str, data: bytes) -> None:
        self.parts.append(f"$ {label}\n".encode("utf-8") + data + (b"" if data.endswith(b"\n") or not data else b"\n"))

    def text(self) -> str:
        return b"".join(self.parts).decode("utf-8", errors="replace")


def _exec(cmd: List[str], cwd: Path, env: Dict[str, str], deadline: float,
          groups: Optional[List[int]] = None) -> Tuple[Optional[int], bytes, bool]:
    """Runs one command in its own process group; returns (exit code, merged output, timed out).

    The output goes to a temp file, not a pipe: a grandchild that left the group (its own session, a daemon) can
    keep a pipe open forever, and reading it to EOF would ignore both the command's exit and the deadline.
    The group id goes into `groups`, so the caller can stop what the command left running in the background.
    """
    with tempfile.TemporaryFile() as sink:
        proc = subprocess.Popen(cmd, cwd=str(cwd), env=env, stdout=sink, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, start_new_session=True)
        if groups is not None:
            groups.append(proc.pid)
        try:
            code: Optional[int] = proc.wait(timeout=max(deadline - time.monotonic(), 0.1))
            expired = False
        except subprocess.TimeoutExpired:
            code, expired = None, True
            _kill_group(proc)
        except BaseException:  # ia itself was stopped: the suite lives in its own session, so stop it too
            _kill_group(proc)
            raise
        sink.seek(0)
        return code, sink.read(), expired


def _kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        proc.kill()
    proc.wait()


def _stop_groups(groups: List[int]) -> None:
    """Stops whatever the repo's commands left running in their groups (a `pre` server, a `cmd &`)."""
    for pgid in groups:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


def _worktree_cwd(repo_path: Path, subdir: str, wt: Path) -> Path:
    top = runmod._toplevel(repo_path)
    try:
        rel = repo_path.resolve().relative_to(top)
    except ValueError:
        rel = Path("")
    return wt / rel / subdir


def _link_deps(source_root: Path, target_root: Path, dirs: List[str], chunks: _Chunks) -> None:
    for name in dirs:
        src, dst = source_root / name, target_root / name
        if not os.path.lexists(src):
            chunks.add(f"symlink {name}", f"skipped: {src} does not exist\n".encode("utf-8"))
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if os.path.lexists(dst):
            continue
        os.symlink(src, dst)
        chunks.add(f"symlink {name}", f"{dst} -> {src}\n".encode("utf-8"))


def _save_result(run: Path, alias: str, result: dict) -> None:
    with runmod.transaction(run) as manifest:
        manifest["baseline"].setdefault(alias, {})["result"] = result


def _repo_and_plan(manifest: dict, alias: str) -> Tuple[dict, dict]:
    repo = next((r for r in manifest["repos"] if r["alias"] == alias), None)
    if repo is None:
        raise runmod.UsageError(f"unknown alias {alias!r}; expected one of "
                                f"{', '.join(r['alias'] for r in manifest['repos'])}")
    plan = (manifest["baseline"].get(alias) or {}).get("plan")
    if not isinstance(plan, dict):
        raise runmod.UsageError(f"{alias} has no baseline plan; run `ia.py detect --run <dir>` first")
    return repo, plan


def _run_coverage(cmd: List[str], cwd: Path, env: Dict[str, str], deadline: float, timeout: int,
                  chunks: _Chunks, groups: Optional[List[int]] = None) -> Tuple[Optional[float], str]:
    """Runs the coverage command as a separate, non-fatal step: (coverage %, error or "")."""
    label = " ".join(cmd)
    try:
        code, out, expired = _exec(cmd, cwd, env, deadline, groups)
    except OSError as exc:  # missing, not executable, wrong format: the command never ran
        error = f"could not start `{label}`: {exc}"
        chunks.add(label, (error + "\n").encode("utf-8"))
        return None, error
    chunks.add(label, out)
    if expired:
        return None, f"`{label}` timed out after {timeout}s"
    coverage = parse_summary(out.decode("utf-8", errors="replace"))["coverage"]
    if coverage is None and code != 0:
        return None, f"coverage command `{label}` exited {code}"
    if coverage is None:
        return None, f"coverage command `{label}` printed no coverage total"
    return coverage, ""


def run_baseline(run: Path, alias: str, timeout: int) -> dict:
    """Runs the suite of `alias` at its pinned sha in a throwaway worktree and records the result."""
    run = Path(run)
    manifest = runmod.load(run)
    repo, plan = _repo_and_plan(manifest, alias)
    test_cmd = plan.get("test_cmd")
    if not test_cmd:
        result = _empty_result()
        _save_result(run, alias, result)
        return result
    repo_path = Path(repo["path"])
    env = {**os.environ, **BASE_ENV, **{str(k): str(v) for k, v in (plan.get("env") or {}).items()}}
    chunks = _Chunks()
    deadline = time.monotonic() + timeout
    tmp = Path(tempfile.mkdtemp(prefix="ia-baseline-"))
    wt = tmp / "wt"
    error = ""
    exit_code: Optional[int] = None
    timed_out = False
    ran_suite = False
    added = False
    suite_text = ""
    coverage: Optional[float] = None
    coverage_error = ""
    junit: Optional[dict] = None
    groups: List[int] = []
    try:
        runmod._git(repo_path, "worktree", "add", "--detach", str(wt), repo["sha"])
        added = True
        cwd = _worktree_cwd(repo_path, repo["subdir"], wt)
        deps = plan.get("deps", "none")
        if deps == "symlink":
            _link_deps(repo_path / repo["subdir"], cwd, list(plan.get("deps_dirs") or []), chunks)
        steps: List[Tuple[str, List[str]]] = []
        if deps == "install" and plan.get("install_cmd"):
            steps.append(("install", list(plan["install_cmd"])))
        steps += [("pre", list(cmd)) for cmd in (plan.get("pre") or [])]
        steps.append(("suite", list(test_cmd)))
        for kind, cmd in steps:
            try:
                code, out, expired = _exec(cmd, cwd, env, deadline, groups)
            except OSError as exc:  # missing, not executable, wrong format: the command never ran
                error = f"could not start `{' '.join(cmd)}`: {exc}"
                chunks.add(" ".join(cmd), (error + "\n").encode("utf-8"))
                break
            chunks.add(" ".join(cmd), out)
            if expired:
                timed_out = True
                error = f"`{' '.join(cmd)}` timed out after {timeout}s"
                break
            if kind == "suite":
                exit_code, ran_suite = code, True
                suite_text = out.decode("utf-8", errors="replace")
            elif code != 0:
                error = f"{kind} command `{' '.join(cmd)}` exited {code}"
                exit_code = code
                break
        if ran_suite and plan.get("junit"):  # read before the worktree goes
            junit = parse_junit(cwd, list(plan["junit"]))
        cov_cmd = list(plan.get("coverage_cmd") or [])
        if ran_suite and cov_cmd:
            counts = junit or parse_summary(suite_text)
            if counts["failed"] == 0 and counts["total"] is not None:
                coverage, coverage_error = _run_coverage(cov_cmd, cwd, env, deadline, timeout, chunks, groups)
            else:
                coverage_error = "skipped: suite failing"
    finally:
        _stop_groups(groups)  # after suite and coverage, so a `pre` server lives as long as they need it
        if added:
            subprocess.run(["git", "worktree", "remove", "--force", str(wt)], cwd=str(repo_path),
                           capture_output=True, stdin=subprocess.DEVNULL)
        subprocess.run(["git", "worktree", "prune"], cwd=str(repo_path), capture_output=True,
                       stdin=subprocess.DEVNULL)
        shutil.rmtree(tmp, ignore_errors=True)
    text = chunks.text()
    out_rel = f"outputs/baseline-{alias}.txt"
    (run / "outputs").mkdir(exist_ok=True)
    from . import hygiene  # local: keep the import graph acyclic
    (run / out_rel).write_text(hygiene.mask_text(text), encoding="utf-8", errors="replace")
    parsed = parse_summary(suite_text) if ran_suite else {}
    if junit:
        parsed.update({k: junit[k] for k in ("passed", "failed", "total", "runner")})
    if ran_suite:
        parsed["coverage"] = coverage if coverage is not None else parsed.get("coverage")
    result = _empty_result(output=out_rel, exit_code=exit_code, timed_out=timed_out, measured=ran_suite, **parsed)
    if ran_suite:
        result["parsed"] = result["passed"] is not None
    if junit:
        result["junit_files"] = junit["files"]
        if junit["skipped_files"]:
            result["junit_skipped"] = junit["skipped_files"]
    if error:
        result["error"] = error
    if coverage_error:
        result["coverage_error"] = coverage_error
    _save_result(run, alias, result)
    return result


def _relative_glob(pattern: str) -> bool:
    return bool(pattern) and not pattern.startswith("/") and ".." not in pattern.split("/")


def _strs(v: object) -> bool:
    return isinstance(v, list) and all(isinstance(x, str) for x in v)


_SHAPES = {
    "env": lambda v: isinstance(v, dict) and all(isinstance(k, str) and isinstance(x, str) for k, x in v.items()),
    "pre": lambda v: isinstance(v, list) and all(_strs(c) for c in v),
    "test_cmd": lambda v: v is None or _strs(v),
    "coverage_cmd": lambda v: v is None or _strs(v),
    "install_cmd": lambda v: v is None or _strs(v),
    "junit": lambda v: _strs(v) and all(_relative_glob(g) for g in v),
    "deps_dirs": _strs,
    "measure": _strs,
    "measured": lambda v: isinstance(v, bool),
}
_SHAPE_HELP = {
    "env": "an object of strings", "pre": "a list of lists of strings", "test_cmd": "a list of strings or null",
    "coverage_cmd": "a list of strings or null", "install_cmd": "a list of strings or null",
    "junit": "a list of globs relative to the suite folder, without '..'",
    "deps_dirs": "a list of strings", "measure": "a list of strings", "measured": "true or false",
}


def parse_pairs(alias_and_pairs: List[str]) -> Tuple[str, Dict[str, object]]:
    alias, pairs = alias_and_pairs[0], alias_and_pairs[1:]
    if not pairs:
        raise runmod.UsageError("--set expects ALIAS KEY=VALUE [KEY=VALUE ...]")
    values: Dict[str, object] = {}
    for pair in pairs:
        key, sep, raw = pair.partition("=")
        if not sep or not key:
            raise runmod.UsageError(f"--set expects KEY=VALUE, got {pair!r}")
        if key not in PLAN_KEYS:
            raise runmod.UsageError(f"unknown plan key {key!r}; expected one of {', '.join(PLAN_KEYS)}")
        try:
            value = json.loads(raw)
        except ValueError:
            value = raw
        if key == "deps" and value not in DEPS_MODES:
            raise runmod.UsageError(f"deps must be one of {', '.join(DEPS_MODES)}, got {raw!r}")
        if not _SHAPES.get(key, lambda v: True)(value):
            raise runmod.UsageError(f"{key} has the wrong shape ({_SHAPE_HELP[key]}), got {raw!r}")
        values[key] = value
    return alias, values


def set_plan(run: Path, alias: str, values: Dict[str, object]) -> dict:
    with runmod.transaction(Path(run)) as manifest:
        _, plan = _repo_and_plan(manifest, alias)
        plan.update(values)
        edited = [k for k in plan.get("edited") or [] if isinstance(k, str)]
        plan["edited"] = edited + [k for k in values if k not in edited]
    return plan
