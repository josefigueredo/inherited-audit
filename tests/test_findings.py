from __future__ import annotations

import json
import unittest
from pathlib import Path

from helpers import SKILL, make_dir, make_git_repo, run_cli

from ia import findings, run as runmod


def candidate(**over) -> dict:
    f = {"report": "correctness", "category": "validation", "dimension": "bug", "title": "Off by one",
         "verdict": "candidate", "severity": "high", "confidence": "unverified", "source": "worker-a",
         "what_happens": "The loop skips the last item.",
         "evidence": [{"cite": "BACK/src/x.ts", "from": 10, "to": 24, "note": "loop"}]}
    f.update(over)
    return f


def quality(**over) -> dict:
    f = candidate(report="quality", dimension="code", suggestion="Extract a function", effort="S")
    f.update(over)
    return f


def make_run() -> Path:
    repo, _ = make_git_repo({"a.txt": "x\n"})
    return runmod.init_run("sys", [("BACK", repo, "")], make_dir() / "run", "es", False, "unknown")


KEY = "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7VJTUt9Us8cKj\n-----END PRIVATE KEY-----"
AWS = "AKIAABCDEFGHIJKLMNOP"


class MaskOnWriteTest(unittest.TestCase):
    def raw(self, run):
        return "".join(p.read_text(encoding="utf-8") for p in (run / "findings").glob("*.json"))

    def test_add_masks_every_prose_field(self):
        run = make_run()
        findings.add(run, candidate(
            what_happens=f"Leaks {KEY}", fix_summary=AWS, reason=AWS, red_reason=KEY,
            audience={"title": "", "what_happens": AWS, "fix_summary": AWS},
            evidence=[{"cite": "BACK/src/x.ts", "from": 1, "to": 2, "note": f"k {AWS}"}],
            tests=[{"path": "t", "red": "", "green": "", "note": AWS}], contrast={"note": AWS}))
        text = self.raw(run)
        self.assertNotIn(AWS, text)
        self.assertNotIn("MIIEvQIBADANBg", text)

    def test_title_and_single_line_key_are_masked(self):
        run = make_run()
        one = '"-----BEGIN PRIVATE KEY-----\\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcw\\n-----END PRIVATE KEY-----\\n"'
        fid = findings.add(run, candidate(title=f"T {AWS}", what_happens=f"k = {one}"))
        text = self.raw(run)
        self.assertNotIn(AWS, text)
        self.assertNotIn("MIIEvQIBADANBg", text)
        findings.update(run, fid, {"title": f"U {AWS}"})
        self.assertNotIn(AWS, self.raw(run))

    def test_measurement_is_masked_on_add_and_set(self):
        run = make_run()
        fid = findings.add(run, quality(measurement={"tool": f"rg {AWS}", "value": f"key {AWS} found"}))
        self.assertNotIn(AWS, self.raw(run))
        findings.update(run, fid, {"measurement.tool": f"grep {AWS}", "measurement.value": AWS})
        self.assertNotIn(AWS, self.raw(run))
        self.assertTrue(findings.load_all(run)[0]["measurement"]["tool"].startswith("grep AKIA"))

    def test_contrast_rebuttal_is_masked_and_validated(self):
        run = make_run()
        fid = findings.add(run, candidate(contrast={"verdict": "refute", "scope": "finding", "rebutted": True,
                                                    "note": "n", "rebuttal": f"holds {AWS}"}))
        self.assertNotIn(AWS, self.raw(run))
        self.assertEqual(findings._fill({})["contrast"]["rebuttal"], "")
        with self.assertRaises(findings.FindingError):
            findings.update(run, fid, {"contrast.rebuttal": 3})

    def test_set_masks_prose(self):
        run = make_run()
        fid = findings.add(run, candidate())
        findings.update(run, fid, {"what_happens": f"x {AWS}", "contrast.note": AWS, "suggestion": AWS})
        self.assertNotIn(AWS, self.raw(run))


