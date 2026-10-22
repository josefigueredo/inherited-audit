"""ia: pin the base of an inherited-system audit, track a resumable run, check citations, branches and hygiene, render reports.

Exit codes: 0 ok, 1 the command found problems, 2 usage error, 3 an external tool failed or is missing.
"""
from __future__ import annotations

import argparse
import signal
import sys
from pathlib import Path
from typing import Callable, List, Optional

import json

from . import baseline as baselinemod
from . import branches as branchesmod
from . import cites as citesmod
from . import coverage as coveragemod
from . import detect as detectmod
from . import evaluate as evaluatemod
from . import filter as filtermod
from . import findings as findingsmod
from . import hygiene as hygienemod
from . import publish as publishmod
from . import render as rendermod
from . import run as runmod

OK, FINDINGS, USAGE, FAILED = 0, 1, 2, 3

COMMANDS = (
    ("init", "create a run directory and pin the base SHA of each audited repo"),
    ("status", "show the steps of a run and what is pending"),
    ("step", "set the state of one step of a run"),
    ("finding", "add, set or list the findings of a run"),
    ("detect", "detect the stacks, tools and workers available for the audited repos"),
    ("baseline", "run the repos' test suites at the base and save the raw output"),
    ("cite-check", "check every citation of the findings against the base SHA"),
    ("merge-check", "check that the finding branches merge pairwise without conflicts"),
    ("hygiene", "run the pre-delivery checks on a run"),
    ("filter", "apply the owner-team filter and count what is shown"),
    ("publish", "prepare issue and PR bodies and the exact gh commands (never runs them)"),
    ("render", "write the two self-contained HTML reports"),
    ("eval", "score a run against an answer key of known findings"),
    ("coverage", "record and show which passes visited which modules (add, status)"),
    ("set", "set manifest keys: host, lang, author_model, options.publish, sections, strengths, baseline.<ALIAS>.tests_branch, baseline.<ALIAS>.result.*"),
)


def _not_implemented(name: str) -> Callable[[argparse.Namespace], int]:
    def handler(_args: argparse.Namespace) -> int:
        print(f"{name}: not implemented", file=sys.stderr)
        return USAGE
    return handler


def _guard(fn: Callable[[argparse.Namespace], int]) -> Callable[[argparse.Namespace], int]:
    """Maps run errors to exit codes: 1 problems, 2 usage, 3 external tool."""
    def handler(args: argparse.Namespace) -> int:
        try:
            return fn(args)
        except runmod.UsageError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return USAGE
        except runmod.ToolError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return FAILED
        except runmod.RunError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return FINDINGS
    return handler


def _init(args: argparse.Namespace) -> int:
    repos = [runmod.parse_repo_spec(spec) for spec in args.repo]
    run_dir = runmod.init_run(args.system, repos, Path(args.out) if args.out else None, args.lang, args.publish,
                              args.host)
    print(run_dir)
    for repo in runmod.load(run_dir)["repos"]:
        if repo.get("root"):
            print(f"added alias {repo['alias']} for the repo root of {repo['path']}: cite its root-level files "
                  f"(Dockerfile, .github/...) as {repo['alias']}/<path>")
    return OK


def _status(args: argparse.Namespace) -> int:
    print(runmod.status_text(Path(args.run)))
    return OK


def _step(args: argparse.Namespace) -> int:
    run_dir = Path(args.run)
    runmod.set_step(run_dir, args.step, args.state, args.force_open)
    print(f"{args.step}: {args.state}")
    if args.step == "proof" and args.state == "done":
        left = findingsmod.list_lines(findingsmod.load_all(run_dir), "correctness", "candidate")
        if left:
            print(f"warning: proof is done but {len(left)} correctness findings are still candidates (not proven, not "
                  "discarded); they stay out of the reports unless confirmed:\n  " + "\n  ".join(left), file=sys.stderr)
    return OK


def _finding(args: argparse.Namespace) -> int:
    run_dir = Path(args.run)
    try:
        if args.action == "add":
            raw = sys.stdin.read() if args.file == "-" else Path(args.file).read_text(encoding="utf-8")
            try:
                data = json.loads(raw)
            except ValueError as exc:
                raise runmod.UsageError(f"{args.file} is not valid JSON: {exc}")
            print(findingsmod.add(run_dir, data))
        elif args.action == "set":
            findingsmod.update(run_dir, args.id, findingsmod.parse_pairs(args.pairs))
            print(args.id)
        else:
            runmod.load(run_dir)
            for line in findingsmod.list_lines(findingsmod.load_all(run_dir), args.report, args.verdict):
                print(line)
    except findingsmod.FindingError as exc:
        for problem in exc.problems:
            print(f"error: {problem}", file=sys.stderr)
        return FINDINGS
    except OSError as exc:
        raise runmod.UsageError(str(exc))
    return OK


