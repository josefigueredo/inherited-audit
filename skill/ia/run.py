"""The run manifest: the resumable state every ia command reads."""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import sys
import subprocess
import tempfile
from datetime import date
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

STEPS: Tuple[str, ...] = ("baseline", "correctness", "proof", "tests", "quality", "contrast", "verify", "filter",
                          "prose", "hygiene", "render")
STATES: Tuple[str, ...] = ("pending", "in_progress", "done", "skipped")
VERDICTS: Tuple[str, ...] = ("candidate", "confirmed", "discarded", "blocked")
SUPPORTED_VERSION = 1
HOSTS: Tuple[str, ...] = ("claude-code", "cursor", "unknown")
SYSTEM_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class RunError(Exception):
    """The command found a problem with the run or the repos (exit 1)."""


class UsageError(RunError):
    """The arguments are wrong (exit 2)."""


class ToolError(RunError):
    """An external tool failed or is missing (exit 3)."""


LOCK_NAME = ".ia.lock"
_HELD: Dict[str, int] = {}


@contextlib.contextmanager
def run_lock(run: Path) -> Iterator[None]:
    """Exclusive lock on the run dir for a read-modify-write: parallel subagents call ia on the same run.

    Reentrant inside one process (flock on a second descriptor of the same file would block on itself).
    """
    key = str(Path(run).resolve())
    if _HELD.get(key):
        _HELD[key] += 1
        try:
            yield
        finally:
            _HELD[key] -= 1
        return
    path = Path(key) / LOCK_NAME
    try:
        fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o600)
    except OSError as exc:
        raise RunError(f"cannot lock the run dir {key}: {exc}")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        _HELD[key] = 1
        try:
            yield
        finally:
            _HELD.pop(key, None)
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def atomic_write(path: Path, text: str) -> None:
    """Writes through a tmp file unique to this writer, then renames it over `path`."""
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, str(path))
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True)
    except (OSError, ValueError) as exc:
        raise ToolError(f"git is not available: {exc}")
    if check and result.returncode != 0:
        raise ToolError(f"git {' '.join(args)} failed in {repo}: {result.stderr.strip()}")
    return result


def parse_repo_spec(spec: str) -> Tuple[str, Path, str]:
    """ALIAS=PATH[:SUBDIR]: split on the first '=', then on the last ':' if the path part exists."""
    alias, sep, rest = spec.partition("=")
    if not sep or not alias or not rest:
        raise UsageError(f"--repo expects ALIAS=PATH[:SUBDIR], got {spec!r}")
    path_part, subdir = rest, ""
    head, colon, tail = rest.rpartition(":")
    if colon and tail and head and Path(head).expanduser().exists():
        path_part, subdir = head, tail
    return alias, Path(path_part).expanduser().resolve(), subdir


def _hygiene():
    from . import hygiene  # local: hygiene imports this module; it owns the single credential rule
    return hygiene


def normalise_remote(url: str) -> str:
    """https-style remote without `.git`, trailing slash or embedded credentials."""
    url = url.strip()
    if not url:
        return ""
    m = re.match(r"^(?:ssh://)?git@([^:/]+)[:/](.+)$", url)
    if m:
        url = f"https://{m.group(1)}/{m.group(2)}"
    url = _hygiene().strip_userinfo(url)
    if url.endswith(".git"):
        url = url[:-4]
    return url.rstrip("/")


def remote_had_credentials(raw: str) -> bool:
    """True when the raw remote URL carries userinfo (anything but the plain `git@host` ssh form)."""
    return _hygiene().has_credentials(raw.strip())


def _raw_remote(repo: Path) -> str:
    result = _git(repo, "remote", "get-url", "origin", check=False)
    return result.stdout if result.returncode == 0 else ""


def remote_of(repo: Path) -> str:
    return normalise_remote(_raw_remote(repo))


def _toplevel(repo: Path) -> Path:
    return Path(_git(repo, "rev-parse", "--show-toplevel").stdout.strip()).resolve()


