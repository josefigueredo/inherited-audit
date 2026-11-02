from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

from helpers import ROOT, make_dir, make_git_repo, run_cli, write_tree

from ia import evaluate
from ia.run import UsageError


def ref(name="1", path="BACK/src/a.ts", a=10, b=20):
    return {"ref": name, "title": "t", "cites": [{"cite": path, "from": a, "to": b}], "dimension": "race",
            "cause_keywords": ["boom"]}


def finding(fid="C-01", path="BACK/src/a.ts", a=10, b=20, verdict="confirmed", report="correctness",
            title="the BOOM happens", what="", red=""):
    return {"id": fid, "report": report, "verdict": verdict, "title": title, "what_happens": what, "red_reason": red,
            "evidence": [{"cite": path, "from": a, "to": b}]}


class MatchTest(unittest.TestCase):
    def test_overlap_within_slack_matches(self):
        self.assertTrue(evaluate.match(ref(), finding(a=34, b=40)))      # 14 lines after the ref range
        self.assertTrue(evaluate.match(ref(), finding(a=1, b=10)))  # overlaps directly
        self.assertFalse(evaluate.match(ref(), finding(a=36, b=40)))     # 16 lines away
        self.assertTrue(evaluate.match(ref(), finding(a=36, b=40), slack=16))

    def test_commit_suffix_is_ignored(self):
        self.assertTrue(evaluate.match(ref(), finding(path="BACK/src/a.ts@abc1234")))
        self.assertTrue(evaluate.match(ref(path="BACK/src/a.ts@abc1234"), finding()))
        self.assertFalse(evaluate.match(ref(), finding(path="BACK/src/b.ts@abc1234")))

    def test_different_path_no_match(self):
        self.assertFalse(evaluate.match(ref(), finding(path="BACK/src/b.ts")))
        self.assertFalse(evaluate.match(ref(), finding(path="FRONT/src/a.ts")))

    def test_discarded_finding_never_matches(self):
        self.assertFalse(evaluate.match(ref(), finding(verdict="discarded")))
        self.assertEqual(evaluate.score(self.reference([ref()]), [finding(verdict="discarded")])["found"], [])

    def test_quality_finding_can_match_a_reference(self):
        result = evaluate.score(self.reference([ref()]), [finding("Q-03", report="quality")])
        self.assertEqual(result["found"], ["1"])
        self.assertEqual(result["candidates"], {"1": ["Q-03"]})

    def test_two_findings_on_one_ref_count_once(self):
        result = evaluate.score(self.reference([ref()]), [finding("C-01"), finding("Q-02", report="quality")])
        self.assertEqual(result["score"], 1)
        self.assertEqual(result["candidates"]["1"], ["C-01", "Q-02"])

    def test_score_pass_threshold(self):
        refs = [ref(str(i), path=f"BACK/src/f{i}.ts") for i in range(10)]
        ref_doc = self.reference(refs)
        seven = [finding(f"C-{i:02d}", path=f"BACK/src/f{i}.ts") for i in range(7)]
        result = evaluate.score(ref_doc, seven)
        self.assertEqual((result["score"], result["pass"], len(result["missed"])), (7, True, 3))
        six = evaluate.score(ref_doc, seven[:6])
        self.assertEqual((six["score"], six["pass"]), (6, False))
        self.assertEqual(six["missed"], ["6", "7", "8", "9"])

    def test_one_finding_cannot_score_two_refs(self):
        refs = [ref("1", a=10, b=20), ref("2", a=30, b=40)]   # both within slack of a finding at 25-26
        both = finding("C-01", a=25, b=26)
        self.assertEqual(evaluate.score(self.reference(refs), [both])["score"], 1)
        # augmenting path: C-01 fits both refs, C-02 only ref 1; the best matching scores 2
        result = evaluate.score(self.reference(refs), [both, finding("C-02", a=1, b=5)])
        self.assertEqual(result["score"], 2)
        self.assertEqual(result["assigned"], {"1": "C-02", "2": "C-01"})
        self.assertEqual(result["candidates"]["1"], ["C-01", "C-02"])

    def test_wide_evidence_span_is_ignored(self):
        self.assertFalse(evaluate.match(ref(), finding(a=1, b=99999)))
        self.assertTrue(evaluate.match(ref(), finding(a=1, b=80)))
        self.assertFalse(evaluate.match(ref(), finding(a=1, b=81)))

    def test_alias_names_do_not_matter_only_top_level_paths(self):
        reference = self.reference([ref("1", path="BACK/src/a.ts")])
        reference["aliases"] = {"BACK": "svc/api"}
        repos = [{"alias": "API", "subdir": "svc/api"}]
        self.assertEqual(evaluate.score(reference, [finding(path="API/src/a.ts")], repos=repos)["found"], ["1"])
        # same alias name but a different directory does not match
        other = [{"alias": "BACK", "subdir": "svc/worker"}]
        self.assertEqual(evaluate.score(reference, [finding(path="BACK/src/a.ts")], repos=other)["found"], [])

    def test_root_alias_distinguishes_repo_root_files(self):
        reference = self.reference([ref("1", path="BACK_ROOT/package.json")])
        reference["aliases"] = {"BACK": "svc/api", "BACK_ROOT": "svc"}
        repos = [{"alias": "BACK", "subdir": "svc/api"}, {"alias": "ROOT", "subdir": "svc"}]
        self.assertEqual(evaluate.score(reference, [finding(path="ROOT/package.json")], repos=repos)["found"], ["1"])
        self.assertEqual(evaluate.score(reference, [finding(path="BACK/package.json")], repos=repos)["found"], [])

    def test_check_sha(self):
        reference = self.reference([ref("1", path="BACK/src/a.ts")])
        reference["aliases"] = {"BACK": "svc/api"}
        repos = [{"alias": "BACK", "subdir": "svc/api", "sha": "ab12cd3" + "0" * 33}]
        reference["sha"] = "ab12cd3" + "0" * 33
        evaluate.check_sha(reference, repos)
        reference["sha"] = "ab12cd3"
        evaluate.check_sha(reference, repos)
        reference["sha"] = "ffffffff"
        with self.assertRaises(UsageError) as cm:
            evaluate.check_sha(reference, repos)
        self.assertIn("ffffffff", str(cm.exception))
        self.assertIn("ab12cd3", str(cm.exception))
        reference["sha"] = "abc"
        with self.assertRaises(UsageError):
            evaluate.check_sha(reference, repos)

    def test_place_without_cause_does_not_count(self):
        other = finding("C-02", title="something else", what="unrelated")
        result = evaluate.score(self.reference([ref()]), [other])
        self.assertEqual((result["score"], result["found"], result["missed"]), (0, [], ["1"]))
        self.assertEqual(result["place_only"], {"1": ["C-02"]})

    def test_keyword_is_case_insensitive_in_title_what_or_red_reason(self):
        for kw in ({"title": "A Boom"}, {"what": "it goes BOOM"}, {"red": "boom!"}):
            title = kw.get("title", "x")
            result = evaluate.score(self.reference([ref()]), [finding(title=title, what=kw.get("what", ""), red=kw.get("red", ""))])
            self.assertEqual(result["found"], ["1"], kw)

    def test_other_finding_with_cause_wins_over_place_only_one(self):
        wrong = finding("C-01", title="nothing")
        right = finding("C-02", title="boom")
        result = evaluate.score(self.reference([ref()]), [wrong, right])
        self.assertEqual(result["assigned"], {"1": "C-02"})
        self.assertEqual(result["candidates"], {"1": ["C-02"]})
        self.assertEqual(result["place_only"], {"1": ["C-01"]})

    def test_keywords_match_at_word_start_only(self):
        hang = ref(); hang["cause_keywords"] = ["hang"]
        self.assertEqual(evaluate.score(self.reference([hang]), [finding(title="a change here")])["score"], 0)
        self.assertEqual(evaluate.score(self.reference([hang]), [finding(title="it hangs forever")])["score"], 1)
        ddl = ref(); ddl["cause_keywords"] = ["ddl"]
        self.assertEqual(evaluate.score(self.reference([ddl]), [finding(title="the middleware")])["score"], 0)
        self.assertEqual(evaluate.score(self.reference([ddl]), [finding(title="runs DDL at boot")])["score"], 1)
        stem = ref(); stem["cause_keywords"] = ["transacci"]
        self.assertEqual(evaluate.score(self.reference([stem]), [finding(title="sin transacción")])["score"], 1)

    def test_load_reference_rejects_short_keywords(self):
        tmp = make_dir()
        item = ref(); item["cause_keywords"] = ["ddl"]
        write_tree(tmp, {"r.json": json.dumps({"items": [item]})})
        with self.assertRaises(UsageError) as cm:
            evaluate.load_reference(tmp / "r.json")
        self.assertIn("ddl", str(cm.exception))

    def test_reference_without_keywords_never_counts(self):
        item = ref()
        del item["cause_keywords"]
        self.assertEqual(evaluate.score(self.reference([item]), [finding()])["score"], 0)

    def test_report_lines_headline_and_place_only(self):
        reference = self.reference([ref("1"), ref("2", path="BACK/src/b.ts")])
        result = evaluate.score(reference, [finding("C-01"), finding("C-02", path="BACK/src/b.ts", title="no")])
        lines = evaluate.report_lines(reference, result)
        self.assertIn("candidate score: 1/2 (pass at 7) \u2014 confirm every pair by reading both", lines)
        text = "\n".join(lines)
        self.assertIn("same place, cause not confirmed (1), not counted:", text)
        self.assertNotIn("mismo lugar", text)
        self.assertIn("C-02", text)

    @staticmethod
    def reference(items):
        return {"system": "x", "sha": "0" * 40, "pass_at": 7, "items": items}