class ValidateTests(unittest.TestCase):
    def test_valid_minimal_correctness_candidate_passes(self):
        self.assertEqual(findings.validate(candidate(id="C-01")), [])

    def test_missing_required_fields_listed(self):
        required = ["id", "report", "category", "dimension", "title", "verdict", "severity", "confidence",
                    "source", "what_happens", "evidence"]
        problems = findings.validate({})
        for name in required:
            self.assertTrue(any(name in p for p in problems), name)

    def test_confirmed_execution_requires_branch_sha_tests_red_reason(self):
        f = candidate(id="C-01", verdict="confirmed", confidence="execution")
        problems = findings.validate(f)
        for name in ("branch", "sha_test", "tests", "red_reason"):
            self.assertTrue(any(name in p for p in problems), name)
        f.update(branch="fix/x", sha_test="abc", tests=[{"path": "t", "red": "", "green": "", "note": ""}],
                 red_reason="fails")
        self.assertEqual(findings.validate(f), [])

    def test_supply_chain_confirmed_by_execution_needs_measurement_not_branch(self):
        for dim in ("supply-chain", "container"):
            f = candidate(id="C-01", dimension=dim, verdict="confirmed", confidence="execution",
                          measurement={"tool": "osv-scanner --lockfile package-lock.json", "value": "2 advisories"},
                          outputs={"red": "", "green": "", "suite": "outputs/osv-BACK.txt"})
            self.assertEqual(findings.validate(f), [], dim)
            f.update(outputs={"red": "", "green": "", "suite": ""},
                     evidence=[{"cite": "BACK/Dockerfile", "from": 1, "to": 3, "note": "see outputs/trivy-BACK.txt"}])
            self.assertEqual(findings.validate(f), [], dim)

    def test_supply_chain_confirmed_by_execution_without_measurement_or_output_refused(self):
        f = candidate(id="C-01", dimension="supply-chain", verdict="confirmed", confidence="execution")
        problems = findings.validate(f)
        self.assertTrue(any("measurement.tool" in p for p in problems), problems)
        self.assertTrue(any("outputs.suite" in p for p in problems), problems)
        self.assertFalse(any("branch" in p or "red_reason" in p for p in problems), problems)
        f.update(measurement={"tool": "trivy image app", "value": "runs as root"})
        problems = findings.validate(f)
        self.assertTrue(any("outputs.suite" in p for p in problems), problems)
        self.assertFalse(any("measurement.tool" in p for p in problems), problems)

    def history_secret(self, **over):
        f = candidate(id="C-01", category="secrets", dimension="security", verdict="confirmed",
                      confidence="execution", source="gitleaks",
                      measurement={"tool": "gitleaks detect --redact --log-opts=--all", "value": "aws-access-token: 1"},
                      outputs={"red": "", "green": "", "suite": "outputs/gitleaks-BACK.txt"},
                      evidence=[{"cite": "BACK/.env@3f9a1c2", "from": 1, "to": 1, "note": "value redacted"}])
        f.update(over)
        return f

    def test_history_secret_confirmed_by_scanner_needs_no_branch(self):
        self.assertEqual(findings.validate(self.history_secret()), [])
        noted = self.history_secret(outputs={"red": "", "green": "", "suite": ""},
                                    evidence=[{"cite": "BACK/.env@3f9a1c2", "from": 1, "to": 1,
                                               "note": "redacted output in outputs/gitleaks-BACK.txt"}])
        self.assertEqual(findings.validate(noted), [])

    def test_security_with_only_history_cites_uses_the_non_code_rule(self):
        f = self.history_secret(measurement={"tool": "", "value": ""})
        problems = findings.validate(f)
        self.assertTrue(any("measurement.tool" in p for p in problems), problems)
        self.assertFalse(any("branch" in p or "red_reason" in p for p in problems), problems)

    def test_security_scanner_without_saved_output_refused(self):
        f = self.history_secret(outputs={"red": "", "green": "", "suite": ""})
        problems = findings.validate(f)
        self.assertTrue(any("outputs.suite" in p for p in problems), problems)

    def test_security_on_current_code_without_scanner_still_needs_a_red_branch(self):
        f = self.history_secret(measurement={"tool": "", "value": ""},
                                evidence=[{"cite": "BACK/.env@3f9a1c2", "from": 1, "to": 1, "note": ""},
                                          {"cite": "BACK/src/x.ts", "from": 1, "to": 2, "note": ""}])
        problems = findings.validate(f)
        for name in ("branch", "sha_test", "tests", "red_reason"):
            self.assertTrue(any(name in p for p in problems), (name, problems))
        bug = self.history_secret(dimension="bug")
        self.assertTrue(any("red_reason" in p for p in findings.validate(bug)))

    def test_schema_md_history_secret_example_is_accepted(self):
        text = (SKILL / "references" / "schema.md").read_text(encoding="utf-8")
        section = text.split("**Secrets that exist only in history**", 1)[1]
        block = section.split("```json", 1)[1].split("```", 1)[0]
        example = json.loads(block)
        self.assertEqual(example["dimension"], "security")
        self.assertIn("@", example["evidence"][0]["cite"])
        run = make_run()
        fid = findings.add(run, example)
        self.assertTrue(fid.startswith("C-"))
        skill_md = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("outputs.suite", skill_md.split("**Secrets present only in git history**", 1)[1][:600])

    def test_supply_chain_confirmed_by_docs_needs_nothing_extra(self):
        f = candidate(id="C-01", dimension="container", verdict="confirmed", confidence="docs")
        self.assertEqual(findings.validate(f), [])

    def test_quality_requires_suggestion_and_effort(self):
        problems = findings.validate(quality(id="Q-01", suggestion="", effort=""))
        self.assertTrue(any("suggestion" in p for p in problems))
        self.assertTrue(any("effort" in p for p in problems))

    def test_enum_values_enforced(self):
        problems = findings.validate(candidate(id="C-01", severity="critical"))
        self.assertTrue(any("severity" in p and "high" in p and "medium" in p and "low" in p for p in problems))

    def test_empty_enums_allowed_where_contract_says(self):
        f = candidate(id="C-01", effort="", exclude="", contrast={"verdict": ""})
        self.assertEqual(findings.validate(f), [])

    def test_contrast_scope_and_rebutted_validated(self):
        f = candidate(id="C-01")
        f["contrast"] = {"verdict": "refute", "scope": "severity", "rebutted": True}
        self.assertEqual(findings.validate(f), [])
        f["contrast"] = {"verdict": "refute", "scope": "everything"}
        self.assertTrue(any("contrast.scope" in p and "'severity'" in p for p in findings.validate(f)))
        f["contrast"] = {"verdict": "refute", "scope": "", "rebutted": "yes"}
        self.assertTrue(any("contrast.rebutted" in p for p in findings.validate(f)))

    def test_old_finding_without_scope_or_rebutted_validates_and_add_fills_defaults(self):
        f = candidate(id="C-01")
        f["contrast"] = {"model": "m", "same_family": False, "verdict": "refute"}
        self.assertEqual(findings.validate(f), [])
        filled = findings._fill(f)
        self.assertEqual(filled["contrast"]["scope"], "")
        self.assertIs(filled["contrast"]["rebutted"], False)
        self.assertEqual(findings._fill({})["contrast"]["scope"], "")

    def test_evidence_must_be_nonempty_list(self):
        self.assertTrue(findings.validate(candidate(id="C-01", evidence=[])))

    def test_id_prefix_must_match_report(self):
        self.assertTrue(findings.validate(candidate(id="Q-01")))


