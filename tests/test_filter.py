from __future__ import annotations

import json
import unittest
from pathlib import Path

from helpers import make_git_repo, run_cli

from ia import filter as filtermod
from ia import findings as findingsmod
from ia import run as runmod
from test_branches import new_run


def cfind(fid="C-01", verdict="confirmed", exclude="", confidence="docs", **extra):
    f = {"id": fid, "report": "correctness", "verdict": verdict, "exclude": exclude, "confidence": confidence}
    f.update(extra)
    return f


def qfind(fid="Q-01", verdict="confirmed", refute="", confidence="docs", severity="low", effort="S"):
    return {"id": fid, "report": "quality", "verdict": verdict, "confidence": confidence, "severity": severity,
            "effort": effort, "contrast": {"verdict": refute}}


class ApplyTest(unittest.TestCase):
    def test_refactor_excluded_from_correctness(self):
        items = [cfind("C-01"), cfind("C-02", exclude="refactor")]
        filtermod.apply(items)
        self.assertEqual([f["shown"] for f in items], [True, False])

    def test_unverified_never_shown(self):
        items = [cfind("C-01", confidence="unverified"), qfind("Q-01", confidence="unverified")]
        filtermod.apply(items)
        self.assertEqual([f["shown"] for f in items], [False, False])

    def test_correctness_needs_confirmed(self):
        items = [cfind("C-01", verdict="candidate"), cfind("C-02", verdict="blocked"), cfind("C-03", verdict="discarded")]
        filtermod.apply(items)
        self.assertEqual([f["shown"] for f in items], [False, False, False])

    def test_refuted_quality_hidden(self):
        items = [qfind("Q-01", refute="refute"), qfind("Q-02", refute="agree"), qfind("Q-03", verdict="discarded"),
                 qfind("Q-04", verdict="candidate"), qfind("Q-05", refute="unsure")]
        filtermod.apply(items)
        self.assertEqual([f["shown"] for f in items], [False, True, False, True, True])

    def test_duplicates_hidden_in_both_reports_and_counted(self):
        dup_q = qfind("Q-02")
        dup_q.update({"exclude": "duplicate", "duplicate_of": "Q-01"})
        items = [cfind("C-01"), cfind("C-02", exclude="duplicate", duplicate_of="C-01"), qfind("Q-01"), dup_q]
        counts = filtermod.apply(items)
        self.assertEqual([f["shown"] for f in items], [True, False, True, False])
        self.assertEqual(counts, {"correctness": {"shown": 1, "total": 2, "duplicates": 1},
                                  "quality": {"shown": 1, "total": 2, "duplicates": 1}})

    def test_no_duplicates_key_when_there_are_none(self):
        self.assertEqual(filtermod.apply([cfind("C-01")])["correctness"], {"shown": 1, "total": 1})

    def _refuted(self, report, **contrast):
        f = cfind("C-01") if report == "correctness" else qfind("Q-01")
        f["contrast"] = {"verdict": "refute", **contrast}
        return f

    def test_refute_on_severity_keeps_finding_visible_in_both_reports(self):
        items = [self._refuted("correctness", scope="severity"), self._refuted("quality", scope="severity")]
        filtermod.apply(items)
        self.assertEqual([f["shown"] for f in items], [True, True])

    def test_refute_on_finding_or_empty_scope_hides_in_both_reports(self):
        items = [self._refuted("correctness", scope="finding"), self._refuted("quality", scope="finding"),
                 self._refuted("correctness", scope=""), self._refuted("quality")]
        filtermod.apply(items)
        self.assertEqual([f["shown"] for f in items], [False, False, False, False])

    def test_rebutted_refute_on_finding_stays_visible(self):
        items = [self._refuted("correctness", scope="finding", rebutted=True),
                 self._refuted("quality", scope="", rebutted=True),
                 self._refuted("quality", scope="finding", rebutted=False)]
        filtermod.apply(items)
        self.assertEqual([f["shown"] for f in items], [True, True, False])

    def test_rebutted_does_not_rescue_unverified_or_discarded(self):
        a = self._refuted("quality", scope="finding", rebutted=True)
        a["verdict"] = "discarded"
        b = self._refuted("correctness", scope="finding", rebutted=True)
        b["confidence"] = "unverified"
        filtermod.apply([a, b])
        self.assertEqual([a["shown"], b["shown"]], [False, False])

    def test_counts(self):
        items = [cfind("C-01"), cfind("C-02", exclude="feature"), qfind("Q-01"), qfind("Q-02", refute="refute"),
                 qfind("Q-03")]
        self.assertEqual(filtermod.apply(items), {"correctness": {"shown": 1, "total": 2},
                                                  "quality": {"shown": 2, "total": 3}})

    def test_start_here_order_and_size(self):
        items = [qfind("Q-01", severity="low", effort="S"), qfind("Q-02", severity="high", effort="L"),
                 qfind("Q-03", severity="high", effort="S"), qfind("Q-04", severity="medium", effort="M"),
                 qfind("Q-05", severity="medium", effort="S"), qfind("Q-06", severity="high", effort="S"),
                 qfind("Q-07", severity="low", effort="L")]
        filtermod.apply(items)
        self.assertEqual(filtermod.start_here(items), ["Q-03", "Q-06", "Q-02", "Q-05", "Q-04"])
        self.assertEqual(filtermod.start_here(items, 2), ["Q-03", "Q-06"])

    def test_start_here_skips_hidden_and_correctness(self):
        items = [cfind("C-01"), qfind("Q-01", refute="refute", severity="high"), qfind("Q-02")]
        filtermod.apply(items)
        self.assertEqual(filtermod.start_here(items), ["Q-02"])

    def test_start_here_min_three_means_all_when_fewer(self):
        items = [qfind("Q-01"), qfind("Q-02")]
        filtermod.apply(items)
        self.assertEqual(filtermod.start_here(items, 1), ["Q-01", "Q-02"])

    def test_start_here_respects_n_when_three_or_more_shown(self):
        items = [qfind(f"Q-0{i}") for i in range(1, 6)]
        filtermod.apply(items)
        self.assertEqual(len(filtermod.start_here(items, 1)), 1)


