"""Rediscovery scorer: how many known findings (an answer key) did a run find again. Generic: the key is a file."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional

from . import cites as citesmod
from .run import UsageError

SLACK = 15
MIN_KEYWORD = 4  # shorter keywords collide with unrelated words
MAX_SPAN = 80  # evidence spans wider than this say "somewhere in the file" and would match anything


def _close(a: dict, b: dict, slack: int) -> bool:
    if citesmod.strip_commit(str(a.get("cite"))) != citesmod.strip_commit(str(b.get("cite"))):
        return False
    try:
        a_from, a_to, b_from, b_to = int(a["from"]), int(a["to"]), int(b["from"]), int(b["to"])
    except (KeyError, TypeError, ValueError):
        return False
    if b_to - b_from + 1 > MAX_SPAN:
        return False
    return a_from <= b_to + slack and b_from <= a_to + slack


def match(ref_item: dict, finding: dict, slack: int = SLACK) -> bool:
    """Same path and line ranges overlapping within `slack` lines, on any evidence cite; discarded never matches.

    Finding spans wider than MAX_SPAN lines are ignored. Cites are compared as written: `score` normalises them first."""
    if finding.get("verdict") == "discarded":
        return False
    return any(_close(c, e, slack) for c in ref_item.get("cites") or [] for e in finding.get("evidence") or [])


def _top_path(cite: str, dirs: Dict[str, str]) -> str:
    """ALIAS/path -> <path from the git top level>, when the alias is known; otherwise unchanged."""
    cite = citesmod.strip_commit(cite)
    alias, sep, path = cite.partition("/")
    if not sep or alias not in dirs:
        return cite
    return f"{dirs[alias]}/{path}" if dirs[alias] else path


def _normalise(cites: List[dict], dirs: Dict[str, str]) -> List[dict]:
    return [{**c, "cite": _top_path(str(c.get("cite", "")), dirs)} for c in cites or []]


def repo_dirs(repos: List[dict]) -> Dict[str, str]:
    return {r["alias"]: (r.get("subdir") or "").strip("/") for r in repos}


def cause_match(ref_item: dict, finding: dict, field: str = "cause_keywords") -> bool:
    """At least one of the item's keywords (`field`) appears (case-insensitive, matched at a word start) in the finding's own words.

    An item without keywords can never be confirmed: place alone is not the same problem."""
    text = " ".join(str(finding.get(k) or "") for k in ("title", "what_happens", "red_reason")).lower()
    return any(re.search(r"(?<![a-z0-9])" + re.escape(str(k).lower()), text)
               for k in ref_item.get(field) or [] if str(k).strip())


def _assign(candidates: Dict[str, List[str]], order: List[str]) -> Dict[str, str]:
    """Maximum one-to-one matching ref -> finding id (Kuhn's augmenting paths)."""
    owner: Dict[str, str] = {}

    def try_ref(ref: str, seen: set) -> bool:
        for fid in candidates.get(ref, []):
            if fid in seen:
                continue
            seen.add(fid)
            if fid not in owner or try_ref(owner[fid], seen):
                owner[fid] = ref
                return True
        return False

    for ref in order:
        try_ref(ref, set())
    return {ref: fid for fid, ref in owner.items()}


def score(reference: dict, findings: List[dict], slack: int = SLACK, repos: Optional[List[dict]] = None) -> dict:
    ref_dirs = reference.get("aliases") or {}
    finding_dirs = repo_dirs(repos) if repos is not None else {}
    items = [{**i, "cites": _normalise(i.get("cites"), ref_dirs)} for i in reference.get("items") or []]
    norm = [{**f, "evidence": _normalise(f.get("evidence"), finding_dirs)} for f in findings]
    candidates: Dict[str, List[str]] = {}
    place_only: Dict[str, List[str]] = {}
    for item in items:
        placed = [f for f in norm if match(item, f, slack)]
        caused = [f["id"] for f in placed if cause_match(item, f)]
        if caused:
            candidates[item["ref"]] = caused
        rest = [f["id"] for f in placed if not cause_match(item, f)]
        if rest:
            place_only[item["ref"]] = rest
    assigned = _assign(candidates, [i["ref"] for i in items])
    found = [i["ref"] for i in items if i["ref"] in assigned]
    missed = [i["ref"] for i in items if i["ref"] not in assigned]
    pass_at = reference.get("pass_at", len(items))
    decoy_hits: Dict[str, List[str]] = {}
    for d in reference.get("decoys") or []:
        d = {**d, "cites": _normalise(d.get("cites"), ref_dirs)}
        hits = [f["id"] for f in norm if match(d, f, slack) and cause_match(d, f, "claim_keywords")]
        if hits:
            decoy_hits[d["ref"]] = hits
    false_positives = len({fid for ids in decoy_hits.values() for fid in ids})
    allowed = reference.get("max_decoy_hits")
    precise = allowed is None or false_positives <= int(allowed)
    by_area: Dict[str, List[int]] = {}
    for item in items:
        if item.get("area"):
            tally = by_area.setdefault(str(item["area"]), [0, 0])
            tally[0] += item["ref"] in assigned
            tally[1] += 1
    return {"found": found, "missed": missed, "score": len(found), "total": len(items), "pass_at": pass_at,
            "pass": len(found) >= pass_at and precise, "candidates": candidates, "assigned": assigned,
            "place_only": place_only, "decoy_hits": decoy_hits, "false_positives": false_positives,
            "by_area": by_area}


def check_sha(reference: dict, repos: List[dict]) -> None:
    """The run must audit the commit the reference was built on: same full SHA (reference prefix >= 7 accepted)."""
    want = str(reference.get("sha", ""))
    if len(want) < 7:
        raise UsageError("the reference has no sha (at least 7 hex digits)")
    ref_dirs = reference.get("aliases") or {}
    paths = [_top_path(str(c.get("cite", "")), ref_dirs) for i in reference.get("items") or [] for c in i.get("cites") or []]
    covering = [r for r in repos if not (r.get("subdir") or "").strip("/")
                or any(p.startswith(r["subdir"].strip("/") + "/") for p in paths)]
    if not covering:
        raise UsageError("no repo of the run covers the paths the reference cites")
    for r in covering:
        if not str(r.get("sha", "")).startswith(want):
            raise UsageError(f"the run audits {r['alias']} at {r.get('sha')}, but the reference was built at {want}")


def load_reference(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise UsageError(f"cannot read the reference {path}: {exc}")
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise UsageError(f"{path} is not a reference file (needs an items list)")
    for item in data["items"]:
        for kw in item.get("cause_keywords") or []:
            if len(str(kw).strip()) < MIN_KEYWORD:
                raise UsageError(f"{path}: item {item.get('ref')} has a cause keyword shorter than {MIN_KEYWORD} characters: {kw!r}")
    dirs = data.get("aliases") or {}
    item_cites = [c for i in data["items"] for c in _normalise(i.get("cites"), dirs)]
    for d in data.get("decoys") or []:
        keywords = [str(k).strip() for k in d.get("claim_keywords") or []]
        if not keywords or any(len(k) < MIN_KEYWORD for k in keywords):
            raise UsageError(f"{path}: decoy {d.get('ref')} needs claim keywords of at least {MIN_KEYWORD} characters")
        for c in _normalise(d.get("cites"), dirs):
            if any(_close(c, ic, SLACK) or _close(ic, c, SLACK) for ic in item_cites):
                raise UsageError(f"{path}: decoy {d.get('ref')} sits within {SLACK} lines of a seeded item; "
                                 "one finding could count as both a hit and a false positive")
    return data


def report_lines(reference: dict, result: dict) -> List[str]:
    titles = {i["ref"]: i.get("title", "") for i in reference["items"]}
    lines = [f"candidate score: {result['score']}/{result['total']} (pass at {result['pass_at']})"
             " \u2014 confirm every pair by reading both",
             f"found ({len(result['found'])}):"]
    for ref in result["found"]:
        lines.append(f"  {ref}  {titles[ref]}")
        lines.append(f"      counted for: {result['assigned'][ref]}; candidates: {', '.join(result['candidates'][ref])}"
                     "  (place and cause matched; confirm it is the same problem)")
    lines.append(f"missed ({len(result['missed'])}):")
    lines += [f"  {ref}  {titles[ref]}" for ref in result["missed"]]
    place_only = {r: ids for r, ids in result.get("place_only", {}).items() if r in result["missed"]}
    if place_only:
        lines.append(f"same place, cause not confirmed ({len(place_only)}), not counted:")
        lines += [f"  {ref}  {titles[ref]}: {', '.join(ids)}" for ref, ids in place_only.items()]
    if "decoys" in reference:
        decoys = reference.get("decoys") or []
        allowed = reference.get("max_decoy_hits")
        hits = result.get("decoy_hits", {})
        lines.append(f"decoys hit: {len(hits)}/{len(decoys)}; false-positive findings: {result['false_positives']}"
                     + (f" (allowed {allowed})" if allowed is not None else ""))
        dtitles = {d["ref"]: d.get("title", "") for d in decoys}
        lines += [f"  {ref}  {dtitles.get(ref, '')}: {', '.join(ids)}" for ref, ids in hits.items()]
    if result.get("by_area"):
        lines.append("by area:")
        lines += [f"  {area}: {f}/{n}" for area, (f, n) in result["by_area"].items()]
    lines.append("candidate PASS" if result["pass"] else "candidate FAIL")
    return lines