def _configure_finding(s: argparse.ArgumentParser) -> None:
    actions = s.add_subparsers(dest="action", metavar="<action>", required=True)
    add = actions.add_parser("add", help="add a finding from a JSON file or stdin (prints the assigned id)")
    add.add_argument("--run", required=True, help="run directory")
    add.add_argument("file", help="FILE.json, or - for stdin")
    st = actions.add_parser("set", help="change fields of a finding (dotted keys, JSON values)")
    st.add_argument("--run", required=True, help="run directory")
    st.add_argument("id", help="finding id, e.g. C-01")
    st.add_argument("pairs", nargs="+", metavar="KEY=VALUE", help="e.g. contrast.verdict=refute")
    ls = actions.add_parser("list", help="list findings")
    ls.add_argument("--run", required=True, help="run directory")
    ls.add_argument("--report", choices=findingsmod.REPORTS, help="only this report")
    ls.add_argument("--verdict", choices=runmod.VERDICTS, help="only this verdict")


def _detect(args: argparse.Namespace) -> int:
    with runmod.run_lock(Path(args.run)):  # detect rewrites plans, modules and workers in one save
        return _detect_locked(args)


def _detect_locked(args: argparse.Namespace) -> int:
    run_dir = Path(args.run)
    manifest = runmod.load(run_dir)
    names: List[str] = list(detectmod.SCANNERS)
    for repo in runmod.measured_repos(manifest):
        root = Path(repo["path"]) / repo["subdir"]
        plan = detectmod.detect_repo(root, repo["sha"])
        entry = manifest["baseline"].setdefault(repo["alias"], {})
        old = entry.get("plan") if isinstance(entry.get("plan"), dict) else {}
        for key in ("env", "pre"):
            if old.get(key):
                plan[key] = old[key]
        edited = [k for k in old.get("edited") or [] if isinstance(k, str) and k in old]
        for key in edited:
            plan[key] = old[key]
        if edited:
            plan["edited"] = edited
        entry["plan"] = plan
        names += [n for n in plan["measure"] if n not in names]
        hint = (f"  (suggested install, ask first: {' '.join(plan['install_cmd'])})"
                if plan["deps"] == "none" and plan.get("install_cmd") else "")
        print(f"{repo['alias']}: {plan['stack']}  test: {' '.join(plan['test_cmd']) if plan['test_cmd'] else '-'}"
              f"  deps: {plan['deps']}{hint}" + ("" if plan["measured"] else "  (unmeasured stack)"))
    manifest["modules"] = {r["alias"]: (detectmod.detect_root_modules(Path(r["path"])) if r.get("root")
                                        else detectmod.detect_modules(Path(r["path"]) / r["subdir"]))
                           for r in manifest["repos"]}
    manifest["modules"] = {a: m for a, m in manifest["modules"].items() if m or a not in
                           {r["alias"] for r in manifest["repos"] if r.get("root")}}
    for alias, mods in manifest["modules"].items():
        print(f"{alias}: {len(mods)} modules")
    manifest["tools"] = detectmod.tool_status(names)
    hosts = list(detectmod.WORKERS) if manifest["host"] not in detectmod.WORKERS else [manifest["host"]]
    roots = [Path(r["path"]) / r["subdir"] for r in manifest["repos"]]
    js = any((e.get("plan") or {}).get("stack") == "ts-js" for e in manifest["baseline"].values() if isinstance(e, dict))
    manifest["workers"] = {h: [w for w in detectmod.worker_status(h, roots)
                               if js or not (w["check"] and w["check"]["which"] == "npx")] for h in hosts}
    runmod.save(run_dir, manifest)
    missing = [(h, w) for h in hosts for w in manifest["workers"][h] if w["available"] is False]
    if missing:
        print("missing workers (never installed without asking):")
        for h, w in missing:
            print(f"  [{h}] {w['step']}: {w['worker']}  ->  {w['install'] or '(no install command)'}"
                  + (f"  (fallback: {w['fallback']})" if w["fallback"] else ""))
    ask = [(h, w) for h in hosts for w in manifest["workers"][h]
           if w["available"] is None and w["check"] and w["check"]["which"] == "npx"]
    if ask:
        print("ask before using (npx downloads the package on first use; not a dependency of the audited repos):")
        for h, w in ask:
            print(f"  [{h}] {w['step']}: {w['worker']}  ->  {w['install']}")
    return OK