class CliTest(unittest.TestCase):
    def test_filter_cli_writes_shown_manifest_and_step(self):
        repo, _ = make_git_repo({"a.py": "x\n"})
        run = new_run(repo)
        ev = [{"cite": "BACK/a.py", "from": 1, "to": 1, "note": ""}]
        base = {"category": "x", "dimension": "bug", "title": "t", "severity": "low", "confidence": "docs",
                "source": "t", "what_happens": "w", "evidence": ev}
        findingsmod.add(run, {**base, "report": "correctness", "verdict": "confirmed"})
        findingsmod.add(run, {**base, "report": "correctness", "verdict": "confirmed", "exclude": "refactor"})
        findingsmod.add(run, {**base, "report": "quality", "verdict": "confirmed", "suggestion": "s", "effort": "S"})
        result = run_cli(["filter", "--run", str(run)])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("correctness: showing 1 of 2", result.stdout)
        self.assertIn("quality: showing 1 of 1", result.stdout)
        manifest = runmod.load(run)
        self.assertEqual(manifest["filter"], {"counts": {"correctness": {"shown": 1, "total": 2},
                                                          "quality": {"shown": 1, "total": 1}},
                                              "start_here": ["Q-01"]})
        self.assertEqual(manifest["steps"]["filter"], "done")
        shown = {f["id"]: f["shown"] for f in findingsmod.load_all(run)}
        self.assertEqual(shown, {"C-01": True, "C-02": False, "Q-01": True})

    def test_filter_rejects_a_duplicate_whose_target_became_a_duplicate(self):
        repo, _ = make_git_repo({"a.py": "x\n"})
        run = new_run(repo)
        ev = [{"cite": "BACK/a.py", "from": 1, "to": 1, "note": ""}]
        base = {"report": "correctness", "category": "x", "dimension": "bug", "title": "t", "severity": "low",
                "confidence": "docs", "source": "t", "what_happens": "w", "evidence": ev, "verdict": "confirmed"}
        for _ in range(3):
            findingsmod.add(run, base)
        findingsmod.update(run, "C-02", {"exclude": "duplicate", "duplicate_of": "C-01"})
        path = run / "findings" / "C-01.json"
        hand = json.loads(path.read_text())
        hand.update({"exclude": "duplicate", "duplicate_of": "C-03"})
        path.write_text(json.dumps(hand))
        result = run_cli(["filter", "--run", str(run)])
        self.assertEqual(result.returncode, 1)
        self.assertIn("C-02", result.stderr)
        self.assertIsNone(json.loads((run / "findings" / "C-03.json").read_text())["shown"])

    def test_filter_validates_everything_before_writing(self):
        repo, _ = make_git_repo({"a.py": "x\n"})
        run = new_run(repo)
        ev = [{"cite": "BACK/a.py", "from": 1, "to": 1, "note": ""}]
        findingsmod.add(run, {"report": "correctness", "category": "x", "dimension": "bug", "title": "t",
                              "verdict": "confirmed", "severity": "low", "confidence": "docs", "source": "t",
                              "what_happens": "w", "evidence": ev})
        bad = json.loads((run / "findings" / "C-01.json").read_text())
        bad["id"] = "C-02"
        del bad["title"]
        (run / "findings" / "C-02.json").write_text(json.dumps(bad))
        result = run_cli(["filter", "--run", str(run)])
        self.assertEqual(result.returncode, 1)
        self.assertIn("C-02", result.stderr)
        self.assertIsNone(json.loads((run / "findings" / "C-01.json").read_text())["shown"])
        self.assertNotIn("filter", runmod.load(run))

    def test_filter_cli_requires_run(self):
        self.assertEqual(run_cli(["filter"]).returncode, 2)


if __name__ == "__main__":
    unittest.main()