class StoreTests(unittest.TestCase):
    def test_add_assigns_sequential_ids_per_report(self):
        run = make_run()
        self.assertEqual(findings.add(run, candidate()), "C-01")
        self.assertEqual(findings.add(run, candidate()), "C-02")
        self.assertEqual(findings.add(run, quality()), "Q-01")
        stored = json.loads((run / "findings" / "C-01.json").read_text())
        self.assertEqual(stored["shown"], None)
        self.assertEqual(stored["contrast"]["same_family"], False)
        self.assertEqual(stored["audience"], {"title": "", "what_happens": "", "fix_summary": ""})

    def test_ids_use_max_plus_one_and_grow_past_99(self):
        run = make_run()
        findings.add(run, candidate(id="C-98"))
        self.assertEqual(findings.add(run, candidate()), "C-99")
        self.assertEqual(findings.add(run, candidate()), "C-100")

    def test_add_existing_id_refused(self):
        run = make_run()
        findings.add(run, candidate(id="C-05"))
        with self.assertRaises(findings.FindingError):
            findings.add(run, candidate(id="C-05"))

    def test_add_invalid_refused_and_nothing_written(self):
        run = make_run()
        with self.assertRaises(findings.FindingError) as ctx:
            findings.add(run, candidate(severity="critical"))
        self.assertTrue(ctx.exception.problems)
        self.assertEqual(list((run / "findings").glob("*.json")), [])

    def test_set_dotted_key_and_revalidates(self):
        run = make_run()
        fid = findings.add(run, candidate())
        out = findings.update(run, fid, {"contrast.verdict": "refute"})
        self.assertEqual(out["contrast"]["verdict"], "refute")
        before = (run / "findings" / f"{fid}.json").read_text()
        with self.assertRaises(findings.FindingError):
            findings.update(run, fid, {"severity": "critical"})
        self.assertEqual((run / "findings" / f"{fid}.json").read_text(), before)

    def test_set_unknown_id_refused(self):
        with self.assertRaises(findings.FindingError):
            findings.update(make_run(), "C-09", {"title": "x"})

    def test_set_cannot_change_id(self):
        run = make_run()
        fid = findings.add(run, candidate())
        with self.assertRaises(findings.FindingError):
            findings.update(run, fid, {"id": "C-09"})

    def test_load_all_sorted_by_id(self):
        run = make_run()
        findings.add(run, quality())
        findings.add(run, candidate(id="C-10"))
        findings.add(run, candidate(id="C-02"))
        self.assertEqual([f["id"] for f in findings.load_all(run)], ["C-02", "C-10", "Q-01"])


