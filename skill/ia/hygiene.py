"""Pre-delivery hygiene: local tooling files, secrets and TruffleHog-prone identifiers in what the audit leaves behind."""
from __future__ import annotations

import copy
import html
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
MASK = "****"

# Values behind a secret-looking name: readable defaults have no secret shape of their own, so the name gives them away.
SECRET_WORDS = {"token", "tokens", "secret", "secrets", "password", "passwd", "pwd", "passphrase", "credential",
                "credentials", "apikey"}
# `key` and `master` alone are everywhere (`- key: DB_HOST`, `keycloak`, `branch: master`): only these compounds count.
KEY_QUALIFIERS = {"api", "secret", "private", "access", "signing", "encryption", "master", "client", "auth", "hmac",
                  "jwt", "license", "app", "session"}
MASTER_PARTNERS = {"value", "key", "token", "secret", "password"}
# A secret word followed by one of these names a setting about the secret, not the secret (`token-ttl`, `key-store-type`).
NOT_SECRET_TAIL = {"ttl", "expiration", "expiry", "expires", "length", "size", "timeout", "type", "uri", "url",
                   "endpoint", "header", "name", "policy", "enabled", "enable", "path", "file", "location", "source",
                   "prefix", "format", "algorithm", "alg", "validity", "duration", "issuer", "audience", "count", "max",
                   "min", "store", "id", "mode", "env", "var", "field", "param", "required", "regex", "pattern", "attribute",
                   "attr", "claim", "label", "column", "property"}
CONFIG_SUFFIXES = (".yml", ".yaml", ".properties", ".env", ".conf", ".cfg", ".ini", ".toml")
# Saved files that something runs (the e2e infra under outputs/): masking a literal there breaks them, so --fix leaves
# them for a person, who moves the value to an environment variable.
RUNNABLE_SUFFIXES = (".sh", ".bash", ".zsh", ".ps1", ".py", ".js", ".mjs", ".cjs", ".ts", ".rb", ".sql")
RUNNABLE_NAMES = ("dockerfile", "makefile", "containerfile")
_NAME = r"[A-Za-z_][A-Za-z0-9_.-]*"
PLACEHOLDER = re.compile(r"\$\{(" + _NAME + r")(:-?)([^}]*)\}")
# QUOTED and BARE are lookaheads, so candidates overlap: in `env: DB_PASSWORD=x` or `{"a": "b {"api_key": "x"}"}`
# the inner key is seen even though an outer one matched first.
QUOTED = re.compile(r"""(?<![\w.-])(?=(["']?)(""" + _NAME + r""")\1\s*[:=]\s*(["'])(.*?)\3)""")
HEADER = re.compile(r"""(?i)(?:-H|--header)\s*["']\s*(""" + _NAME + r""")\s*:\s*(?:(?:bearer|basic)\s+)?([^"'\s]+)""")
BEARER = re.compile(r"(?i)\bauthorization\s*:\s*(?:bearer|basic)\s+([^\s\"'<>$]+)")
BARE = re.compile(r"""(?<![\w.${-])(?=(""" + _NAME + r""")\s*([:=])[ \t]*(?!["'])([^\s#;,"'}]+))""")
SCREAMING = re.compile(r"[A-Z][A-Z0-9_]*$")
NOT_SECRET_VALUE = re.compile(r"(?i)(\*+|[$<{%].*|\d+(\.\d+)?[a-z]{0,2}|true|false|null|none|nil|~|"
                              r"[a-z][a-z0-9+.-]*://.*)$")
ROW = re.compile(r'<span class="ln[^"]*"><i>\d+</i>(.*?)</span>')
PRE = re.compile(r"<pre( data-config)?>(.*?)</pre>")
TAG = re.compile(r"<[^>]+>")

R_TOKEN = "40-char identifier (TruffleHog false positive risk)"
R_TOOLING = "local tooling file"
R_SECRET = "possible secret"
R_CRED = "credentials in a URL"
R_KEY = "possible key material"
R_NAMED = "value of a secret-named key"


def _mask(match: "re.Match[str]") -> str:
    return match.group(0)[:4] + "****"


def _mask_token(match: "re.Match[str]") -> str:
    return match.group(0) if HEX40.fullmatch(match.group(0)) else _mask(match)


IDENT_CAMEL = re.compile(r"[A-Za-z][a-z]+(?:[A-Z][a-z]+)+\d{0,3}")
IDENT_SNAKE = re.compile(r"(?:[a-z]+(?:_[a-z]+)+|[A-Z]+(?:_[A-Z]+)+)\d{0,3}")


def looks_like_identifier(token: str) -> bool:
    """camelCase, PascalCase, snake_case or SCREAMING_SNAKE words with no digits inside: code, not a random token."""
    return bool(IDENT_CAMEL.fullmatch(token) or IDENT_SNAKE.fullmatch(token))


def _mask_token_prose(match: "re.Match[str]") -> str:
    return match.group(0) if looks_like_identifier(match.group(0)) else _mask_token(match)