def decoy(name="D1", path="BACK/src/a.ts", a=60, b=70, keywords=("injection",)):
    return {"ref": name, "title": "looks unsafe, is not", "cites": [{"cite": path, "from": a, "to": b}],
            "claim_keywords": list(keywords)}


class DecoyTest(unittest.TestCase):
    """Decoys are correct code that looks suspicious: a finding that claims their problem is a false positive."""

    @staticmethod
    def reference(items, decoys=None, **extra):
        doc = {"system": "x", "sha": "0" * 40, "pass_at": 1, "items": items, **extra}
        if decoys is not None:
            doc["decoys"] = decoys
        return doc

    def test_finding_on_a_decoy_with_its_claim_is_a_false_positive(self):
        result = evaluate.score(self.reference([ref()], [decoy()]),
                                [finding("C-02", a=62, b=64, title="SQL injection in the query")])
        self.assertEqual(result["decoy_hits"], {"D1": ["C-02"]})

    def test_decoy_needs_place_and_claim(self):
        reference = self.reference([ref()], [decoy()])
        near_other_claim = finding("C-02", a=62, b=64, title="a slow loop")
        far_same_claim = finding("C-03", path="BACK/src/b.ts", a=62, b=64, title="SQL injection")
        self.assertEqual(evaluate.score(reference, [near_other_claim, far_same_claim])["decoy_hits"], {})

    def test_discarded_finding_never_hits_a_decoy(self):
        result = evaluate.score(self.reference([ref()], [decoy()]),
                                [finding("C-02", a=62, b=64, title="injection", verdict="discarded")])
        self.assertEqual(result["decoy_hits"], {})

    def test_max_decoy_hits_fails_a_run_with_full_recall(self):
        reference = self.reference([ref()], [decoy()], max_decoy_hits=0)
        noisy = [finding("C-01"), finding("C-02", a=62, b=64, title="injection here")]
        self.assertFalse(evaluate.score(reference, noisy)["pass"])
        self.assertTrue(evaluate.score(reference, noisy[:1])["pass"])

    def test_without_max_decoy_hits_pass_is_recall_only(self):
        noisy = [finding("C-01"), finding("C-02", a=62, b=64, title="injection here")]
        self.assertTrue(evaluate.score(self.reference([ref()], [decoy()]), noisy)["pass"])

    def test_report_lists_decoy_hits_and_areas(self):
        items = [dict(ref("1"), area="races-distributed"), dict(ref("2", path="BACK/src/b.ts"), area="security")]
        reference = self.reference(items, [decoy()], max_decoy_hits=0)
        result = evaluate.score(reference, [finding("C-01"), finding("C-02", a=62, b=64, title="injection")])
        text = "\n".join(evaluate.report_lines(reference, result))
        self.assertIn("decoys hit: 1/1; false-positive findings: 1 (allowed 0)", text)
        self.assertIn("  D1  looks unsafe, is not: C-02", text)
        self.assertIn("by area:", text)
        self.assertIn("  races-distributed: 1/1", text)
        self.assertIn("  security: 0/1", text)

    def test_two_findings_on_one_decoy_are_two_false_positives(self):
        reference = self.reference([ref()], [decoy()], max_decoy_hits=1)
        noisy = [finding("C-01"), finding("C-02", a=62, b=64, title="injection"),
                 finding("C-03", a=66, b=68, title="injection again")]
        result = evaluate.score(reference, noisy)
        self.assertEqual(result["false_positives"], 2)
        self.assertFalse(result["pass"])

    def test_reference_without_decoys_or_areas_reports_as_before(self):
        reference = {"system": "x", "sha": "0" * 40, "pass_at": 1, "items": [ref()]}
        text = "\n".join(evaluate.report_lines(reference, evaluate.score(reference, [finding()])))
        self.assertNotIn("decoy", text)
        self.assertNotIn("by area", text)

    def write(self, doc):
        tmp = make_dir()
        (tmp / "r.json").write_text(json.dumps(doc), encoding="utf-8")
        return tmp / "r.json"

    def test_load_rejects_a_decoy_next_to_an_item(self):
        path = self.write(self.reference([ref()], [decoy(a=25, b=30)]))
        with self.assertRaises(UsageError) as ctx:
            evaluate.load_reference(path)
        self.assertIn("D1", str(ctx.exception))

    def test_load_rejects_a_decoy_without_claim_keywords_or_with_short_ones(self):
        for bad in ((), ("sql",)):
            with self.assertRaises(UsageError):
                evaluate.load_reference(self.write(self.reference([ref()], [decoy(keywords=bad)])))

    def test_load_accepts_a_decoy_far_from_items(self):
        self.assertEqual(len(evaluate.load_reference(self.write(self.reference([ref()], [decoy()])))["decoys"]), 1)


