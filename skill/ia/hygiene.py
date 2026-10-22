"""Pre-delivery hygiene: local tooling files, secrets and TruffleHog-prone identifiers in what the audit leaves behind."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from . import branches as branchesmod
from . import findings as findingsmod
from . import run as runmod

TOKEN40 = re.compile(r"\b[A-Za-z0-9_]{40}\b")
HEX40 = re.compile(r"[0-9a-f]{40}")
TOOLING = re.compile(r"^(\.serena|\.idea|\.vscode|\.cursor|\.claude|\.DS_Store|.*\.swp)")
PINNED = re.compile(r"uses:\s*[\w.-]+/[\w./-]+@[0-9a-f]{40}\s*#\s*\S+")
SECRETS = (re.compile(r"AKIA[0-9A-Z]{16}"),
           re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
           re.compile(r"ghp_[A-Za-z0-9]{36}"),
           re.compile(r"xox[baprs]-[A-Za-z0-9-]*"))
PEM_BEGIN = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
PEM_END = re.compile(r"-----END [A-Z ]*PRIVATE KEY-----")
# Credentials in a URL: any user part on http(s), or a `user:password` part on any scheme (`ssh://git@host` is not one).
# The authority ends at the first `/`, `?`, `#`, whitespace, quote or angle bracket after `://`; the userinfo runs up to
# its LAST `@` (greedy), so an unencoded `@` inside a password is masked with the rest.
USERINFO = re.compile(r"\b((?i:(?:[a-z][a-z0-9.-]*\+)?https?)://)[^/?#\s\"'<>]+@"
                      r"|\b([A-Za-z][A-Za-z0-9+.-]*://)[^/?#\s@\"'<>]*:[^/?#\s\"'<>]*@")
PEM_SPAN = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)")
B64RUN = re.compile(r"[A-Za-z0-9+/=_-]{60,}")
EXCERPT = 80

R_TOKEN = "40-char identifier (TruffleHog false positive risk)"
R_TOOLING = "local tooling file"
R_SECRET = "possible secret"
R_CRED = "credentials in a URL"
R_KEY = "possible key material"


def _mask(match: "re.Match[str]") -> str:
    return match.group(0)[:4] + "****"


def _mask_token(match: "re.Match[str]") -> str:
    return match.group(0) if HEX40.fullmatch(match.group(0)) else _mask(match)


def has_credentials(url: str) -> bool:
    """The one credential rule: userinfo on an http(s)-family URL, or `user:password` on any scheme."""
    return bool(USERINFO.search(url or ""))


def strip_userinfo(url: str) -> str:
    """`url` without credentials (a plain `ssh://git@host` login name is kept)."""
    return USERINFO.sub(lambda m: m.group(1) or m.group(2), url or "")


def _opens_key(line: str, start: int = 0) -> bool:
    """True when the LAST private-key BEGIN at or after `start` has no END after it on this line."""
    last = None
    for last in PEM_BEGIN.finditer(line, start):
        pass
    return last is not None and not PEM_END.search(line, last.end())


def mask_line(line: str) -> str:
    """The line with every secret, URL userinfo and flagged 40-char token masked, whitespace intact."""
    text = PEM_SPAN.sub("****", line)
    text = USERINFO.sub(lambda m: (m.group(1) or m.group(2)) + "****@", text)
    for pattern in SECRETS:
        text = pattern.sub(_mask, text)
    return TOKEN40.sub(_mask_token, text)


class KeyMasker:
    """Line-by-line masking that knows about PEM private-key blocks: BEGIN..END (inclusive) is masked whole."""

    def __init__(self, inside: bool = False) -> None:
        self.inside = inside

    def line(self, line: str) -> str:
        """The masked line; advances the key-block state."""
        if self.inside:
            end = PEM_END.search(line)
            if end:
                self.inside = _opens_key(line, end.end())
            return line[:len(line) - len(line.lstrip())] + "****" if line.strip() else line
        self.inside = _opens_key(line)
        return mask_line(line)


def mask_text(text: str, inside: bool = False) -> str:
    """`text` with every line masked (PEM blocks included); the number of lines is unchanged."""
    masker = KeyMasker(inside)
    return "\n".join(masker.line(raw) for raw in text.split("\n"))


def in_key_at(lines: Sequence[str], index: int) -> bool:
    """True when line `index` (0-based) of `lines` is inside a private-key block that began on an earlier line."""
    masker = KeyMasker()
    for raw in lines[:max(0, index)]:
        masker.line(raw)
    return masker.inside


def _masked(line: str) -> str:
    """mask_line, stripped: the form used in problem excerpts."""
    return mask_line(line).strip()


def _excerpt(line: str) -> str:
    """The fully masked line, trimmed to EXCERPT chars around the first mask; none for a private-key line."""
    if PEM_BEGIN.search(line):
        return "private key block"
    text = _masked(line)
    if len(text) <= EXCERPT:
        return text
    at = text.find("****")
    start = max(0, at - 20) if at >= 0 else 0
    return text[start:start + EXCERPT]


def _secret_hit(line: str) -> bool:
    return any(p.search(line) for p in SECRETS)


def _token_hit(line: str) -> bool:
    """A mixed 40-char token that is not part of a secret already reported."""
    text = line
    for pattern in SECRETS:
        text = pattern.sub(_mask, text)
    return any(not HEX40.fullmatch(t) for t in TOKEN40.findall(text))


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, errors="replace",
                              stdin=subprocess.DEVNULL)
    except (OSError, ValueError) as exc:
        raise runmod.ToolError(f"git is not available: {exc}")


def _is_tooling(path: str) -> bool:
    parts = path.split("/")
    return any(TOOLING.match(part) for part in parts)


def scan_branch(repo: Path, base: str, branch: str) -> Tuple[List[str], List[str]]:
    """(problems, info) for the lines and paths a branch adds on top of `base`."""
    if not branchesmod.branch_exists(repo, branch):
        return [f"{branch}: branch not found: not in the repo"], []
    names = _git(repo, "diff", "--name-only", "--diff-filter=d", f"{base}...{branch}")
    if names.returncode != 0:
        raise runmod.ToolError(f"git diff {base}...{branch} failed in {repo}: {names.stderr.strip()}")
    problems: List[str] = []
    info: List[str] = []
    for path in names.stdout.splitlines():
        if _is_tooling(path):
            problems.append(f"{branch}: {R_TOOLING}: {path[:EXCERPT]}")
    diff = _git(repo, "diff", "--no-color", "-U0", f"{base}...{branch}")
    if diff.returncode != 0:
        raise runmod.ToolError(f"git diff {base}...{branch} failed in {repo}: {diff.stderr.strip()}")
    in_header = False
    keys = KeyMasker()
    path = ""
    blobs: Dict[str, List[str]] = {}
    reported_key = False

    def inside_at(line_no: int) -> bool:
        if path not in blobs:
            shown = _git(repo, "show", f"{branch}:{path}")
            blobs[path] = shown.stdout.splitlines() if shown.returncode == 0 else []
        return in_key_at(blobs[path], line_no - 1)

    for line in diff.stdout.splitlines():
        if line.startswith("diff --git "):
            in_header = True
            m = re.match(r"^diff --git a/.+ b/(.+)$", line)
            path = m.group(1) if m else ""
            keys = KeyMasker()
            reported_key = False
            continue
        h = re.match(r"^@@ -\S+ \+(\d+)", line)
        if h:
            in_header = False
            keys = KeyMasker(inside_at(int(h.group(1))) if path else False)
            continue
        if in_header or not line.startswith("+"):
            continue
        added = line[1:]
        if keys.inside:
            keys.line(added)
            if not reported_key:
                reported_key = True
                problems.append(f"{branch}: {R_KEY}")
            continue
        keys.line(added)
        if PINNED.search(added):
            info.append(f"{branch}: pinned action SHA: {added.strip()[:EXCERPT]}")
        if _secret_hit(added):
            problems.append(f"{branch}: {R_SECRET}: {_excerpt(added)}")
        if _token_hit(added):
            problems.append(f"{branch}: {R_KEY}" if B64RUN.search(added)
                            else f"{branch}: {R_TOKEN}: {_excerpt(added)}")
    return problems, info


def check_branch(repo: Path, base: str, branch: str) -> List[str]:
    return scan_branch(repo, base, branch)[0]


def _raw_userinfo(line: str) -> bool:
    """A URL with credentials that are not already masked: only a userinfo that is exactly `****`, up to the last `@`
    of the authority (what mask_line leaves), counts as masked."""
    for m in USERINFO.finditer(line):
        scheme = m.group(1) or m.group(2) or ""
        if m.group(0)[len(scheme):-1] != "****":
            return True
    return False


def _scan_file(path: Path, rel: str) -> List[str]:
    """One problem per secret line; lines inside a private-key block are never echoed, only the BEGIN line."""
    out: List[str] = []
    keys = KeyMasker()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if keys.inside:
            keys.line(line)
            continue
        keys.line(line)
        if _secret_hit(line):
            out.append(f"{rel}: {R_SECRET}: {_excerpt(line)}")
        elif _raw_userinfo(line):
            out.append(f"{rel}: {R_CRED}: {_excerpt(line)}")
    return out


def check_outputs(run: Path) -> List[str]:
    out: List[str] = []
    root = Path(run) / "outputs"
    if not root.is_dir():
        return out
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(Path(run)).as_posix()
        out += _scan_file(path, rel)
    return out


def check_findings(run: Path) -> List[str]:
    """Finding files (`<run>/findings/*.json`) must carry no unmasked secret: add and set mask prose, a hand edit may not."""
    root = Path(run) / "findings"
    if not root.is_dir():
        return []
    out: List[str] = []
    for path in sorted(p for p in root.glob("*.json") if p.is_file()):
        out += _scan_file(path, path.relative_to(Path(run)).as_posix())
    return out


def check_reports(run: Path) -> List[str]:
    """Rendered reports (`<run>/*.html`) must carry no unmasked secret."""
    out: List[str] = []
    for path in sorted(p for p in Path(run).glob("*.html") if p.is_file()):
        out += _scan_file(path, path.name)
    return out


def check_publish(run: Path) -> List[str]:
    """Prepared publish files (`<run>/publish/*`) must carry no secret and no credentialed URL."""
    out: List[str] = []
    root = Path(run) / "publish"
    if not root.is_dir():
        return out
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        out += _scan_file(path, path.relative_to(Path(run)).as_posix())
    return out


def check_run_dir(run: Path, manifest: dict) -> List[str]:
    reason = runmod.committable_reason(Path(run), manifest)
    return [f"{run}: run dir could be committed: {reason}"] if reason else []


def check_run(run: Path) -> Tuple[List[str], List[str]]:
    """(problems, info) for a whole run: finding and tests branches, saved outputs, finding files, reports, publish
    files and the run dir."""
    manifest = runmod.load(run)
    shas: Dict[str, str] = {}
    for repo in manifest["repos"]:
        shas.setdefault(repo["path"], repo["sha"])
    problems: List[str] = []
    info: List[str] = []
    groups = branchesmod.collect(manifest, findingsmod.load_all(run))
    for path, names in groups.items():
        for branch in names:
            p, i = scan_branch(Path(path), shas[path], branch)
            problems += p
            info += i
    problems += check_outputs(run)
    problems += check_findings(run)
    problems += check_reports(run)
    problems += check_publish(run)
    problems += _scan_file(Path(run) / "manifest.json", "manifest.json")
    problems += check_run_dir(run, manifest)
    return problems, info