def _coverage(args: argparse.Namespace) -> int:
    run_dir = Path(args.run)
    if args.action == "add":
        coveragemod.add_cells(run_dir, args.pass_name, args.module, args.result,
                              coveragemod.parse_topics(args.topics, args.pass_name), args.note or "")
        for module in args.module:
            print(f"{args.pass_name} {module}: {args.result}")
    else:
        print(coveragemod.status_text(run_dir, args.pass_name))
    return OK


def _configure_coverage(s: argparse.ArgumentParser) -> None:
    actions = s.add_subparsers(dest="action", metavar="<action>", required=True)
    add = actions.add_parser("add", help="record that a pass visited a module (last write wins)")
    add.add_argument("--run", required=True, help="run directory")
    add.add_argument("--pass", dest="pass_name", required=True, metavar="PASS", help="one of: " + ", ".join(coveragemod.PASSES))
    add.add_argument("--module", action="append", required=True, metavar="ALIAS/path",
                     help="a module from `ia.py detect` (repeatable: same result for each)")
    add.add_argument("--result", required=True, choices=coveragemod.RESULTS, help="found findings, or nothing")
    add.add_argument("--topics", help=f"topic numbers covered, e.g. 1,2,3; {coveragemod.RACES_PASS} needs all "
                                      f"1 to {coveragemod.RACES_TOPICS}")
    add.add_argument("--note", help="what was looked at, or why nothing")
    st = actions.add_parser("status", help="print the module x pass grid and the open cells")
    st.add_argument("--run", required=True, help="run directory")
    st.add_argument("--pass", dest="pass_name", metavar="PASS", help="only this pass")


def _configure_detect(s: argparse.ArgumentParser) -> None:
    s.add_argument("--run", required=True, help="run directory")


def _configure_init(s: argparse.ArgumentParser) -> None:
    s.add_argument("--system", required=True, help="name of the audited system")
    s.add_argument("--repo", action="append", required=True, metavar="ALIAS=PATH[:SUBDIR]",
                   help="an audited repo (repeatable)")
    s.add_argument("--out", help="run directory (default: <parent of first repo>/<system>-inherited-audit/<date>)")
    s.add_argument("--lang", default="es", help="report language (default es)")
    s.add_argument("--publish", action="store_true", help="also prepare issue and PR bodies")
    s.add_argument("--host", default="unknown", choices=runmod.HOSTS, help="host running the audit")


def _configure_status(s: argparse.ArgumentParser) -> None:
    s.add_argument("--run", required=True, help="run directory")


def _configure_step(s: argparse.ArgumentParser) -> None:
    s.add_argument("--run", required=True, help="run directory")
    s.add_argument("step", help="one of: " + ", ".join(runmod.STEPS))
    s.add_argument("state", help="one of: " + ", ".join(runmod.STATES))
    s.add_argument("--force-open", metavar="REASON",
                   help="close correctness or quality with open coverage cells anyway; the reason is recorded "
                        "in the manifest and shown in the reports")


def _record_hint(run_dir: Path, alias: str) -> str:
    key = f"baseline.{alias}.result"
    return (f"`ia.py set --run {run_dir} {key}.passed=<n> {key}.failed=<n> {key}.total=<n>` (also {key}.coverage, "
            f"{key}.runner and {key}.measured)")