def _check_clean(alias: str, repo: Path) -> None:
    lines = [ln for ln in _git(repo, "status", "--porcelain").stdout.splitlines() if ln.strip()]
    if lines:
        raise RunError(f"{alias} ({repo}) has uncommitted changes; commit or stash them first:\n  "
                       + "\n  ".join(lines))


def _committable_reason(out: Path, tops: List[Tuple[str, Path]]) -> Optional[str]:
    for alias, top in tops:
        try:
            out.relative_to(top)
        except ValueError:
            continue
        probe = out / "manifest.json"
        if _git(top, "check-ignore", "-q", str(probe), check=False).returncode != 0:
            return (f"output dir {out} is inside {alias} ({top}) and not ignored by git: it could be "
                    "committed; choose a dir outside the repo or add it to .gitignore")
    return None


def committable_reason(out: Path, manifest: dict) -> Optional[str]:
    """Why `out` could end up committed to one of the manifest's repos, or None if it cannot."""
    tops = []
    for repo in manifest.get("repos") or []:
        path = Path(repo["path"])
        if path.is_dir():
            tops.append((repo["alias"], _toplevel(path)))
    return _committable_reason(Path(out).resolve(), tops)


def _check_out_not_committable(out: Path, tops: List[Tuple[str, Path]]) -> None:
    reason = _committable_reason(out, tops)
    if reason:
        raise RunError(reason)


def init_run(system: str, repos: List[Tuple[str, Path, str]], out: Optional[Path], lang: str,
             publish: bool, host: str) -> Path:
    if not repos:
        raise UsageError("at least one --repo is required")
    aliases = [alias for alias, _, _ in repos]
    dupes = sorted({a for a in aliases if aliases.count(a) > 1})
    if dupes:
        raise UsageError(f"duplicate repo alias: {', '.join(dupes)}")
    if host not in HOSTS:
        raise UsageError(f"unknown host {host!r}; expected one of {', '.join(HOSTS)}")
    if not SYSTEM_RE.match(system or ""):
        raise UsageError(f"--system {system!r} must match {SYSTEM_RE.pattern} (it is used in file names)")
    today = date.today().isoformat()
    entries, tops = [], []
    for alias, path, subdir in repos:
        path = Path(path).resolve()
        if not path.is_dir():
            raise RunError(f"{alias}: {path} is not a directory")
        top = _toplevel(path)
        _check_clean(alias, path)
        rel = path.relative_to(top).as_posix() if path != top else ""
        folded = "/".join(p for p in (rel, subdir.strip("/")) if p)
        entries.append({"alias": alias, "path": str(top), "subdir": folded,
                        "sha": _git(path, "rev-parse", "HEAD").stdout.strip(), "remote": remote_of(path),
                        "remote_had_credentials": remote_had_credentials(_raw_remote(path))})
        tops.append((alias, top))
    taken = set(aliases)
    for top in dict.fromkeys(e["path"] for e in entries):
        mine = [e for e in entries if e["path"] == top]
        if all(e["subdir"] for e in mine):
            name, n = "ROOT", 1
            while name in taken:
                n += 1
                name = f"ROOT{n}"
            taken.add(name)
            entries.append({"alias": name, "path": top, "subdir": "", "sha": mine[0]["sha"],
                            "remote": mine[0]["remote"],
                            "remote_had_credentials": mine[0]["remote_had_credentials"], "root": True})
    run_dir = (Path(out).expanduser() if out else tops[0][1].parent / f"{system}-inherited-audit" / today).resolve()
    if (run_dir / "manifest.json").exists():
        raise RunError(f"a run already exists in {run_dir}; use `ia status --run {run_dir}` to resume it, "
                       "or pick another --out")
    _check_out_not_committable(run_dir, tops)
    (run_dir / "findings").mkdir(parents=True, exist_ok=True)
    (run_dir / "outputs").mkdir(exist_ok=True)
    manifest = {"version": SUPPORTED_VERSION, "system": system, "lang": lang, "host": host, "created": today,
                "options": {"fix": False, "publish": publish}, "repos": entries,
                "steps": {s: "pending" for s in STEPS}, "tools": {}, "workers": {}, "baseline": {},
                "sections": {"correctness": [], "quality": []}}
    save(run_dir, manifest)
    return run_dir


