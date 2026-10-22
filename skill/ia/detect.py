"""Stack detectors and the per-host worker table (spec 4.3)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from .run import UsageError

PASSES = "references/passes/"
SCANNERS = ("semgrep", "gitleaks", "trivy", "osv-scanner")


def _git_show(root: Path, sha: str, rel: str) -> Optional[bytes]:
    """Content of `rel` (relative to `root`) at `sha`; None if absent there.

    `git -C <root> show <sha>:./<rel>` resolves the path against root, which is the repo root joined with the
    subdir, so the lockfile path inside the repo is `subdir/rel` without the detector knowing the top level.
    """
    try:
        res = subprocess.run(["git", "-C", str(root), "show", f"{sha}:./{rel}"], capture_output=True,
                             stdin=subprocess.DEVNULL)
    except (OSError, ValueError):
        return None
    return res.stdout if res.returncode == 0 else None


def _base_plan() -> dict:
    return {"test_cmd": None, "coverage_cmd": None, "measure": [], "env": {}, "pre": [], "deps": "none",
            "deps_dirs": [], "install_cmd": None}


def _deps_mode(root: Path, sha: Optional[str], deps_dirs: List[str], lockfile: Optional[str],
               install_cmd: Optional[List[str]]) -> str:
    """`symlink` when the deps dirs exist and the lockfile matches the base; otherwise `none`.

    Never `install`: `install_cmd` stays in the plan as a suggestion and the person decides (`baseline --set`).
    """
    if deps_dirs and all((root / d).exists() for d in deps_dirs):
        same = True
        if sha is not None and lockfile is not None:
            at_sha = _git_show(root, sha, lockfile)
            now = (root / lockfile).read_bytes()
            same = at_sha is not None and at_sha == now
        if same:
            return "symlink"
    return "none"


class TsJsDetector:
    name = "ts-js"
    LOCKS = (("pnpm-lock.yaml", "pnpm", ["pnpm", "install", "--frozen-lockfile"]),
             ("yarn.lock", "yarn", ["yarn", "install", "--frozen-lockfile"]),
             ("package-lock.json", "npm", ["npm", "ci"]))

    def matches(self, root: Path) -> bool:
        return (root / "package.json").is_file()

    def plan(self, root: Path, sha: Optional[str] = None) -> dict:
        try:
            pkg = json.loads((root / "package.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pkg = {}
        if not isinstance(pkg, dict):
            pkg = {}
        runner, lockfile, install = "npm", None, None
        for lock, name, cmd in self.LOCKS:
            if (root / lock).is_file():
                runner, lockfile, install = name, lock, cmd
                break
        scripts = pkg.get("scripts") if isinstance(pkg.get("scripts"), dict) else {}
        test_script = str(scripts.get("test", ""))
        deps = {}
        for key in ("dependencies", "devDependencies"):
            if isinstance(pkg.get(key), dict):
                deps.update(pkg[key])
        coverage = None
        if "vitest" in test_script or "vitest" in deps:
            coverage = ["npx", "vitest", "run", "--coverage"]
        elif "jest" in test_script or "jest" in deps:
            coverage = ["npx", "jest", "--coverage"]
        plan = _base_plan()
        plan.update(test_cmd=[runner, "test", "--silent"] if test_script else None, coverage_cmd=coverage,
                    measure=["dependency-cruiser", "knip", "jscpd"], deps_dirs=["node_modules"],
                    install_cmd=install)
        plan["deps"] = _deps_mode(root, sha, plan["deps_dirs"], lockfile, install)
        return plan


class PythonDetector:
    name = "python"
    MARKERS = ("pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "pytest.ini")
    LOCKS = ("uv.lock", "poetry.lock")

    def _tests(self, root: Path) -> bool:
        return any((root / "tests").glob("test_*.py")) if (root / "tests").is_dir() else False

    def matches(self, root: Path) -> bool:
        return any((root / m).is_file() for m in self.MARKERS) or self._tests(root)

    def plan(self, root: Path, sha: Optional[str] = None) -> dict:
        pyproject = root / "pyproject.toml"
        text = pyproject.read_text(encoding="utf-8", errors="replace") if pyproject.is_file() else ""
        plan = _base_plan()
        lockfile = next((lock for lock in self.LOCKS if (root / lock).is_file()), None)
        deps = _deps_mode(root, sha, [".venv"], lockfile, None)
        # The venv interpreter exists in the worktree only when .venv is linked there.
        python = ".venv/bin/python" if deps == "symlink" else "python3"
        if "pytest" in text or (root / "pytest.ini").is_file():
            plan["test_cmd"] = [python, "-m", "pytest", "-q"]
            plan["coverage_cmd"] = [python, "-m", "pytest", "-q", "--cov"]
        elif self._tests(root):
            plan["test_cmd"] = [python, "-m", "unittest", "discover", "-s", "tests"]
        install = (["python3", "-m", "pip", "install", "-e", "."]
                   if (pyproject.is_file() or (root / "setup.py").is_file()) else None)
        plan.update(measure=["ruff"], deps_dirs=[".venv"], install_cmd=install, deps=deps)
        return plan


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


class JvmDetector:
    """Java and Kotlin with Maven or Gradle (Spring Boot or not).

    Dependencies live in ~/.m2 or ~/.gradle, not in the repo, so the suite runs offline (`-o`, `--offline`): fetching
    them is installing, and only `deps=install` runs `install_cmd` first. The counts come from the JUnit XML reports
    (`junit`), because Gradle prints no summary when every test passes and Maven prints one per module.
    """
    name = "jvm"
    MAVEN = ("pom.xml",)
    GRADLE = ("build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts")

    def matches(self, root: Path) -> bool:
        return any((root / f).is_file() for f in self.MAVEN + self.GRADLE)

    def plan(self, root: Path, sha: Optional[str] = None) -> dict:
        plan = _base_plan()
        if (root / "pom.xml").is_file():
            mvn = "./mvnw" if (root / "mvnw").is_file() else "mvn"
            plan.update(test_cmd=[mvn, "-B", "-ntp", "-o", "-Dmaven.test.failure.ignore=true", "test"],
                        install_cmd=[mvn, "-B", "-ntp", "dependency:go-offline"],
                        junit=["**/target/surefire-reports/TEST-*.xml"])
            build = _read(root / "pom.xml")
        else:
            gradle = "./gradlew" if (root / "gradlew").is_file() else "gradle"
            plan.update(test_cmd=[gradle, "test", "--offline", "--continue", "--console=plain"],
                        install_cmd=[gradle, "dependencies", "--console=plain"],
                        junit=["**/build/test-results/**/TEST-*.xml"])
            build = "".join(_read(root / f) for f in self.GRADLE)
        if "org.springframework.boot" in build or "spring-boot" in build:
            plan["framework"] = "spring-boot"
        return plan


GO_OFFLINE = ("GOPROXY=off", "GOTOOLCHAIN=local")


class GoDetector:
    """Go modules. The module cache lives outside the repo, so the suite runs with GOPROXY=off (no download) and
    GOTOOLCHAIN=local (no toolchain download either); `go mod download` is the suggested install. `go test -json`
    gives exact counts, also for packages that fail to build."""
    name = "go"

    def matches(self, root: Path) -> bool:
        return (root / "go.mod").is_file()

    def plan(self, root: Path, sha: Optional[str] = None) -> dict:
        offline = " ".join(GO_OFFLINE)
        plan = _base_plan()
        plan.update(test_cmd=["env", *GO_OFFLINE, "go", "test", "-json", "./..."],
                    coverage_cmd=["sh", "-c", f"{offline} go test -coverprofile=.ia-cover.out ./... > /dev/null && "
                                              f"{offline} go tool cover -func=.ia-cover.out"],
                    install_cmd=["go", "mod", "download"], measure=["golangci-lint"])
        return plan


DETECTORS: list = [JvmDetector(), GoDetector(), TsJsDetector(), PythonDetector()]

MODULE_CONTAINERS = ("src/modules", "src/features", "src/app", "app", "src/components")
NOT_MODULES = {"tests", "test", "__tests__", "spec", "specs", "e2e", "node_modules", "dist", "build", "out", "target",
               "coverage", "__pycache__", "venv", "env", "site-packages"}


def _module_dirs(parent: Path) -> List[str]:
    """Names of the immediate subdirectories of `parent` that can hold code (not tests, build output or dotdirs)."""
    if not parent.is_dir():
        return []
    names = []
    for child in sorted(parent.iterdir(), key=lambda c: c.name):
        if (not child.is_dir() or child.name.startswith(".") or child.name in NOT_MODULES
                or child.name.endswith(".egg-info")):
            continue
        if any(files for _, _, files in os.walk(child)):  # a folder git would not even track is not a module
            names.append(child.name)
    return names


ROOT_FILES = "."


def _has_root_files(folder: Path) -> bool:
    """True when `folder` holds a regular file directly (not a dotfile): bootstrap files that no folder module covers."""
    try:
        return any(p.is_file() and not p.name.startswith(".") for p in folder.iterdir())
    except OSError:
        return False


def detect_modules(root: Path) -> List[str]:
    """Module paths relative to `root`: the subdirectories of the usual containers plus every other directory of `src/`
    (of `root` when there is no `src/`), and the pseudo-module `src/.` (or `.`) when files sit directly in that folder.
    Sorted, so the same tree gives the same list."""
    root = Path(root)
    if JvmDetector().matches(root):
        return _jvm_modules(root)
    if GoDetector().matches(root):
        return _go_modules(root)
    found = set()
    for container in MODULE_CONTAINERS:
        found.update(f"{container}/{n}" for n in _module_dirs(root / container))
    base = "src" if (root / "src").is_dir() else ""
    # the containers themselves are not modules, their children are
    skip = {"modules", "features", "app", "components"} if base else {"app"}
    found.update(f"{base}/{n}" if base else n for n in _module_dirs(root / base) if n not in skip)
    if _has_root_files(root / base if base else root):
        found.add(f"{base}/{ROOT_FILES}" if base else ROOT_FILES)
    return sorted(found)


JVM_SOURCES = ("src/main/java", "src/main/kotlin")
BUILD_FILES = JvmDetector.MAVEN + JvmDetector.GRADLE


def _package_root(source: Path) -> Path:
    """The base package: walk down while a folder holds exactly one folder and no file (com/acme/shop)."""
    here = source
    while True:
        try:
            children = [c for c in here.iterdir() if not c.name.startswith(".")]
        except OSError:
            return here
        dirs = [c for c in children if c.is_dir()]
        if len(dirs) != 1 or any(c.is_file() for c in children):
            return here
        here = dirs[0]


def _jvm_projects(root: Path) -> List[Path]:
    """The root and every sub-project with its own build file (Maven modules, Gradle subprojects), two levels deep."""
    found = [root]
    for depth in ("*", "*/*"):
        for build in sorted(root.glob(f"{depth}/pom.xml")) + sorted(
                p for name in JvmDetector.GRADLE for p in root.glob(f"{depth}/{name}")):
            project = build.parent
            if project not in found and not any(part in NOT_MODULES or part.startswith(".")
                                                for part in project.relative_to(root).parts):
                found.append(project)
    return found


def _jvm_modules(root: Path) -> List[str]:
    """Per project: the children of the base package of src/main/java|kotlin (Spring's package by feature or by
    layer), `<base package>/.` for the files sitting in it (the @SpringBootApplication class), and src/main/resources
    (application.yml and its profiles)."""
    found = set()
    for project in _jvm_projects(root):
        for source in JVM_SOURCES:
            if not (project / source).is_dir():
                continue
            base = _package_root(project / source)
            rel = base.relative_to(root).as_posix()
            children = _module_dirs(base)
            found.update(f"{rel}/{name}" for name in children)
            if _has_root_files(base):  # a package with no sub-package is one module, not a `/.` of itself
                found.add(f"{rel}/{ROOT_FILES}" if children else rel)
        resources = project / "src/main/resources"
        if resources.is_dir() and any(files for _, _, files in os.walk(resources)):
            found.add(resources.relative_to(root).as_posix())
    return sorted(found)


GO_CONTAINERS = ("cmd", "internal", "pkg")
GO_SKIP = {"vendor", "testdata"}


def _go_dirs(parent: Path) -> List[str]:
    """Subdirectories of `parent` holding Go code somewhere below (not vendor/, testdata/ or test-only folders)."""
    names = []
    for name in _module_dirs(parent):
        if name in GO_SKIP:
            continue
        for here, dirs, files in os.walk(parent / name):
            dirs[:] = [d for d in dirs if d not in GO_SKIP and not d.startswith(".")]
            if any(f.endswith(".go") for f in files):
                names.append(name)
                break
    return names


def _has_go_files(folder: Path) -> bool:
    try:
        return any(p.is_file() and p.name.endswith(".go") for p in folder.iterdir())
    except OSError:
        return False


def _go_modules(root: Path) -> List[str]:
    """The Go layout: every command under cmd/, every package under internal/ and pkg/, every other top-level package
    folder, `<container>/.` for Go files directly in a container, and `.` for the root package."""
    found = set()
    for container in GO_CONTAINERS:
        found.update(f"{container}/{n}" for n in _go_dirs(root / container))
        if _has_go_files(root / container):
            found.add(f"{container}/{ROOT_FILES}")
    found.update(n for n in _go_dirs(root) if n not in GO_CONTAINERS)
    if _has_go_files(root):
        found.add(ROOT_FILES)
    return sorted(found)


ROOT_DIRS = (".github", "docker", "deploy", "infra", "scripts")


def detect_root_modules(top: Path) -> List[str]:
    """Root-level directories no other alias covers (CI, containers, deploy, infra, scripts), only those that exist,
    after the pseudo-module `.` when files (Dockerfile, entrypoint.sh...) sit directly at the repo root."""
    top = Path(top)
    dirs = [d for d in ROOT_DIRS if (top / d).is_dir() and any(files for _, _, files in os.walk(top / d))]
    return ([ROOT_FILES] if _has_root_files(top) else []) + dirs


def detect_repo(root: Path, sha: Optional[str] = None) -> dict:
    root = Path(root)
    for detector in DETECTORS:
        if detector.matches(root):
            return {"stack": detector.name, "measured": True, **detector.plan(root, sha)}
    return {"stack": "unknown", "measured": False, **_base_plan()}


def tool_status(names: List[str]) -> Dict[str, bool]:
    return {name: shutil.which(name) is not None for name in names}


def _w(step: str, worker: str, check: Optional[str], install: str, fallback: str) -> dict:
    return {"step": step, "worker": worker, "check": {"which": check} if check else None, "install": install,
            "fallback": f"{PASSES}{fallback}.md" if fallback else ""}


def _own(step: str, fallback: str) -> dict:
    return {"step": step, "worker": "own pass", "check": None, "install": "", "fallback": f"{PASSES}{fallback}.md"}


def _shared() -> List[dict]:
    return [
        _w("static", "semgrep", "semgrep", "brew install semgrep", "supply-chain-container"),
        _w("static", "gitleaks", "gitleaks", "brew install gitleaks", "supply-chain-container"),
        _w("static", "trivy", "trivy", "brew install trivy", "supply-chain-container"),
        _w("static", "osv-scanner", "osv-scanner", "brew install osv-scanner", "supply-chain-container"),
        _w("measure", "dependency-cruiser", "npx", "npx -y dependency-cruiser --version", ""),
        _w("measure", "knip", "npx", "npx -y knip --version", ""),
        _w("measure", "jscpd", "npx", "npx -y jscpd --version", ""),
    ]


WORKERS: Dict[str, List[dict]] = {
    "claude-code": [
        _own("baseline", "baseline-inventory"),
        _w("correctness-bugs", "/code-review per module", None, "", "correctness-general"),
        _w("security", "claude-security", None, "/plugin install claude-security@claude-plugins-official",
           "security"),
        _own("races", "races-distributed"),
        *_shared(),
        _w("unit-tests", "superpowers:test-driven-development", None, "/plugin install superpowers@claude-plugins-official",
           "unit-tests"),
        _w("e2e", "Playwright", None, "/plugin install playwright@claude-plugins-official", "e2e-infra"),
        _w("quality", "feature-dev:code-architect", None, "/plugin install feature-dev@claude-plugins-official",
           "quality-lenses"),
        _w("contrast", "openai/codex-plugin-cc (/codex:adversarial-review)", None,
           "/plugin marketplace add openai/codex-plugin-cc && /plugin install codex@openai-codex", "contrast"),
        _own("proof", "red-test-proof"),
        _own("verify", "verify-high"),
        _own("prose", "owner-prose"),
    ],
    "cursor": [
        _own("baseline", "baseline-inventory"),
        _w("correctness-bugs", "/review-bugbot", None, "", "correctness-general"),
        _own("security", "security"),
        _own("races", "races-distributed"),
        *_shared(),
        _w("unit-tests", "obra/superpowers", None, "/add-plugin superpowers", "unit-tests"),
        _w("e2e", "Playwright", None, "", "e2e-infra"),
        _w("quality", "wshobson/agents (c4-architecture, comprehensive-review)", None,
           "/add-plugin (Cursor 2.5+ marketplace: https://github.com/wshobson/agents)", "quality-lenses"),
        _w("contrast", "agent -p --mode ask --model <other-model> --output-format json", "agent",
           "", "contrast"),
        _own("proof", "red-test-proof"),
        _own("verify", "verify-high"),
        _own("prose", "owner-prose"),
    ],
}


def _npm_dependencies(roots: List[Path]) -> set:
    """Package names in dependencies/devDependencies of every root's package.json (unreadable files are skipped)."""
    names: set = set()
    for root in roots:
        try:
            pkg = json.loads((Path(root) / "package.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(pkg, dict):
            continue
        for key in ("dependencies", "devDependencies"):
            if isinstance(pkg.get(key), dict):
                names.update(pkg[key])
    return names


def worker_status(host: str, roots: Optional[List[Path]] = None) -> List[dict]:
    """The worker rows of `host` with `available`: True, False, or None when the person has to be asked.

    Rows run through `npx -y` download the package on first use, which counts as installing: they are None unless
    the package is already a dependency of one of the audited `roots`.
    """
    if host not in WORKERS:
        raise UsageError(f"unknown host {host!r}; expected one of {', '.join(WORKERS)}")
    deps = _npm_dependencies(list(roots or []))
    out = []
    for entry in WORKERS[host]:
        available: Optional[bool] = None
        if entry["worker"] == "own pass":
            available = True
        elif entry["check"] and entry["check"]["which"] == "npx":
            available = (True if entry["worker"] in deps else None) if shutil.which("npx") else False
        elif entry["check"]:
            available = shutil.which(entry["check"]["which"]) is not None
        out.append({**entry, "available": available})
    return out