def _baseline(args: argparse.Namespace) -> int:
    run_dir = Path(args.run)
    manifest = runmod.load(run_dir)
    if args.set:
        if args.alias:
            raise runmod.UsageError("--set edits the plan and runs nothing; do not combine it with --alias")
        edits = [baselinemod.parse_pairs(chunk) for chunk in args.set]
        for alias, _ in edits:
            baselinemod._repo_and_plan(manifest, alias)
        for alias, values in edits:
            baselinemod.set_plan(run_dir, alias, values)
            print(f"{alias}: set {', '.join(values)}")
        return OK
    aliases = [r["alias"] for r in runmod.measured_repos(manifest)]
    if args.alias:
        baselinemod._repo_and_plan(manifest, args.alias)
        targets = [args.alias]
    else:
        for alias in aliases:
            baselinemod._repo_and_plan(manifest, alias)
        targets = aliases
    status = OK
    for alias in targets:
        result = baselinemod.run_baseline(run_dir, alias, args.timeout)
        if result["timed_out"] or (not result["measured"] and result.get("error")):
            print(f"{alias}: {result.get('error')}  (output: {result['output']})", file=sys.stderr)
            status = FAILED if result["timed_out"] or "could not start" in result["error"] else max(status, FINDINGS)
        elif not result["measured"]:
            print(f"{alias}: no test command for this stack; the baseline stays open until you record a result: run "
                  f"the suite yourself and record it with {_record_hint(run_dir, alias)}; with no test runner at all, "
                  f"record `ia.py set --run {run_dir} baseline.{alias}.result.total=0`. Or give it a command with "
                  f"`ia.py baseline --run {run_dir} --set {alias} test_cmd=[...]` and run baseline again.")
        elif not result.get("parsed", True):
            print(f"{alias}: the suite ran (exit {result['exit_code']}) but ia could not parse its summary; read "
                  f"{run_dir / result['output']} and record the numbers you read with {_record_hint(run_dir, alias)} "
                  "(tell the person); the step closes once every repo has a result.")
            status = max(status, FINDINGS)
        else:
            cov = "" if result["coverage"] is None else f"  coverage: {result['coverage']}%"
            if result.get("coverage_error"):
                cov = f"  coverage failed: {result['coverage_error']}"
            print(f"{alias}: {result['runner'] or 'unknown runner'}  passed: {result['passed']}  "
                  f"failed: {result['failed']}  total: {result['total']}  exit: {result['exit_code']}{cov}  "
                  f"output: {result['output']}")
    manifest = runmod.load(run_dir)

    done = runmod.baselines_closed(manifest)
    if done:
        runmod.set_step(run_dir, "baseline", "done")
    return status


def _configure_baseline(s: argparse.ArgumentParser) -> None:
    s.add_argument("--run", required=True, help="run directory")
    s.add_argument("--alias", help="only this repo")
    s.add_argument("--timeout", type=int, default=1800, help="seconds for all commands of one repo (default 1800)")
    s.add_argument("--set", action="append", nargs="+", metavar="ALIAS KEY=VALUE",
                   help="edit the plan of ALIAS (JSON values, e.g. env='{\"A\":\"1\"}' deps=symlink) and run nothing")


def _cite_check(args: argparse.Namespace) -> int:
    run_dir = Path(args.run)
    manifest = runmod.load(run_dir)
    found = findingsmod.load_all(run_dir)
    problems = citesmod.check_cites(manifest, found)
    if problems:
        for problem in problems:
            print(problem)
        return FINDINGS
    total = sum(len(f.get("evidence") or []) for f in found)
    print(f"all {total} citations resolve")
    return OK


def _configure_cite_check(s: argparse.ArgumentParser) -> None:
    s.add_argument("--run", required=True, help="run directory")


def _merge_check(args: argparse.Namespace) -> int:
    lines, ok = branchesmod.check_run(Path(args.run))
    for line in lines:
        print(line)
    return OK if ok else FINDINGS


def _configure_merge_check(s: argparse.ArgumentParser) -> None:
    s.add_argument("--run", required=True, help="run directory")


def _hygiene(args: argparse.Namespace) -> int:
    problems, info = hygienemod.check_run(Path(args.run))
    for line in problems:
        print(line)
    if info:
        print("info: pinned action SHAs for the model to verify against the API")
        for line in info:
            print(f"  {line}")
    if not problems:
        print("hygiene: clean")
    return FINDINGS if problems else OK


def _configure_hygiene(s: argparse.ArgumentParser) -> None:
    s.add_argument("--run", required=True, help="run directory")


def _filter(args: argparse.Namespace) -> int:
    try:
        result = filtermod.run_filter(Path(args.run), args.n)
    except findingsmod.FindingError as exc:
        for problem in exc.problems:
            print(f"error: {problem}", file=sys.stderr)
        return FINDINGS
    for report in findingsmod.REPORTS:
        c = result["counts"][report]
        print(f"{report}: showing {c['shown']} of {c['total']}")
    print("start here: " + (", ".join(result["start_here"]) or "(none)"))
    return OK


def _configure_filter(s: argparse.ArgumentParser) -> None:
    s.add_argument("--run", required=True, help="run directory")
    s.add_argument("-n", type=int, default=5, help="how many quality findings to suggest starting with (default 5)")


def _publish(args: argparse.Namespace) -> int:
    out = publishmod.prepare_publish(Path(args.run))
    print(f"prepared {out}  (nothing was executed)")
    print(publishmod.REMINDER)
    return OK