_WARNED_LEGACY_FIX: set = set()


def load(run: Path) -> dict:
    path = Path(run) / "manifest.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise RunError(f"no manifest.json in {run}")
    except (OSError, ValueError) as exc:
        raise RunError(f"cannot read {path}: {exc}")
    version = manifest.get("version") if isinstance(manifest, dict) else None
    if not isinstance(version, int):
        raise RunError(f"{path} has no integer version")
    if version > SUPPORTED_VERSION:
        raise RunError(f"{path} is version {version}, newer than the {SUPPORTED_VERSION} this ia supports; "
                       "update ia instead of resuming it")
    options = manifest.get("options")
    if isinstance(options, dict) and options.get("fix") is True:
        options["fix"] = False
        if str(path) not in _WARNED_LEGACY_FIX:
            _WARNED_LEGACY_FIX.add(str(path))
            print(f"warning: {path} has options.fix=true; fixes are no longer applied, the run stops at the red "
                  "test and the written proposal (treated as false)", file=sys.stderr)
    return manifest


def save(run: Path, manifest: dict) -> None:
    with run_lock(run):
        atomic_write(Path(run) / "manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")


@contextlib.contextmanager
def transaction(run: Path) -> Iterator[dict]:
    """load -> change -> save under the run lock, so a parallel ia call cannot overwrite the change.

    Nothing is saved when the block raises."""
    with run_lock(run):
        manifest = load(run)
        yield manifest
        save(run, manifest)


def set_step(run: Path, step: str, state: str, force_open: Optional[str] = None) -> None:
    if step not in STEPS:
        raise UsageError(f"unknown step {step!r}; expected one of {', '.join(STEPS)}")
    if state not in STATES:
        raise UsageError(f"unknown state {state!r}; expected one of {', '.join(STATES)}")
    if force_open is not None and not force_open.strip():
        raise UsageError("--force-open needs a reason")
    with transaction(run) as manifest:
        if state == "done":
            from . import coverage  # local: coverage imports this module
            coverage.guard_step(manifest, step, force_open.strip() if force_open is not None else None)
        manifest["steps"][step] = state


def next_step(manifest: dict) -> Optional[str]:
    steps = manifest["steps"]
    for step in STEPS:
        if steps.get(step, "pending") not in ("done", "skipped"):
            return step
    return None