class ReferenceFileTest(unittest.TestCase):
    def test_reference_file_is_valid(self):
        path = os.environ.get("IA_EVAL_REFERENCE")
        if not path:
            self.skipTest("set IA_EVAL_REFERENCE to the reference file to run this test")
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self.assertEqual(data["pass_at"], 7)
        self.assertEqual(len(data["sha"]), 40)
        self.assertIsInstance(data["notes"], str)
        self.assertEqual(set(data["aliases"]), {"BACK", "FRONT"})
        self.assertEqual(len(data["items"]), 10)
        self.assertEqual(len({i["ref"] for i in data["items"]}), 10)
        for item in data["items"]:
            self.assertIn(item["dimension"], ("race", "distributed"))
            self.assertTrue(item["title"])
            self.assertGreaterEqual(len(item["cites"]), 1)
            self.assertTrue(1 <= len(item["cause_keywords"]) <= 3, item["ref"])
            for kw in item["cause_keywords"]:
                self.assertEqual(kw, kw.lower())
                self.assertGreaterEqual(len(kw.strip()), 4)
            for c in item["cites"]:
                self.assertTrue(c["cite"].startswith(("BACK/", "FRONT/")))
                self.assertLessEqual(c["from"], c["to"])


class EvalCliTest(unittest.TestCase):
    def run_with(self, n_found, sha_ok=True):
        tmp = make_dir()
        repo, sha = make_git_repo({"a.txt": "x"})
        refs = [ref(str(i), path=f"BACK/src/f{i}.ts") for i in range(10)]
        write_tree(tmp, {"ref.json": json.dumps({"system": "x", "sha": sha if sha_ok else "f" * 40, "pass_at": 7,
                                                 "aliases": {"BACK": ""}, "items": refs})})
        init = run_cli(["init", "--system", "x", "--repo", f"BACK={repo}", "--out", str(tmp / "run")])
        self.assertEqual(init.returncode, 0, init.stderr)
        for i in range(n_found):
            doc = {"report": "correctness", "category": "c", "dimension": "race", "title": "t", "verdict": "candidate",
                   "severity": "low", "confidence": "unverified", "source": "s", "what_happens": "boom",
                   "evidence": [{"cite": f"BACK/src/f{i}.ts", "from": 10, "to": 12, "note": ""}]}
            write_tree(tmp, {"doc.json": json.dumps(doc)})
            added = run_cli(["finding", "add", "--run", str(tmp / "run"), str(tmp / "doc.json")])
            self.assertEqual(added.returncode, 0, added.stderr)
        return run_cli(["eval", "--run", str(tmp / "run"), "--reference", "ref.json"], cwd=tmp)

    def test_cli_pass(self):
        result = self.run_with(7)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("candidate score: 7/10 (pass at 7)", result.stdout)
        self.assertIn("PASS", result.stdout)
        self.assertIn("C-01", result.stdout)

    def test_cli_fail(self):
        result = self.run_with(6)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("candidate score: 6/10 (pass at 7)", result.stdout)
        self.assertIn("FAIL", result.stdout)
        self.assertIn("missed", result.stdout)

    def test_cli_sha_mismatch_is_usage_error(self):
        result = self.run_with(7, sha_ok=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("ffffffff", result.stderr)

    def test_cli_bad_reference_is_usage_error(self):
        tmp = make_dir()
        repo, _ = make_git_repo({"a.txt": "x"})
        run_cli(["init", "--system", "x", "--repo", f"BACK={repo}", "--out", str(tmp / "run")])
        result = run_cli(["eval", "--run", str(tmp / "run"), "--reference", str(tmp / "nope.json")])
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
