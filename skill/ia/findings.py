"""The finding schema: validate, add, update and list `findings/<id>.json`."""
from __future__ import annotations

import copy
import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

from . import run as runmod
from .run import RunError, UsageError

REPORTS = ("correctness", "quality")
PREFIX = {"correctness": "C", "quality": "Q"}
ENUMS: Dict[str, tuple] = {
    "report": REPORTS,
    "dimension": ("bug", "race", "distributed", "security", "supply-chain", "container", "architecture", "code",
                  "resilience", "docs", "tests"),
    "verdict": ("candidate", "confirmed", "discarded", "blocked"),
    "severity": ("high", "medium", "low"),
    "confidence": ("execution", "docs", "unverified"),
    "effort": ("S", "M", "L", ""),
    "exclude": ("refactor", "feature", "tooling", "doubtful", "no-code", "duplicate", ""),
}
CONTRAST_VERDICTS = ("agree", "refute", "unsure", "")
CONTRAST_SCOPES = ("severity", "finding", "")
# `fix` is written by inherited-fix (`ia.py fix`), never by the audit; absent on a finding nobody tried to fix.
FIX_STATUSES = ("", "started", "moot", "blocked", "declined", "done")
FIX_CLAIMS = ("targeted", "no_new_risk", "minimal")
CLAIM_STATES = ("CONFIDENT", "NOT_CONFIDENT", "UNSURE")
REQUIRED = ("id", "report", "category", "dimension", "title", "verdict", "severity", "confidence", "source",
            "what_happens", "evidence")
# Correctness dimensions no code test can express: confirmed by a command and its saved output, not a red branch.
NON_CODE_DIMENSIONS = ("supply-chain", "container")
# A security finding is proven the same way when it lives only in history (every cite carries `@commit`) or when a
# scanner verified it (config, CI or secrets: `measurement.tool` set).
ID_RE = re.compile(r"^([CQ])-(\d{2,})$")

DEFAULTS = {
    "reason": "", "fix_summary": "", "suggestion": "", "effort": "", "measurement": {"tool": "", "value": ""},
    "branch": "", "base": "", "sha_test": "", "sha_fix": "", "prod_files": [], "tests": [], "red_reason": "",
    "outputs": {"red": "", "green": "", "suite": ""},
    "contrast": {"model": "", "same_family": False, "verdict": "", "scope": "", "rebutted": False, "rebuttal": ""},
    "exclude": "", "duplicate_of": "", "publish_repo": "", "shown": None,
    "audience": {"title": "", "what_happens": "", "fix_summary": ""},
}


