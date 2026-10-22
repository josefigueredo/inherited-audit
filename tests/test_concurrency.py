"""Parallel subagents call the CLI at the same time on one run: no write may be lost or swapped."""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from typing import List

from helpers import SKILL, make_dir, make_git_repo

from ia import run as runmod

PARALLEL = 16


def candidate(title: str) -> dict:
    return {"report": "correctness", "category": "validation", "dimension": "bug", "title": title,
            "verdict": "candidate", "severity": "low", "confidence": "unverified", "source": "worker-a",
            "what_happens": "w", "evidence": [{"cite": "BACK/src/a.py", "from": 1, "to": 1}]}


def parallel(commands: List[List[str]]) -> List[subprocess.CompletedProcess]:
    """Starts every command before waiting for any, so they really overlap."""
    procs = [subprocess.Popen([sys.executable, str(SKILL / "ia.py"), *cmd], stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True) for cmd in commands]
    out = []
    for cmd, p in zip(commands, procs):
        stdout, stderr = p.communicate(timeout=120)
        out.append(subprocess.CompletedProcess(cmd, p.returncode, stdout, stderr))
    return out


def make_run(modules: int = 0) -> Path:
    files = {"src/a.py": "x = 1\n"}
    files.update({f"src/m{i}/x.py": "x = 1\n" for i in range(modules)})
    repo, _ = make_git_repo(files)
    run = runmod.init_run("sys", [("BACK", repo, "")], make_dir() / "run", "es", False, "unknown")
    if modules:
        manifest = runmod.load(run)
        manifest["modules"] = {"BACK": [f"src/m{i}" for i in range(modules)]}
        runmod.save(run, manifest)
    return run


class ParallelFindingAddTest(unittest.TestCase):
    def test_every_successful_add_keeps_its_own_finding(self):
        run = make_run()
        src = make_dir()
        for i in range(PARALLEL):
            (src / f"f{i}.json").write_text(json.dumps(candidate(f"P{i}")), encoding="utf-8")
        results = parallel([["finding", "add", "--run", str(run), str(src / f"f{i}.json")] for i in range(PARALLEL)])
        for i, r in enumerate(results):
            self.assertEqual(r.returncode, 0, f"P{i}: {r.stderr}")
            fid = r.stdout.strip()
            data = json.loads((run / "findings" / f"{fid}.json").read_text(encoding="utf-8"))
            self.assertEqual(data["title"], f"P{i}", f"P{i} printed {fid}")
        self.assertEqual(len(list((run / "findings").glob("*.json"))), PARALLEL)
        self.assertEqual(list((run / "findings").glob("*.tmp")), [])

    def test_parallel_sets_on_one_finding_keep_every_field(self):
        run = make_run()
        src = make_dir() / "f.json"
        src.write_text(json.dumps(candidate("t")), encoding="utf-8")
        fid = parallel([["finding", "add", "--run", str(run), str(src)]])[0].stdout.strip()
        fields = [("reason", "r"), ("audience.title", "a"), ("audience.what_happens", "b"),
                  ("audience.fix_summary", "c"),("contrast.note", "n"), ("contrast.model", "m"), ("severity", "high"), ("category", "c2")]
        results = parallel([["finding", "set", "--run", str(run), fid, f"{k}={v}"] for k, v in fields])
        for r in results:
            self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads((run / "findings" / f"{fid}.json").read_text(encoding="utf-8"))
        for key, value in fields:
            node = data
            for part in key.split(".")[:-1]:
                node = node[part]
            self.assertEqual(node[key.split(".")[-1]], value, key)


class ParallelManifestTest(unittest.TestCase):
    def test_parallel_coverage_adds_keep_every_cell(self):
        run = make_run(modules=PARALLEL)
        results = parallel([["coverage", "add", "--run", str(run), "--pass", "security", "--module",
                             f"BACK/src/m{i}", "--result", "nothing"] for i in range(PARALLEL)])
        for r in results:
            self.assertEqual(r.returncode, 0, r.stderr)
        cells = runmod.load(run)["coverage"]["security"]
        self.assertEqual(sorted(cells), sorted(f"BACK/src/m{i}" for i in range(PARALLEL)))
        self.assertEqual([p.name for p in run.iterdir() if p.name.endswith(".tmp")], [])

    def test_parallel_set_step_and_coverage_keep_every_write(self):
        run = make_run(modules=4)
        cmds = [["coverage", "add", "--run", str(run), "--pass", "quality-lenses", "--module", f"BACK/src/m{i}",
                 "--result", "found"] for i in range(4)]
        cmds += [["set", "--run", str(run), "author_model=m"], ["set", "--run", str(run), "lang=en"],
                 ["set", "--run", str(run), 'strengths=["s"]'], ["step", "--run", str(run), "proof", "in_progress"],
                 ["step", "--run", str(run), "tests", "skipped"], ["set", "--run", str(run), "host=cursor"]]
        for r in parallel(cmds):
            self.assertEqual(r.returncode, 0, r.stderr)
        m = runmod.load(run)
        self.assertEqual(len(m["coverage"]["quality-lenses"]), 4)
        self.assertEqual((m["author_model"], m["lang"], m["strengths"], m["host"]), ("m", "en", ["s"], "cursor"))
        self.assertEqual((m["steps"]["proof"], m["steps"]["tests"]), ("in_progress", "skipped"))


if __name__ == "__main__":
    unittest.main()