class CliTests(unittest.TestCase):
    def test_list_filters(self):
        run = make_run()
        findings.add(run, candidate())
        findings.add(run, candidate(verdict="discarded", reason="dup"))
        findings.add(run, quality())
        both = run_cli(["finding", "list", "--run", str(run)]).stdout
        self.assertEqual(len(both.strip().splitlines()), 3)
        r = run_cli(["finding", "list", "--run", str(run), "--report", "correctness", "--verdict", "discarded"])
        self.assertEqual(r.returncode, 0)
        self.assertEqual(len(r.stdout.strip().splitlines()), 1)
        self.assertIn("C-02", r.stdout)

    def test_cli_add_file_set_and_invalid(self):
        run = make_run()
        path = make_dir() / "f.json"
        path.write_text(json.dumps(candidate()))
        r = run_cli(["finding", "add", "--run", str(run), str(path)])
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "C-01"))
        r = run_cli(["finding", "set", "--run", str(run), "C-01", "contrast.verdict=refute", "severity=low",
                     "prod_files=[\"a.ts\"]"])
        self.assertEqual(r.returncode, 0, r.stderr)
        stored = json.loads((run / "findings" / "C-01.json").read_text())
        self.assertEqual((stored["severity"], stored["prod_files"]), ("low", ["a.ts"]))
        r = run_cli(["finding", "set", "--run", str(run), "C-01", "severity=critical"])
        self.assertEqual(r.returncode, 1)
        self.assertIn("severity", r.stderr)
        path.write_text(json.dumps(candidate(severity="nope")))
        self.assertEqual(run_cli(["finding", "add", "--run", str(run), str(path)]).returncode, 1)

    def test_cli_bad_json_and_bad_pair_are_usage_errors(self):
        run = make_run()
        path = make_dir() / "f.json"
        path.write_text("{nope")
        self.assertEqual(run_cli(["finding", "add", "--run", str(run), str(path)]).returncode, 2)
        self.assertEqual(run_cli(["finding", "set", "--run", str(run), "C-01", "noequals"]).returncode, 2)


if __name__ == "__main__":
    unittest.main()