def masked_tokens(text: str) -> int:
    """How many 40-char tokens prose masking rewrites in `text` (hex SHAs and code identifiers are kept)."""
    return sum(1 for t in TOKEN40.findall(text or "") if not HEX40.fullmatch(t) and not looks_like_identifier(t))


def _words(name: str) -> List[str]:
    out: List[str] = []
    for part in re.split(r"[_.\-]+", name):
        out += [w.lower() for w in re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+", part)]
    return out


def secret_name(name: str) -> bool:
    """True when a key or variable name says its value is a secret (`DB_PASSWORD`, `apiKey`, `MASTER_TOKEN_VALUE`)."""
    words = _words(name)
    if not words or words[-1] in NOT_SECRET_TAIL:
        return False
    if any(w in SECRET_WORDS for w in words):
        return True
    for i, w in enumerate(words):
        if w == "key" and i > 0 and words[i - 1] in KEY_QUALIFIERS:
            return True
        if w == "master" and any(x in MASTER_PARTNERS for x in words[i + 1:]):
            return True
    return False


def is_config_path(path: str) -> bool:
    """Config files, where a bare `key: value` or `KEY=value` is a literal, not code."""
    name = (path or "").rsplit("/", 1)[-1].lower()
    return name.endswith(CONFIG_SUFFIXES) or name.startswith(".env")


def _hides(value: str) -> bool:
    return bool(value) and not NOT_SECRET_VALUE.match(value)


def _mask_spans(text: str, pattern: "re.Pattern[str]", group: int, hides) -> str:
    """`text` with group `group` of every (overlapping) match of `pattern` for which `hides(match)` holds masked;
    replaced right to left, and a span inside one already masked is dropped."""
    spans = [(m.start(group), m.end(group)) for m in pattern.finditer(text) if hides(m)]
    last = len(text) + 1
    for start, end in reversed(spans):
        if end <= last:
            text = text[:start] + MASK + text[end:]
            last = start
    return text


def mask_named(line: str, config: bool = False) -> str:
    """`line` with the value behind every secret-named key masked as `****`: a `${NAME:default}` default, a quoted
    literal, a curl header or bearer token, a `SCREAMING_NAME=value` and, in config files (`config`), any bare
    `key: value` or `key=value`. Idempotent."""
    def placeholder(m: "re.Match[str]") -> str:
        if not secret_name(m.group(1)) or not _hides(m.group(3)):
            return m.group(0)
        return "${" + m.group(1) + m.group(2) + MASK + "}"

    def quoted(m: "re.Match[str]") -> bool:
        return secret_name(m.group(2)) and _hides(m.group(4))

    def header(m: "re.Match[str]") -> str:
        if not secret_name(m.group(1)) or not _hides(m.group(2)):
            return m.group(0)
        return m.group(0)[:m.start(2) - m.start(0)] + MASK

    def bearer(m: "re.Match[str]") -> str:
        return m.group(0) if not _hides(m.group(1)) else m.group(0)[:m.start(1) - m.start(0)] + MASK

    def bare(m: "re.Match[str]") -> bool:
        name, sep, value = m.group(1), m.group(2), m.group(3)
        return bool((config or (sep == "=" and SCREAMING.match(name))) and secret_name(name) and _hides(value))

    text = PLACEHOLDER.sub(placeholder, line)
    text = _mask_spans(text, QUOTED, 4, quoted)
    text = HEADER.sub(header, text)
    text = BEARER.sub(bearer, text)
    return _mask_spans(text, BARE, 3, bare)


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


def mask_line(line: str, prose: bool = False, config: bool = False, tokens: bool = True) -> str:
    """The line with every secret, URL userinfo, secret-named value and flagged 40-char token masked, whitespace
    intact. `prose` keeps 40-char code identifiers (camelCase, snake_case); `config` masks bare `key: value` too;
    `tokens=False` leaves 40-char tokens alone (they are a scanner false positive, not a secret)."""
    text = PEM_SPAN.sub("****", line)
    text = USERINFO.sub(lambda m: (m.group(1) or m.group(2)) + "****@", text)
    for pattern in SECRETS:
        text = pattern.sub(_mask, text)
    text = mask_named(text, config)
    if not tokens:
        return text
    return TOKEN40.sub(_mask_token_prose if prose else _mask_token, text)


class KeyMasker:
    """Line-by-line masking that knows about PEM private-key blocks: BEGIN..END (inclusive) is masked whole."""

    def __init__(self, inside: bool = False, prose: bool = False, config: bool = False, tokens: bool = True) -> None:
        self.inside = inside
        self.prose = prose
        self.config = config
        self.tokens = tokens

    def line(self, line: str) -> str:
        """The masked line; advances the key-block state."""
        if self.inside:
            end = PEM_END.search(line)
            if end:
                self.inside = _opens_key(line, end.end())
            return line[:len(line) - len(line.lstrip())] + "****" if line.strip() else line
        self.inside = _opens_key(line)
        return mask_line(line, self.prose, self.config, self.tokens)


def mask_text(text: str, inside: bool = False, prose: bool = False, tokens: bool = True) -> str:
    """`text` with every line masked (PEM blocks included); the number of lines is unchanged. `prose` keeps 40-char
    code identifiers; `tokens=False` keeps every 40-char token."""
    masker = KeyMasker(inside, prose, tokens=tokens)
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


def _scan_file(path: Path, rel: str, named: bool = True) -> List[str]:
    """One problem per secret line; lines inside a private-key block are never echoed, only the BEGIN line. `named`
    also flags the value behind a secret-named key (in a JSON file, after unescaping `\\"`); bare `key: value` is
    not checked here, since these files are not config files."""
    out: List[str] = []
    keys = KeyMasker()
    unescape = path.suffix == ".json"
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if keys.inside:
            keys.line(line)
            continue
        keys.line(line)
        text = line.replace('\\"', '"') if unescape else line
        if _secret_hit(line):
            out.append(f"{rel}: {R_SECRET}: {_excerpt(line)}")
        elif _raw_userinfo(line):
            out.append(f"{rel}: {R_CRED}: {_excerpt(line)}")
        elif named and mask_named(text) != text:
            out.append(f"{rel}: {R_NAMED}: {_named_excerpt(text)}")
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


def _named_excerpt(text: str) -> str:
    """The line masked with the config rules too, trimmed to EXCERPT chars around the first mask."""
    text = mask_line(text, config=True).strip()
    at = text.find(MASK)
    start = max(0, at - 40) if at >= 0 else 0
    return text[start:start + EXCERPT]


def _named_hits(line: str) -> List[str]:
    """Unmasked secret-named values in one HTML line: code rows of a `<pre>` one by one (bare `key: value` only in a
    config file's `<pre data-config>`), and the text outside them."""
    hits: List[str] = []
    for pre in PRE.finditer(line):
        config = bool(pre.group(1))
        for row in ROW.findall(pre.group(2)):
            text = html.unescape(TAG.sub("", row))
            if mask_named(text, config) != text:
                hits.append(_named_excerpt(text))
    rest = html.unescape(TAG.sub(" ", PRE.sub(" ", line)))
    if mask_named(rest) != rest:
        hits.append(_named_excerpt(rest))
    return hits


def check_reports(run: Path) -> List[str]:
    """Rendered reports (`<run>/*.html`) must carry no unmasked secret, including the value behind a secret-named key
    (`${API_TOKEN:default}`, `password: ...` in a config file's snippet)."""
    out: List[str] = []
    for path in sorted(p for p in Path(run).glob("*.html") if p.is_file()):
        out += _scan_file(path, path.name, named=False)  # rows are checked one by one below
        keys = KeyMasker()
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if keys.inside:
                keys.line(line)
                continue
            keys.line(line)
            out += [f"{path.name}: {R_NAMED}: {hit}" for hit in _named_hits(line)]
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


def _changed_lines(before: str, after: str) -> int:
    return sum(1 for a, b in zip(before.split("\n"), after.split("\n")) if a != b)


def _runnable(path: Path) -> bool:
    name = path.name.lower()
    return (is_config_path(name) or name.endswith(RUNNABLE_SUFFIXES) or name in RUNNABLE_NAMES
            or name.startswith(RUNNABLE_NAMES))


def _fix_file(path: Path) -> int:
    """Rewrite one saved text file with what the checks flag masked (secrets, URL credentials, key blocks,
    secret-named values; 40-char tokens such as lockfile hashes and test names stay); the number of lines changed.
    Files that are not UTF-8 text, and config files, scripts and Dockerfiles (something runs them), are left alone:
    the checks still report them."""
    if _runnable(path):
        return 0
    try:
        text = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return 0
    masked = mask_text(text, tokens=False)
    if masked == text:
        return 0
    runmod.atomic_write(path, masked)
    return _changed_lines(text, masked)


def fix_run(run: Path) -> List[Tuple[str, int]]:
    """Mask what the audit saved: every finding whose prose is not masked is written again (`finding set` masks on
    write) and every text file under `outputs/` and `publish/` is rewritten masked. (relative path, lines changed)
    for each file that changed, sorted; branches, reports, binaries and runnable files (config, scripts,
    Dockerfiles) are never touched."""
    run = Path(run)
    fixed: List[Tuple[str, int]] = []
    for f in findingsmod.load_all(run):
        if findingsmod.mask_prose(copy.deepcopy(f)) == f:
            continue
        path = run / "findings" / f"{f['id']}.json"
        before = path.read_text(encoding="utf-8")
        findingsmod.update(run, f["id"], {})
        fixed.append((path.relative_to(run).as_posix(), _changed_lines(before, path.read_text(encoding="utf-8"))))
    for folder in ("outputs", "publish"):
        root = run / folder
        for path in sorted(p for p in root.rglob("*") if p.is_file()) if root.is_dir() else []:
            n = _fix_file(path)
            if n:
                fixed.append((path.relative_to(run).as_posix(), n))
    return sorted(fixed)


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