def verdict_counts(run: Path) -> Dict[str, int]:
    counts = {v: 0 for v in VERDICTS}
    folder = Path(run) / "findings"
    if folder.is_dir():
        for path in sorted(folder.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise RunError(f"cannot read finding {path}: {exc}")
            if not isinstance(data, dict):
                raise RunError(f"finding {path} is not a JSON object")
            verdict = data.get("verdict")
            if verdict in counts:
                counts[verdict] += 1
    return counts


def _mask_remote(remote: str) -> str:
    return _hygiene().mask_line(remote or "")


def status_text(run: Path) -> str:
    manifest = load(run)
    lines = [f"system: {manifest['system']}  created: {manifest['created']}  lang: {manifest['lang']}  "
             f"host: {manifest['host']}"]
    for repo in manifest["repos"]:
        lines.append(f"repo {repo['alias']}: {repo['sha']}  {_mask_remote(repo['remote']) or '(no remote)'}")
    lines.append("steps:")
    for step in STEPS:
        lines.append(f"  {step}: {manifest['steps'].get(step, 'pending')}")
    counts = verdict_counts(run)
    lines.append("findings: " + ", ".join(f"{v}: {n}" for v, n in counts.items()))
    lines.append(f"next: {next_step(manifest) or '(none, all steps done)'}")
    return "\n".join(lines)


def _str_list(v: object) -> bool:
    return isinstance(v, list) and all(isinstance(x, str) for x in v)


SETTABLE = {
    "host": (lambda v: v in HOSTS, "one of " + ", ".join(HOSTS)),
    "lang": (lambda v: isinstance(v, str) and bool(v.strip()), "a non-empty string"),
    "options.publish": (lambda v: isinstance(v, bool), "true or false"),
    "sections.correctness": (_str_list, "a list of strings"),
    "sections.quality": (_str_list, "a list of strings"),
    "strengths": (_str_list, "a list of strings"),
    "author_model": (lambda v: isinstance(v, str) and bool(v.strip()), "a non-empty string (the model that wrote the findings)"),
}
_TESTS_BRANCH = re.compile(r"^baseline\.([^.]+)\.tests_branch$")
_RESULT_KEY = re.compile(r"^baseline\.([^.]+)\.result\.(passed|failed|total|coverage|runner|measured)$")
_STRING_KEYS = ("lang", "author_model")
_WORKER_AVAILABLE = re.compile(r"^workers\.([^.]+)\.([^.]+)\.(.+)\.available$")


def _count(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def _coverage(v: object) -> bool:
    return v is None or (isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 100)


_RESULT_SHAPES = {
    "passed": (_count, "an integer >= 0"), "failed": (_count, "an integer >= 0"),
    "total": (_count, "an integer >= 0"), "coverage": (_coverage, "a number from 0 to 100, or null"),
    "runner": (lambda v: isinstance(v, str) and bool(v.strip()), "a non-empty string"),
    "measured": (lambda v: isinstance(v, bool), "true or false"),
}


def measured_repos(manifest: dict) -> List[dict]:
    """The repos with a suite to run: every one but the synthetic ROOT alias, which only exists so root files can be cited."""
    return [r for r in manifest.get("repos") or [] if not r.get("root")]


def baselines_closed(manifest: dict) -> bool:
    return all(baseline_closed(manifest, r["alias"]) for r in measured_repos(manifest))


def baseline_closed(manifest: dict, alias: str) -> bool:
    """A repo's baseline is closed by a parsed run result or by numbers recorded by hand (`result.source`); a repo
    whose plan has no `test_cmd` stays open until a manual result is set (`total=0` when there is no runner)."""
    result = (manifest.get("baseline", {}).get(alias) or {}).get("result")
    if not isinstance(result, dict):
        return False
    if result.get("source") == "manual":
        return any(result.get(k) is not None for k in ("passed", "failed", "total"))
    if result.get("measured"):
        return result.get("parsed", True) is not False
    # no suite ran (no test_cmd, or `pre` failed): only a result recorded by hand closes it
    return False


def _worker_row(manifest: dict, host: str, step: str, worker: str) -> Optional[dict]:
    rows = (manifest.get("workers") or {}).get(host)
    for r in rows if isinstance(rows, list) else []:
        if isinstance(r, dict) and r.get("step") == step and r.get("worker") == worker:
            return r
    return None


def _check_worker_row(manifest: dict, host: str, step: str, worker: str) -> None:
    workers = manifest.get("workers")
    if not isinstance(workers, dict) or not workers:
        raise UsageError("manifest.workers is empty: run `ia.py detect` first")
    if host not in workers:
        raise UsageError(f"unknown host {host!r}; expected one of {', '.join(workers)}")
    if not isinstance(workers[host], list):
        raise UsageError(f"manifest.workers.{host} is not a list: run `ia.py detect` again")
    steps = sorted({r.get("step") for r in workers[host] if isinstance(r, dict)})
    if step not in steps:
        raise UsageError(f"unknown step {step!r} for host {host}; expected one of {', '.join(map(str, steps))}")
    if _worker_row(manifest, host, step, worker) is None:
        names = [r["worker"] for r in workers[host] if isinstance(r, dict) and r.get("step") == step]
        raise UsageError(f"unknown worker {worker!r} for {host}/{step}; expected one of {', '.join(names)}")


def parse_set_pairs(manifest: dict, pairs: List[str]) -> List[Tuple[str, object]]:
    """Validates every KEY=VALUE (JSON value, or the raw string when it is not JSON) before anything is written."""
    if not pairs:
        raise UsageError("set expects KEY=VALUE [KEY=VALUE ...]")
    aliases = [r["alias"] for r in manifest.get("repos") or []]
    out: List[Tuple[str, object]] = []
    for pair in pairs:
        key, sep, raw = pair.partition("=")
        if not sep or not key:
            raise UsageError(f"set expects KEY=VALUE, got {pair!r}")
        m, rm = _TESTS_BRANCH.match(key), _RESULT_KEY.match(key)
        wm = _WORKER_AVAILABLE.match(key)
        if key in _STRING_KEYS or bool(m) or (rm and rm.group(2) == "runner"):
            value: object = raw  # string-typed: never JSON-parsed, so tests_branch=2024 stays "2024"
        else:
            try:
                value = json.loads(raw)
            except ValueError:
                value = raw
        if wm:
            _check_worker_row(manifest, wm.group(1), wm.group(2), wm.group(3))
            if not isinstance(value, bool):
                raise UsageError(f"{key} must be true or false, got {raw!r}")
        elif m:
            if m.group(1) not in aliases:
                raise UsageError(f"unknown alias {m.group(1)!r}; expected one of {', '.join(aliases)}")
            if not isinstance(value, str) or not value.strip():
                raise UsageError(f"{key} must be a branch name, got {raw!r}")
        elif rm:
            if rm.group(1) not in aliases:
                raise UsageError(f"unknown alias {rm.group(1)!r}; expected one of {', '.join(aliases)}")
            check, shape = _RESULT_SHAPES[rm.group(2)]
            if not check(value):
                raise UsageError(f"{key} must be {shape}, got {raw!r}")
        elif key in SETTABLE:
            check, shape = SETTABLE[key]
            if not check(value):
                raise UsageError(f"{key} must be {shape}, got {raw!r}")
        else:
            raise UsageError(f"{key!r} cannot be set; settable keys: {', '.join(SETTABLE)}, "
                             "baseline.<ALIAS>.tests_branch, baseline.<ALIAS>.result.passed|failed|total|coverage|runner|measured, "
                             "workers.<host>.<step>.<worker>.available "
                             "(plan keys: `ia.py baseline --set`)")
        out.append((key, value))
    return out


def set_keys(run: Path, pairs: List[str]) -> List[str]:
    """Sets manifest-level keys in one atomic save; returns the keys set."""
    with transaction(run) as manifest:
        return _set_keys(manifest, pairs)


def _set_keys(manifest: dict, pairs: List[str]) -> List[str]:
    parsed = parse_set_pairs(manifest, pairs)
    for key, value in parsed:
        m = _TESTS_BRANCH.match(key)
        wm = _WORKER_AVAILABLE.match(key)
        if wm:
            _worker_row(manifest, wm.group(1), wm.group(2), wm.group(3))["available"] = value
        elif m:
            entry = manifest.setdefault("baseline", {}).setdefault(m.group(1), {})
            entry["tests_branch"] = value
        elif _RESULT_KEY.match(key):
            rm = _RESULT_KEY.match(key)
            entry = manifest.setdefault("baseline", {}).setdefault(rm.group(1), {})
            result = entry.get("result")
            if not isinstance(result, dict):
                result = entry["result"] = {}
            result[rm.group(2)] = value
            result["source"] = "manual"
        elif "." in key:
            head, tail = key.split(".", 1)
            manifest.setdefault(head, {})[tail] = value
        else:
            manifest[key] = value
    if any(_RESULT_KEY.match(k) for k, _ in parsed) and baselines_closed(manifest):
        manifest["steps"]["baseline"] = "done"
    return [k for k, _ in parsed]