class FindingError(RunError):
    """A finding does not follow the schema (exit 1); `problems` lists each one."""

    def __init__(self, problems: List[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = list(problems)


def _blank(value: object) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _history_only(f: dict) -> bool:
    """True when the finding has evidence and every cite points into history (`ALIAS/path@commit`)."""
    from .cites import parse_cite  # local, like hygiene: keeps the import graph flat

    evidence = f.get("evidence") if isinstance(f.get("evidence"), list) else []
    if not evidence:
        return False
    for item in evidence:
        try:
            if not isinstance(item, dict) or not parse_cite(str(item.get("cite") or ""))[2]:
                return False
        except ValueError:
            return False
    return True


def proven_by_command(f: dict) -> bool:
    """A confirmed correctness finding whose proof is a command and its saved output instead of a red branch."""
    if f.get("dimension") in NON_CODE_DIMENSIONS:
        return True
    if f.get("dimension") != "security":
        return False
    measurement = f.get("measurement") if isinstance(f.get("measurement"), dict) else {}
    return _history_only(f) or not _blank(measurement.get("tool"))


def _non_code_execution_problems(f: dict) -> List[str]:
    """A finding confirmed by running a command (supply-chain, container, scanner-verified or history-only
    security): the command and its saved output."""
    problems: List[str] = []
    measurement = f.get("measurement") if isinstance(f.get("measurement"), dict) else {}
    if _blank(measurement.get("tool")):
        problems.append("missing required field: measurement.tool (the command that was run, for a confirmed "
                        f"{f.get('dimension')} finding with execution confidence)")
    outputs = f.get("outputs") if isinstance(f.get("outputs"), dict) else {}
    evidence = f.get("evidence") if isinstance(f.get("evidence"), list) else []
    noted = any(isinstance(e, dict) and "outputs/" in str(e.get("note", "")) for e in evidence)
    if _blank(outputs.get("suite")) and not noted:
        problems.append("missing required field: outputs.suite, or an evidence note naming the saved output under "
                        f"outputs/ (confirmed {f.get('dimension')} finding with execution confidence)")
    return problems


def validate(f: dict) -> List[str]:
    if not isinstance(f, dict):
        return ["finding must be a JSON object"]
    problems: List[str] = []
    for name in REQUIRED:
        if name not in f or _blank(f[name]):
            problems.append(f"missing required field: {name}")
    for name, allowed in ENUMS.items():
        if name in f and f[name] not in allowed and not (name in REQUIRED and _blank(f[name])):
            problems.append(f"{name}: {f[name]!r} is not one of {', '.join(repr(a) for a in allowed)}")
    contrast = f.get("contrast")
    if isinstance(contrast, dict) and contrast.get("verdict", "") not in CONTRAST_VERDICTS:
        problems.append(f"contrast.verdict: {contrast.get('verdict')!r} is not one of "
                        + ", ".join(repr(a) for a in CONTRAST_VERDICTS))
    elif contrast is not None and not isinstance(contrast, dict):
        problems.append("contrast must be an object")
    if isinstance(contrast, dict):
        if contrast.get("scope", "") not in CONTRAST_SCOPES:
            problems.append(f"contrast.scope: {contrast.get('scope')!r} is not one of "
                            + ", ".join(repr(a) for a in CONTRAST_SCOPES))
        if not isinstance(contrast.get("rebutted", False), bool):
            problems.append("contrast.rebutted must be true or false")
        if not isinstance(contrast.get("rebuttal", ""), str):
            problems.append("contrast.rebuttal must be a string")
    fid = f.get("id")
    if isinstance(fid, str) and fid:
        m = ID_RE.match(fid)
        if not m:
            problems.append(f"id: {fid!r} must look like C-01 or Q-01")
        elif f.get("report") in PREFIX and PREFIX[f["report"]] != m.group(1):
            problems.append(f"id: {fid!r} does not match report {f['report']!r} (expected {PREFIX[f['report']]}-NN)")
    elif "id" in f and not _blank(fid):
        problems.append("id must be a string")
    evidence = f.get("evidence")
    if "evidence" in f and not _blank(evidence):
        if not isinstance(evidence, list):
            problems.append("evidence must be a list")
        else:
            for i, item in enumerate(evidence):
                if not isinstance(item, dict) or not item.get("cite"):
                    problems.append(f"evidence[{i}] needs a cite")
    if (f.get("report") == "correctness" and f.get("verdict") == "confirmed"
            and f.get("confidence") == "execution"):
        if proven_by_command(f):
            problems.extend(_non_code_execution_problems(f))
        else:
            for name in ("branch", "sha_test", "tests", "red_reason"):
                if _blank(f.get(name)):
                    problems.append(f"missing required field: {name} (confirmed correctness finding with "
                                    "execution confidence)")
    problems.extend(_duplicate_shape_problems(f))
    problems.extend(fix_problems(f.get("fix")) if "fix" in f else [])
    if not isinstance(f.get("publish_repo", ""), str):
        problems.append("publish_repo must be a string (a repo alias of the run)")
    if f.get("report") == "quality":
        for name in ("suggestion", "effort"):
            if _blank(f.get(name)):
                problems.append(f"missing required field: {name} (quality finding)")
    return problems


def fix_problems(fix: object) -> List[str]:
    """The shape of `fix`: status, extra_files, reason, and the reviewer's three claims, each with a state and
    evidence."""
    if not isinstance(fix, dict):
        return ["fix must be an object"]
    problems = []
    if fix.get("status", "") not in FIX_STATUSES:
        problems.append(f"fix.status: {fix.get('status')!r} is not one of " + ", ".join(repr(a) for a in FIX_STATUSES))
    if not isinstance(fix.get("extra_files", []), list) or not all(isinstance(p, str) and p
                                                                     for p in fix.get("extra_files", [])):
        problems.append("fix.extra_files must be a list of paths (relative to the repo, like prod_files)")
    if not isinstance(fix.get("reason", ""), str):
        problems.append("fix.reason must be a string")
    if fix.get("status") in ("blocked", "declined") and _blank(fix.get("reason")):
        problems.append(f"fix.reason is required when fix.status is {fix['status']}")
    review = fix.get("review")
    if review is None:
        return problems
    if not isinstance(review, dict):
        return problems + ["fix.review must be an object"]
    for key in ("model", "sha"):
        if key in review and not isinstance(review[key], str):
            problems.append(f"fix.review.{key} must be a string")
    claims = review.get("claims", {})
    if not isinstance(claims, dict):
        return problems + ["fix.review.claims must be an object"]
    for name, claim in claims.items():
        if name not in FIX_CLAIMS:
            problems.append(f"fix.review.claims: {name!r} is not one of " + ", ".join(repr(a) for a in FIX_CLAIMS))
        elif not isinstance(claim, dict) or claim.get("state") not in CLAIM_STATES:
            problems.append(f"fix.review.claims.{name}.state must be one of " + ", ".join(CLAIM_STATES))
        elif not isinstance(claim.get("evidence"), str) or not claim["evidence"].strip():
            problems.append(f"fix.review.claims.{name}.evidence must say what in the diff or the outputs backs it")
    return problems


DUPLICATE_HINT = "set both in one call: `finding set ID exclude=duplicate duplicate_of=<id>`"


def _duplicate_shape_problems(f: dict) -> List[str]:
    """`exclude=duplicate` and `duplicate_of` go together, and a finding is never a duplicate of itself."""
    target = f.get("duplicate_of") or ""
    if f.get("exclude") == "duplicate":
        if _blank(target):
            return [f"missing required field: duplicate_of (exclude=duplicate); {DUPLICATE_HINT}; it names the "
                    "finding this one is the same as"]
        if not isinstance(target, str) or not ID_RE.match(target):
            return [f"duplicate_of: {target!r} must be a finding id (C-01, Q-01)"]
        if target == f.get("id"):
            return [f"duplicate_of: {target} is the finding itself"]
    elif not _blank(target):
        return [f"duplicate_of is set but exclude is not duplicate; {DUPLICATE_HINT}"]
    return []


def duplicate_problems(f: dict, others: Dict[str, dict]) -> List[str]:
    """Problems of a duplicate against the run: its target exists, is in the same report and is not a duplicate."""
    if f.get("exclude") != "duplicate" or _duplicate_shape_problems(f):
        return []
    target = others.get(f.get("duplicate_of"))
    if target is None:
        return [f"duplicate_of: no finding {f['duplicate_of']} in the run"]
    if target.get("report") != f.get("report"):
        return [f"duplicate_of: {f['duplicate_of']} is in report {target.get('report')!r}, not {f.get('report')!r}"]
    if target.get("exclude") == "duplicate":
        return [f"duplicate_of: {f['duplicate_of']} is itself a duplicate of {target.get('duplicate_of')}; point to "
                f"{target.get('duplicate_of')} instead"]
    return []


def publish_repo_problems(f: dict, manifest: dict) -> List[str]:
    """`publish_repo`, when set, names one of the run's repo aliases."""
    alias = f.get("publish_repo") or ""
    aliases = [r["alias"] for r in manifest.get("repos") or []]
    if not isinstance(alias, str) or not alias or alias in aliases:
        return []
    return [f"publish_repo: {alias!r} is not a repo of this run ({', '.join(aliases)})"]


def _target_of(run: Path, f: dict) -> Dict[str, dict]:
    """The finding `f` says it duplicates, read from the run (empty when there is none)."""
    target = f.get("duplicate_of")
    if f.get("exclude") != "duplicate" or not isinstance(target, str) or not ID_RE.match(target):
        return {}
    path = _path(run, target)
    return {target: _read(path)} if path.is_file() else {}


def _folder(run: Path) -> Path:
    return Path(run) / "findings"


def _path(run: Path, fid: str) -> Path:
    return _folder(run) / f"{fid}.json"


def _write(run: Path, f: dict) -> None:
    _folder(run).mkdir(parents=True, exist_ok=True)
    runmod.atomic_write(_path(run, f["id"]), json.dumps(f, indent=2, ensure_ascii=False) + "\n")


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RunError(f"cannot read finding {path}: {exc}")
    if not isinstance(data, dict):
        raise RunError(f"finding {path} is not a JSON object")
    return data


def _next_id(run: Path, prefix: str) -> str:
    top = 0
    folder = _folder(run)
    if folder.is_dir():
        for path in folder.glob(f"{prefix}-*.json"):
            m = ID_RE.match(path.stem)
            if m and m.group(1) == prefix:
                top = max(top, int(m.group(2)))
    return f"{prefix}-{top + 1:02d}"


PROSE_KEYS = ("title", "what_happens", "fix_summary", "suggestion", "red_reason", "reason", "notes")
# Free text nested one level down: masked like the top-level prose.
NESTED_PROSE = {"contrast": ("note", "rebuttal"), "measurement": ("tool", "value"), "fix": ("reason",)}


def mask_prose(f: dict, warnings: Optional[List[str]] = None) -> dict:
    """`f` with every free-text field masked (secrets, key blocks, URL credentials, secret-named values); structure is
    untouched. 40-char code identifiers are kept; each field where a 40-char token was still masked is appended to
    `warnings` by its dotted name (never the token)."""
    from . import hygiene  # local: hygiene imports this module

    def mask(node: dict, key: str, name: str) -> None:
        if isinstance(node.get(key), str):
            if warnings is not None and hygiene.masked_tokens(node[key]) and name not in warnings:
                warnings.append(name)
            node[key] = hygiene.mask_text(node[key], prose=True)

    for key in PROSE_KEYS:
        mask(f, key, key)
    if isinstance(f.get("audience"), dict):
        for sub in list(f["audience"]):
            mask(f["audience"], sub, f"audience.{sub}")
    for key, subs in NESTED_PROSE.items():
        if isinstance(f.get(key), dict):
            for sub in subs:
                mask(f[key], sub, f"{key}.{sub}")
    review = f["fix"].get("review") if isinstance(f.get("fix"), dict) else None
    claims = review.get("claims") if isinstance(review, dict) else None
    for name, claim in (claims.items() if isinstance(claims, dict) else []):
        if isinstance(claim, dict):
            mask(claim, "evidence", f"fix.review.claims.{name}.evidence")
    for key in ("evidence", "tests"):
        for i, item in enumerate(f.get(key) if isinstance(f.get(key), list) else []):
            if isinstance(item, dict):
                mask(item, "note", f"{key}[{i}].note")
    return f


def _fill(f: dict) -> dict:
    out = copy.deepcopy(f)
    for key, default in DEFAULTS.items():
        if key not in out:
            out[key] = copy.deepcopy(default)
        elif isinstance(default, dict) and isinstance(out[key], dict):
            out[key] = {**copy.deepcopy(default), **out[key]}
    return out


def add(run: Path, f: dict, warnings: Optional[List[str]] = None) -> str:
    manifest = runmod.load(run)
    if not isinstance(f, dict):
        raise FindingError(["finding must be a JSON object"])
    f = copy.deepcopy(f)
    with runmod.run_lock(run):  # the id is picked and its file written under one lock
        if _blank(f.get("id")):
            prefix = PREFIX.get(f.get("report"))
            f["id"] = _next_id(run, prefix) if prefix else ""
        filled = mask_prose(_fill(f), warnings)
        problems = validate(filled)
        if not problems and _path(run, filled["id"]).exists():
            problems.append(f"id: {filled['id']} already exists")
        if not problems:
            problems = (publish_repo_problems(filled, manifest)
                        or duplicate_problems(filled, _target_of(run, filled)))
        if problems:
            raise FindingError(problems)
        _write(run, filled)
    return filled["id"]


def _id_key(f: dict):
    m = ID_RE.match(str(f.get("id", "")))
    return (m.group(1), int(m.group(2))) if m else (str(f.get("id", "")), 0)


def load_all(run: Path) -> List[dict]:
    folder = _folder(run)
    items = [_read(p) for p in sorted(folder.glob("*.json"))] if folder.is_dir() else []
    return sorted(items, key=_id_key)


def update(run: Path, fid: str, changes: dict, warnings: Optional[List[str]] = None) -> dict:
    with runmod.run_lock(run):
        return _update(run, fid, changes, warnings)


def _update(run: Path, fid: str, changes: dict, warnings: Optional[List[str]] = None) -> dict:
    path = _path(run, fid)
    if not ID_RE.match(fid or ""):
        raise FindingError([f"{fid!r} is not a finding id (C-01, Q-01)"])
    if not path.is_file():
        raise FindingError([f"no finding {fid} in {run}"])
    f = _read(path)
    for key, value in changes.items():
        parts = key.split(".")
        if parts == ["id"] and value != fid:
            raise FindingError([f"id cannot be changed ({fid})"])
        node = f
        for part in parts[:-1]:
            if not isinstance(node.get(part), dict):
                node[part] = {}
            node = node[part]
        node[parts[-1]] = value
    mask_prose(f, warnings)
    problems = (validate(f) or publish_repo_problems(f, runmod.load(run))
                or duplicate_problems(f, _target_of(run, f)))
    if problems:
        raise FindingError(problems)
    _write(run, f)
    return f


def parse_pairs(pairs: List[str]) -> dict:
    changes: dict = {}
    for pair in pairs:
        key, sep, raw = pair.partition("=")
        if not sep or not key:
            raise UsageError(f"expected KEY=VALUE, got {pair!r}")
        try:
            changes[key] = json.loads(raw)
        except ValueError:
            changes[key] = raw
    return changes


def list_lines(items: List[dict], report: Optional[str], verdict: Optional[str]) -> List[str]:
    return [f"{f['id']}\t{f.get('report', '')}\t{f.get('verdict', '')}\t{f.get('severity', '')}\t{f.get('title', '')}"
            for f in items
            if (not report or f.get("report") == report) and (not verdict or f.get("verdict") == verdict)]
