"""Module x pass coverage map: which passes visited which modules, and the guard that closes a step on it."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .run import RunError, UsageError, load, save

# The races-distributed pass numbers its topics 1..RACES_TOPICS (references/passes/races-distributed.md, "Scope").
RACES_TOPICS = 10
RACES_PASS = "races-distributed"
PASSES: Tuple[str, ...] = ("correctness-general", RACES_PASS, "security", "quality-lenses")
REQUIRED: Dict[str, Tuple[str, ...]] = {
    "correctness": ("correctness-general", RACES_PASS, "security"),
    "quality": ("quality-lenses",),
}
# The synthetic ROOT alias holds config, CI and container files: no general-correctness or races pass applies there.
ROOT_PASSES: Tuple[str, ...] = ("security", "quality-lenses")
RESULTS: Tuple[str, ...] = ("found", "nothing")


def modules_of(manifest: dict) -> List[str]:
    """Every module id (`ALIAS/path`) of the manifest, in repo order then path order."""
    mods = manifest.get("modules")
    out: List[str] = []
    if isinstance(mods, dict):
        for repo in manifest.get("repos") or []:
            out += [f"{repo['alias']}/{p}" for p in mods.get(repo["alias"]) or []]
    return out


def root_modules(manifest: dict) -> set:
    """Module ids of the aliases with `root: true` (the synthetic ROOT alias)."""
    mods = manifest.get("modules") if isinstance(manifest.get("modules"), dict) else {}
    return {f"{r['alias']}/{p}" for r in manifest.get("repos") or [] if r.get("root")
            for p in mods.get(r["alias"]) or []}


def required(manifest: dict, module: str, pass_name: str, roots: Optional[set] = None) -> bool:
    """Whether `pass_name` must visit `module`: every pass for a code module, only ROOT_PASSES for a ROOT module."""
    roots = root_modules(manifest) if roots is None else roots
    return module not in roots or pass_name in ROOT_PASSES


def parse_topics(raw: Optional[str], pass_name: str) -> List[int]:
    if raw is None or not raw.strip():
        return []
    topics = []
    for part in raw.split(","):
        part = part.strip()
        if not part.isdigit() or int(part) < 1:
            raise UsageError(f"--topics expects numbers like 1,2,3, got {raw!r}")
        topics.append(int(part))
    if pass_name == RACES_PASS and any(t > RACES_TOPICS for t in topics):
        raise UsageError(f"{RACES_PASS} has topics 1 to {RACES_TOPICS}, got {raw!r}")
    return sorted(set(topics))


def add_cells(run: Path, pass_name: str, modules: List[str], result: str, topics: List[int], note: str) -> None:
    if pass_name not in PASSES:
        raise UsageError(f"unknown pass {pass_name!r}; expected one of {', '.join(PASSES)}")
    if result not in RESULTS:
        raise UsageError(f"--result must be one of {', '.join(RESULTS)}, got {result!r}")
    manifest = load(run)
    known = modules_of(manifest)
    if not known:
        raise UsageError("the run has no modules; run `ia.py detect` first")
    unknown = [m for m in modules if m not in known]
    if unknown:
        raise UsageError(f"unknown module {', '.join(unknown)}; known modules: {', '.join(known)}")
    cells = manifest.setdefault("coverage", {}).setdefault(pass_name, {})
    for module in modules:
        cell: dict = {"result": result}
        if topics:
            cell["topics"] = topics
        if note:
            cell["note"] = note
        cells[module] = cell
    save(run, manifest)


def cell_gap(manifest: dict, pass_name: str, module: str) -> Optional[str]:
    """Why the cell is still open, or None when it is complete."""
    cell = ((manifest.get("coverage") or {}).get(pass_name) or {}).get(module)
    if not isinstance(cell, dict) or cell.get("result") not in RESULTS:
        return "not visited"
    if pass_name == RACES_PASS:
        have = set(cell.get("topics") or [])
        missing = [n for n in range(1, RACES_TOPICS + 1) if n not in have]
        if missing:
            return "topics missing " + ",".join(str(n) for n in missing)
    return None


def open_cells(manifest: dict, passes: Tuple[str, ...]) -> List[Tuple[str, str, str]]:
    """(module, pass, reason) for each open cell. Empty when the manifest has no `modules` (iteration-1 runs)."""
    out = []
    roots = root_modules(manifest)
    for module in modules_of(manifest):
        for pass_name in passes:
            if not required(manifest, module, pass_name, roots):
                continue
            gap = cell_gap(manifest, pass_name, module)
            if gap:
                out.append((module, pass_name, gap))
    return out


def guard_step(manifest: dict, step: str, force_open: Optional[str]) -> None:
    """Refuses to close `step` with open cells (RunError); with `force_open`, records the waiver in the manifest.

    The caller saves the manifest. Manifests without `modules` are never guarded.
    """
    if step not in REQUIRED or "modules" not in manifest:
        return
    gaps = open_cells(manifest, REQUIRED[step])
    if not gaps:
        return
    if force_open is None:
        lines = "\n".join(f"  {m}  {p}: {why}" for m, p, why in gaps)
        raise RunError(f"{step} has {len(gaps)} open coverage cells; visit them with `ia.py coverage add` "
                       f"(see `ia.py coverage status`), or close anyway with --force-open \"reason\":\n{lines}")
    manifest.setdefault("coverage_waivers", []).append(
        {"step": step, "reason": force_open, "open": [f"{m} / {p}" for m, p, _ in gaps]})


def _glyph(manifest: dict, pass_name: str, module: str) -> str:
    cell = ((manifest.get("coverage") or {}).get(pass_name) or {}).get(module)
    if not required(manifest, module, pass_name) and not isinstance(cell, dict):
        return "-"
    if cell_gap(manifest, pass_name, module):
        return "." if not isinstance(cell, dict) else "partial"
    return cell["result"]


def status_text(run: Path, pass_name: Optional[str] = None) -> str:
    manifest = load(run)
    if pass_name is not None and pass_name not in PASSES:
        raise UsageError(f"unknown pass {pass_name!r}; expected one of {', '.join(PASSES)}")
    passes = (pass_name,) if pass_name else PASSES
    mods = modules_of(manifest)
    if not mods:
        return "no modules recorded (run `ia.py detect`); nothing to cover"
    width = max(len(m) for m in mods)
    lines = ["module x pass (found | nothing | partial | . = not visited | - = not required):",
             " " * width + "  " + "  ".join(passes)]
    for m in mods:
        lines.append(m.ljust(width) + "  " + "  ".join(_glyph(manifest, p, m).ljust(len(p)) for p in passes))
    gaps = open_cells(manifest, passes)
    if gaps:
        lines.append(f"open cells ({len(gaps)}):")
        lines += [f"  {m}  {p}: {why}" for m, p, why in gaps]
    else:
        lines.append("open cells: none")
    return "\n".join(lines)
