"""The owner-team filter: decide which findings are shown, and which quality ones to start with."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from . import findings as findingsmod
from . import run as runmod

SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}
EFFORT_RANK = {"S": 0, "M": 1, "L": 2}
MIN_START = 3


def refute_hides(f: dict) -> bool:
    """A refute hides only when it was about the finding itself (or the scope is empty, as on old data) and was not
    rebutted. A refute on severity already lowered the severity: the finding stays."""
    contrast = f.get("contrast") if isinstance(f.get("contrast"), dict) else {}
    return (contrast.get("verdict") == "refute" and (contrast.get("scope") or "") in ("finding", "")
            and contrast.get("rebutted") is not True)


def is_shown(f: dict) -> bool:
    if f.get("confidence") == "unverified" or refute_hides(f) or f.get("exclude") == "duplicate":
        return False
    if f.get("report") == "correctness":
        return f.get("verdict") == "confirmed" and (f.get("exclude") or "") == ""
    return f.get("verdict") != "discarded"


def apply(findings: List[dict]) -> Dict[str, Dict[str, int]]:
    counts = {r: {"shown": 0, "total": 0} for r in findingsmod.REPORTS}
    for f in findings:
        f["shown"] = is_shown(f)
        bucket = counts.get(f.get("report"))
        if bucket is not None:
            bucket["total"] += 1
            bucket["shown"] += 1 if f["shown"] else 0
            if f.get("exclude") == "duplicate":
                bucket["duplicates"] = bucket.get("duplicates", 0) + 1
    return counts


def start_here(findings: List[dict], n: int = 5) -> List[str]:
    shown = [f for f in findings if f.get("report") == "quality" and f.get("shown") is True]
    shown.sort(key=lambda f: (SEVERITY_RANK.get(f.get("severity"), 3), EFFORT_RANK.get(f.get("effort"), 3),
                              str(f.get("id"))))
    if len(shown) < MIN_START:
        return [f["id"] for f in shown]
    return [f["id"] for f in shown[:n]]


def run_filter(run: Path, n: int = 5) -> dict:
    run = Path(run)
    with runmod.run_lock(run):  # no finding may change between the counts and the `shown` writes
        return _run_filter(run, n)


def _run_filter(run: Path, n: int) -> dict:
    runmod.load(run)
    items = findingsmod.load_all(run)
    counts = apply(items)
    by_id = {f.get("id"): f for f in items}
    problems = [f"{f.get('id')}: {p}" for f in items
                for p in findingsmod.validate(f) or findingsmod.duplicate_problems(f, by_id)]
    if problems:
        raise findingsmod.FindingError(problems)
    for f in items:
        findingsmod.update(run, f["id"], {"shown": f["shown"]})
    manifest = runmod.load(run)
    manifest["filter"] = {"counts": counts, "start_here": start_here(items, n)}
    manifest["steps"]["filter"] = "done"
    runmod.save(run, manifest)
    return manifest["filter"]