def _configure_publish(s: argparse.ArgumentParser) -> None:
    s.add_argument("--run", required=True, help="run directory")


def _render(args: argparse.Namespace) -> int:
    reports = list(findingsmod.REPORTS) if args.report == "both" else [args.report]
    filtered = isinstance(runmod.load(Path(args.run)).get("filter"), dict)
    late = rendermod.unfiltered_ids(Path(args.run)) if filtered else []
    if late:
        print(f"warning: {', '.join(late)} added after the filter (shown: null) and left out of the reports; "
              f"run `ia.py filter --run {args.run}` again, then render", file=sys.stderr)
    for out in rendermod.render_run(Path(args.run), reports, Path(args.theme) if args.theme else None):
        print(out)
    return OK


def _configure_render(s: argparse.ArgumentParser) -> None:
    s.add_argument("--run", required=True, help="run directory")
    s.add_argument("--report", choices=(*findingsmod.REPORTS, "both"), default="both", help="which report (default both)")
    s.add_argument("--theme", metavar="FILE.css", help="stylesheet to embed instead of assets/theme.css")


def _eval(args: argparse.Namespace) -> int:
    run_dir = Path(args.run)
    manifest = runmod.load(run_dir)
    reference = evaluatemod.load_reference(Path(args.reference))
    evaluatemod.check_sha(reference, manifest["repos"])
    result = evaluatemod.score(reference, findingsmod.load_all(run_dir), repos=manifest["repos"])
    for line in evaluatemod.report_lines(reference, result):
        print(line)
    return OK if result["pass"] else FINDINGS


def _configure_eval(s: argparse.ArgumentParser) -> None:
    s.add_argument("--run", required=True, help="run directory")
    s.add_argument("--reference", required=True, metavar="FILE.json", help="answer key of known findings")


def _set(args: argparse.Namespace) -> int:
    for key in runmod.set_keys(Path(args.run), args.pairs):
        print(f"set {key}")
    return OK


def _configure_set(s: argparse.ArgumentParser) -> None:
    s.add_argument("--run", required=True, help="run directory")
    s.add_argument("pairs", nargs="+", metavar="KEY=VALUE",
                   help="JSON values, e.g. host=cursor options.publish=true 'strengths=[\"...\"]'")


IMPLEMENTED = {
    "init": (_init, _configure_init),
    "status": (_status, _configure_status),
    "step": (_step, _configure_step),
    "finding": (_finding, _configure_finding),
    "detect": (_detect, _configure_detect),
    "coverage": (_coverage, _configure_coverage),
    "baseline": (_baseline, _configure_baseline),
    "cite-check": (_cite_check, _configure_cite_check),
    "merge-check": (_merge_check, _configure_merge_check),
    "hygiene": (_hygiene, _configure_hygiene),
    "filter": (_filter, _configure_filter),
    "publish": (_publish, _configure_publish),
    "render": (_render, _configure_render),
    "eval": (_eval, _configure_eval),
    "set": (_set, _configure_set),
}


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ia", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", metavar="<command>")
    for name, help_text in COMMANDS:
        s = sub.add_parser(name, help=help_text)
        if name in IMPLEMENTED:
            handler, configure = IMPLEMENTED[name]
            configure(s)
            s.set_defaults(func=_guard(handler))
        else:
            s.set_defaults(func=_not_implemented(name))
    return p


STOP_SIGNALS = (signal.SIGTERM, signal.SIGHUP)


def _on_stop(signum: int, _frame: object) -> None:
    for s in STOP_SIGNALS:  # a second signal must not cut the cleanup the first one started
        signal.signal(s, signal.SIG_IGN)
    raise runmod.Interrupted(signum)


def main(argv: Optional[List[str]] = None) -> int:
    p = parser()
    args = p.parse_args(argv)
    if not getattr(args, "cmd", None):
        p.print_usage(sys.stderr)
        return USAGE
    previous = {s: signal.signal(s, _on_stop) for s in STOP_SIGNALS}
    try:
        return args.func(args)
    except runmod.Interrupted as exc:
        print(f"error: {exc}; running commands were stopped and temporary worktrees removed", file=sys.stderr)
        return 128 + exc.signum
    except KeyboardInterrupt:
        print("error: interrupted; running commands were stopped and temporary worktrees removed", file=sys.stderr)
        return 128 + signal.SIGINT
    finally:
        for s, handler in previous.items():
            signal.signal(s, handler)
