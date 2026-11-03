"""The bench in bench/ measures what it claims: a fixed sha, every seeded bug proven red, every decoy proven green,
a system the CLI audits like any other, and nothing in the audited tree that points at the answer key."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

from helpers import ROOT, make_dir, run_cli

from ia import evaluate

BENCH = ROOT / "bench"
KEY = json.loads((BENCH / "key.json").read_text(encoding="utf-8"))
sys.path.insert(0, str(BENCH))
import build as benchbuild  # noqa: E402

_BUILT = {}


def built_repo() -> Path:
    """One build per test run, shared by the read-only tests."""
    if "repo" not in _BUILT:
        repo = make_dir() / "shop"
        _BUILT["sha"] = benchbuild.build(repo)
        _BUILT["repo"] = repo
    return _BUILT["repo"]


def proof_for(ref: str) -> Path:
    hits = sorted((BENCH / "proofs").glob(f"test_{ref}_*.py"))
    assert len(hits) == 1, f"{ref}: expected one proof, found {hits}"
    return hits[0]


def run_proof(ref: str) -> subprocess.CompletedProcess:
    proof = proof_for(ref)
    return subprocess.run([sys.executable, "-m", "unittest", proof.stem], cwd=str(proof.parent), capture_output=True,
                          text=True, env={**os.environ, "BENCH_REPO": str(built_repo()),
                                          "PYTHONDONTWRITEBYTECODE": "1"}, timeout=60)


class BenchBuildTest(unittest.TestCase):
    def test_build_gives_the_key_sha_every_time(self):
        built_repo()
        self.assertEqual(_BUILT["sha"], KEY["sha"], "a bench file changed: rebuild and update sha and cites in key.json")
        self.assertEqual(benchbuild.build(make_dir() / "again"), KEY["sha"])

    def test_build_refuses_a_non_empty_dir(self):
        target = make_dir()
        (target / "x").write_text("x", encoding="utf-8")
        with self.assertRaises(SystemExit):
            benchbuild.build(target)

    def test_the_systems_own_suite_is_green(self):
        result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=str(built_repo()),
                                capture_output=True, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_nothing_in_the_audited_tree_points_at_the_key(self):
        repo = built_repo()
        words = re.compile(r"seed|decoy|bench|proof|answer key|\bbug|\bvuln|inject|race|todo|fixme|hack", re.I)
        for path in repo.rglob("*"):
            if path.is_file() and ".git" not in path.parts:
                for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                    self.assertIsNone(words.search(line), f"{path.relative_to(repo)}:{n}: {line.strip()}")
        log = subprocess.run(["git", "log", "--format=%B"], cwd=str(repo), capture_output=True, text=True).stdout
        self.assertIsNone(words.search(log), log)


class BenchKeyTest(unittest.TestCase):
    def test_key_loads_and_no_decoy_sits_next_to_an_item(self):
        loaded = evaluate.load_reference(BENCH / "key.json")
        self.assertEqual(len(loaded["items"]), 14)
        self.assertEqual(len(loaded["decoys"]), 7)

    def test_every_cite_is_inside_its_file(self):
        repo = built_repo()
        for entry in KEY["items"] + KEY["decoys"]:
            for c in entry["cites"]:
                path = repo / c["cite"].split("/", 1)[1]
                lines = path.read_text(encoding="utf-8").splitlines()
                self.assertTrue(1 <= c["from"] <= c["to"] <= len(lines), f"{entry['ref']}: {c}")
                self.assertTrue(lines[c["from"] - 1].strip(), f"{entry['ref']} starts on a blank line")

    def test_every_item_names_an_area_the_skill_has(self):
        areas = {"correctness-general", "races-distributed", "security", "quality-lenses"}
        for item in KEY["items"]:
            self.assertIn(item["area"], areas, item["ref"])

    def test_one_proof_per_item_and_decoy_and_no_strays(self):
        refs = {e["ref"] for e in KEY["items"] + KEY["decoys"]}
        on_disk = {p.name.split("_")[1] for p in (BENCH / "proofs").glob("test_*.py")}
        self.assertEqual(on_disk, refs)


class BenchProofTest(unittest.TestCase):
    """Without this a "bug" that is not one, or a decoy that is really broken, corrupts every measurement."""

    def test_every_seeded_item_fails_on_an_assertion(self):
        for item in KEY["items"]:
            with self.subTest(ref=item["ref"]):
                result = run_proof(item["ref"])
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("FAILED (failures=", result.stderr)
                self.assertNotIn("errors=", result.stderr)

    def test_every_decoy_passes(self):
        for decoy in KEY["decoys"]:
            with self.subTest(ref=decoy["ref"]):
                result = run_proof(decoy["ref"])
                self.assertEqual(result.returncode, 0, result.stderr)


class BenchAuditTest(unittest.TestCase):
    def test_init_detect_and_baseline_close_on_the_bench(self):
        out = make_dir() / "run"
        init = run_cli(["init", "--system", "shop", "--repo", f"SHOP={built_repo()}", "--out", str(out)])
        self.assertEqual(init.returncode, 0, init.stderr)
        detect = run_cli(["detect", "--run", str(out)])
        self.assertEqual(detect.returncode, 0, detect.stderr)
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(manifest["modules"]["SHOP"]),
                         ["src/catalog", "src/checkout", "src/exports", "src/jobs", "src/orders", "src/payments"])
        base = run_cli(["baseline", "--run", str(out), "--timeout", "120"])
        self.assertEqual(base.returncode, 0, base.stdout + base.stderr)
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["steps"]["baseline"], "done")
        result = manifest["baseline"]["SHOP"]["result"]
        self.assertEqual((result["passed"], result["failed"], result["total"]), (14, 0, 14))

    def test_eval_accepts_a_run_of_the_bench(self):
        out = make_dir() / "run"
        self.assertEqual(run_cli(["init", "--system", "shop", "--repo", f"SHOP={built_repo()}", "--out",
                                  str(out)]).returncode, 0)
        result = run_cli(["eval", "--run", str(out), "--reference", str(BENCH / "key.json")])
        self.assertEqual(result.returncode, 1, result.stderr)  # no findings yet: a FAIL, not a usage error
        self.assertIn("candidate score: 0/14 (pass at 9)", result.stdout)
        self.assertIn("decoys hit: 0/7; false-positive findings: 0 (allowed 1)", result.stdout)


if __name__ == "__main__":
    unittest.main()
