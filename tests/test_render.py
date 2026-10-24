from __future__ import annotations

import re
import unittest
from datetime import date
from pathlib import Path

from helpers import SKILL, git, make_dir, make_git_repo, run_cli

from ia import filter as filtermod
from ia import findings as findingsmod
from ia import hygiene as hygienemod
from ia import render as rendermod
from ia import run as runmod

SRC = "".join(f"line {n}\n" for n in range(1, 21))
REMOTE = "https://github.com/o/r"


def new_run(remote=REMOTE, lang="es", files=None):
    repo, sha = make_git_repo(files or {"src/a.py": SRC}, remote=remote)
    out = make_dir() / "run"
    result = run_cli(["init", "--system", "demo", "--out", str(out), "--repo", f"BACK={repo}", "--lang", lang])
    assert result.returncode == 0, result.stderr
    return out, repo, sha


def base(report="correctness", **extra):
    f = {"report": report, "category": "bug", "dimension": "bug", "title": "A title", "verdict": "confirmed",
         "severity": "high", "confidence": "docs", "source": "pass-a", "what_happens": "It breaks.",
         "evidence": [{"cite": "BACK/src/a.py", "from": 5, "to": 6, "note": "here"}]}
    if report == "quality":
        f.update({"suggestion": "Do better.", "effort": "S", "source": "pass-q"})
    f.update(extra)
    return f


def filtered(run):
    filtermod.run_filter(run)
    return run


def first_rule(css: str) -> str:
    return css[:css.index("}") + 1]


class SelfContainedTest(unittest.TestCase):
    def test_output_is_self_contained(self):
        run, _, _ = new_run()
        findingsmod.add(run, base())
        out = rendermod.render_report(filtered(run), "correctness")
        self.assertEqual(out, run / "demo-correctness.html")
        html = out.read_text(encoding="utf-8")
        self.assertNotIn('<link rel="stylesheet"', html)
        self.assertNotIn("<script src=", html)
        css = (SKILL / "assets" / "theme.css").read_text(encoding="utf-8")
        self.assertIn(first_rule(css), html)
        self.assertEqual(html.count("<style>"), 1)
        urls = re.findall(r'(?:href|src)="(https?://[^"]+)"', html)
        self.assertTrue(urls)
        for url in urls:
            self.assertTrue(url.startswith(f"{REMOTE}/blob/"), url)

    def test_custom_theme_replaces_default(self):
        run, _, _ = new_run()
        findingsmod.add(run, base())
        filtered(run)
        theme = make_dir() / "t.css"
        theme.write_text("body{color:#123456}", encoding="utf-8")
        result = run_cli(["render", "--run", str(run), "--report", "correctness", "--theme", str(theme)])
        self.assertEqual(result.returncode, 0, result.stderr)
        html = (run / "demo-correctness.html").read_text(encoding="utf-8")
        self.assertIn("body{color:#123456}", html)
        default = (SKILL / "assets" / "theme.css").read_text(encoding="utf-8")
        self.assertNotIn(first_rule(default), html)

    def test_missing_theme_is_usage_error(self):
        run, _, _ = new_run()
        findingsmod.add(run, base())
        filtered(run)
        result = run_cli(["render", "--run", str(run), "--theme", str(make_dir() / "nope.css")])
        self.assertEqual(result.returncode, 2, result.stderr)


class ContentTest(unittest.TestCase):
    def test_only_shown_findings_rendered_and_counts_displayed(self):
        run, _, _ = new_run()
        findingsmod.add(run, base("quality", title="Shown one"))
        findingsmod.add(run, base("quality", title="Shown two"))
        findingsmod.add(run, base("quality", title="Refuted one", contrast={"model": "m", "verdict": "refute"}))
        html = rendermod.render_report(filtered(run), "quality").read_text(encoding="utf-8")
        self.assertIn("se muestran 2 de 3", html)
        self.assertIn("Shown one", html)
        self.assertIn("Shown two", html)
        self.assertNotIn("Refuted one", html)

    def test_english_and_unknown_lang_fall_back_to_english(self):
        run, _, _ = new_run(lang="xx")
        findingsmod.add(run, base())
        html = rendermod.render_report(filtered(run), "correctness").read_text(encoding="utf-8")
        self.assertIn("showing 1 of 1", html)
        self.assertIn("How it was done", html)

    def test_audience_prose_preferred(self):
        run, _, _ = new_run()
        findingsmod.add(run, base(title="Base title", audience={"title": "Plain title", "what_happens": "Plain words"}))
        html = rendermod.render_report(filtered(run), "correctness").read_text(encoding="utf-8")
        self.assertIn("Plain title", html)
        self.assertIn("Plain words", html)
        self.assertNotIn("Base title", html)

    def test_html_escaped(self):
        run, _, _ = new_run()
        findingsmod.add(run, base(title="<script>x</script>", what_happens="a & b"))
        html = rendermod.render_report(filtered(run), "correctness").read_text(encoding="utf-8")
        self.assertNotIn("<script>x</script>", html)
        self.assertIn("&lt;script&gt;x&lt;/script&gt;", html)
        self.assertIn("a &amp; b", html)

    def test_sections_follow_manifest_order(self):
        run, _, _ = new_run()
        manifest = runmod.load(run)
        manifest["sections"]["correctness"] = ["race", "bug"]
        runmod.save(run, manifest)
        for cat in ("zeta", "bug", "alpha", "race"):
            findingsmod.add(run, base(category=cat, title=f"in {cat}"))
        html = rendermod.render_report(filtered(run), "correctness").read_text(encoding="utf-8")
        found = re.findall(r'data-category="([^"]+)"', html)
        self.assertEqual(found, ["race", "bug", "alpha", "zeta"])

    def test_start_here_only_in_quality(self):
        run, _, _ = new_run()
        findingsmod.add(run, base())
        findingsmod.add(run, base("quality", title="Start with me"))
        filtered(run)
        quality = rendermod.render_report(run, "quality").read_text(encoding="utf-8")
        correctness = rendermod.render_report(run, "correctness").read_text(encoding="utf-8")
        self.assertIn('id="start-here"', quality)
        self.assertIn("Por dónde empezar", quality)
        self.assertNotIn('id="start-here"', correctness)

    def test_quality_card_shows_effort_and_measurement(self):
        run, _, _ = new_run()
        findingsmod.add(run, base("quality", effort="L", measurement={"tool": "radon", "value": "CC 41"}))
        html = rendermod.render_report(filtered(run), "quality").read_text(encoding="utf-8")
        self.assertIn("radon", html)
        self.assertIn("CC 41", html)
        self.assertIn("Do better.", html)

    def test_quality_measurement_is_masked_even_when_stored_raw(self):
        import json as _json
        run, _, _ = new_run()
        fid = findingsmod.add(run, base("quality", measurement={"tool": "rg", "value": "x"}))
        filtered(run)  # the filter rewrites findings (masked); tamper after it, like a legacy run on disk
        path = run / "findings" / f"{fid}.json"
        data = _json.loads(path.read_text(encoding="utf-8"))
        key = "AKIA" + "ABCDEFGHIJKLMNOP"
        data["measurement"] = {"tool": f"rg {key}", "value": f"key {key} found"}
        path.write_text(_json.dumps(data), encoding="utf-8")
        html = rendermod.render_report(run, "quality").read_text(encoding="utf-8")
        self.assertIn("AKIA****", html)
        self.assertNotIn(key, html)


class GitTest(unittest.TestCase):
    def test_snippet_comes_from_pinned_sha_not_worktree(self):
        run, repo, sha = new_run()
        (repo / "src" / "a.py").write_text(SRC.replace("line 5\n", "CHANGED 5\n"), encoding="utf-8")
        git(repo, "-c", "commit.gpgsign=false", "commit", "-qam", "later")
        repo_entry = runmod.load(run)["repos"][0]
        text = rendermod.snippet(repo_entry, "src/a.py", 5, 6)
        self.assertIn("line 5", text)
        self.assertNotIn("CHANGED", text)
        self.assertIn("line 2", text)
        self.assertNotIn("line 1<", text)
        self.assertIn("line 9", text)
        self.assertNotIn("line 10", text)
        findingsmod.add(run, base())
        html = rendermod.render_report(filtered(run), "correctness").read_text(encoding="utf-8")
        self.assertIn("line 5", html)
        self.assertNotIn("CHANGED", html)

    def test_snippet_clamps_at_file_edges(self):
        run, _, _ = new_run()
        repo_entry = runmod.load(run)["repos"][0]
        text = rendermod.snippet(repo_entry, "src/a.py", 1, 1)
        self.assertIn("line 1", text)
        text = rendermod.snippet(repo_entry, "src/a.py", 20, 20)
        self.assertIn("line 20", text)

    def test_legacy_sha_fix_is_ignored_and_the_proposal_is_shown(self):
        run, repo, _ = new_run()
        (repo / "tests").mkdir()
        (repo / "tests" / "test_a.py").write_text("assert False\n", encoding="utf-8")
        git(repo, "add", "-A")
        git(repo, "-c", "commit.gpgsign=false", "commit", "-qm", "test")
        sha_test = git(repo, "rev-parse", "HEAD")
        (repo / "src" / "a.py").write_text(SRC.replace("line 5\n", "fixed 5\n"), encoding="utf-8")
        git(repo, "-c", "commit.gpgsign=false", "commit", "-qam", "fix")
        sha_fix = git(repo, "rev-parse", "HEAD")
        findingsmod.add(run, base(title="Legacy", sha_test=sha_test, sha_fix=sha_fix, prod_files=["src/a.py"],
                                  fix_summary="Guard it.", confidence="execution", branch="fix/a",
                                  tests=[{"path": "tests/test_a.py", "red": "1 of 1 fails", "green": ""}],
                                  red_reason="The test calls it twice."))
        html = rendermod.render_report(filtered(run), "correctness").read_text(encoding="utf-8")
        self.assertNotIn('class="code diff"', html)
        self.assertNotIn("fixed 5", html)
        self.assertNotIn("git diff", html)
        self.assertIn("Guard it.", html)
        self.assertIn("1 of 1 fails", html)

    def test_links_pinned_when_remote_plain_text_when_not(self):
        run, _, sha = new_run()
        findingsmod.add(run, base())
        html = rendermod.render_report(filtered(run), "correctness").read_text(encoding="utf-8")
        self.assertIn(f'href="{REMOTE}/blob/{sha}/src/a.py#L5-L6"', html)
        run2, _, _ = new_run(remote=None)
        findingsmod.add(run2, base())
        html2 = rendermod.render_report(filtered(run2), "correctness").read_text(encoding="utf-8")
        self.assertIn("BACK/src/a.py:5-6", html2)
        self.assertNotIn("/blob/", html2)
        self.assertIsNone(re.search(r'href="https?://', html2))


    def test_snippet_past_eof_or_inverted_shows_warning(self):
        run, _, _ = new_run()
        repo_entry = runmod.load(run)["repos"][0]
        self.assertEqual(rendermod.snippet(repo_entry, "src/a.py", 30, 31), "")
        self.assertEqual(rendermod.snippet(repo_entry, "src/a.py", 6, 5), "")

    def test_local_path_remote_renders_plain_text(self):
        run, _, _ = new_run()
        manifest = runmod.load(run)
        manifest["repos"][0]["remote"] = "/srv/git/r"
        runmod.save(run, manifest)
        findingsmod.add(run, base())
        html = rendermod.render_report(filtered(run), "correctness").read_text(encoding="utf-8")
        self.assertIn("BACK/src/a.py:5-6", html)
        self.assertNotIn("/blob/", html)


class AnchorAndCountTest(unittest.TestCase):
    def test_category_anchors_are_unique(self):
        run, _, _ = new_run()
        findingsmod.add(run, base(category="a b"))
        findingsmod.add(run, base(category="a-b"))
        findingsmod.add(run, base(category="a_b"))
        html = rendermod.render_report(filtered(run), "correctness").read_text(encoding="utf-8")
        ids = re.findall(r'<section id="(cat-[^"]+)"', html)
        self.assertEqual(sorted(ids), ["cat-a-b", "cat-a-b-2", "cat-a-b-3"])

    def test_how_it_was_done_counts_merged_duplicates(self):
        for lang, phrase in (("es", "duplicados fusionados con otro hallazgo: 1"),
                             ("en", "duplicates merged into another finding: 1")):
            run, _, _ = new_run(lang=lang)
            findingsmod.add(run, base())
            findingsmod.add(run, base(exclude="duplicate", duplicate_of="C-01"))
            html = rendermod.render_report(filtered(run), "correctness").read_text(encoding="utf-8")
            self.assertIn(phrase, html)
            self.assertNotIn('id="f-c-02"', html)

    def test_missing_counts_omit_shown_line(self):
        run, _, _ = new_run()
        findingsmod.add(run, base())
        filtered(run)
        manifest = runmod.load(run)
        manifest["filter"]["counts"] = {}
        runmod.save(run, manifest)
        html = rendermod.render_report(run, "correctness").read_text(encoding="utf-8")
        self.assertNotIn("se muestran", html)


class HowTest(unittest.TestCase):
    def test_how_it_was_done_names_contrast_model_and_family(self):
        run, _, sha = new_run()
        findingsmod.add(run, base("quality", source="quality-lenses",
                                  contrast={"model": "other-model-1", "same_family": False, "verdict": "agree"}))
        findingsmod.add(run, base("quality", source="semgrep",
                                  contrast={"model": "same-model-2", "same_family": True, "verdict": "agree"}))
        html = rendermod.render_report(filtered(run), "quality").read_text(encoding="utf-8")
        how = html[html.index('id="how"'):]
        self.assertIn("Cómo se hizo", html)
        self.assertIn("other-model-1", how)
        self.assertIn("same-model-2", how)
        self.assertIn("misma familia: no", how)
        self.assertIn("misma familia: sí", how)
        self.assertNotIn("quality-lenses", how)
        self.assertIn(f'title="{sha}"', how)
        self.assertIn(sha[:7], how)
        self.assertIn("se muestran 2 de 2", how)


class LocalizedHowTest(unittest.TestCase):
    def how(self, lang, **manifest_extra):
        run, _, _ = new_run(lang=lang)
        if manifest_extra:
            m = runmod.load(run)
            m.update(manifest_extra)
            runmod.save(run, m)
        findingsmod.add(run, base("quality", source="quality-lenses",
                                  contrast={"model": "gpt-x", "same_family": False, "verdict": "agree"}))
        findingsmod.add(run, base("quality", title="Hidden one", source="semgrep",
                                  contrast={"model": "gpt-x", "same_family": True, "verdict": "refute"}))
        findingsmod.add(run, base("correctness", source="races-distributed"))
        html = rendermod.render_report(filtered(run), "quality").read_text(encoding="utf-8")
        return html, html[html.index('id="how"'):]

    def test_no_pass_names_anywhere_in_the_report(self):
        html, how = self.how("es")
        for name in ("quality-lenses", "races-distributed", "correctness-general", "red-test-proof"):
            self.assertNotIn(name, html)
        self.assertIn("semgrep", how)

    def test_every_step_has_a_label_in_both_languages(self):
        for lang in ("es", "en"):
            for step in runmod.STEPS:
                self.assertTrue(rendermod.step_label(step, lang), (lang, step))
        self.assertEqual(rendermod.step_label("contrast", "es"), "contraste")
        self.assertEqual(rendermod.step_label("contrast", "en"), "contrast")

    def test_spanish_report_has_no_english_verdicts_and_no_hidden_ids(self):
        html, how = self.how("es")
        self.assertIn("coincide", how)
        self.assertNotRegex(how, r"<td>(agree|refute|unsure)</td>")
        self.assertNotIn("Q-02", how)
        self.assertNotIn("no se muestra", how)
        self.assertNotIn("Hidden one", html)

    def test_english_labels_and_verdicts(self):
        _, how = self.how("en")
        self.assertIn("<td>agrees</td>", how)
        self.assertNotIn("Q-02", how)

    def test_contrast_table_lists_only_shown_findings(self):
        _, how = self.how("es")
        self.assertIn("Q-01", how)
        self.assertEqual(how.count("<code>gpt-x</code>"), 1)

    def test_author_model_stated(self):
        _, how = self.how("es", author_model="claude-opus-4")
        self.assertIn("claude-opus-4", how)
        self.assertIn("Modelo autor", how)
        _, how_en = self.how("en", author_model="claude-opus-4")
        self.assertIn("Author model", how_en)

    def test_test_counts_rendered_as_given(self):
        run, _, _ = new_run()
        findingsmod.add(run, base(tests=[{"path": "t.py", "red": "3 casos fallan", "green": "3 casos pasan",
                                          "note": ""}]))
        html = rendermod.render_report(filtered(run), "correctness").read_text(encoding="utf-8")
        self.assertIn("<td>3 casos fallan</td><td>3 casos pasan</td>", html)


class WaiverTest(unittest.TestCase):
    def render(self, lang):
        run, _, _ = new_run(lang=lang)
        findingsmod.add(run, base())
        m = runmod.load(run)
        m["coverage_waivers"] = [{"step": "correctness", "reason": "out of scope",
                                  "open": ["BACK/src/lib / races-distributed", "BACK/src/x / security"]}]
        runmod.save(run, m)
        return rendermod.render_report(filtered(run), "correctness").read_text(encoding="utf-8")

    def test_waiver_shows_module_and_localized_pass_never_the_name(self):
        html = self.render("es")
        self.assertNotIn("races-distributed", html)
        self.assertIn("BACK/src/lib", html)
        self.assertIn("revisión de carreras y sistemas distribuidos", html)
        self.assertIn("revisión de seguridad", html)
        en = self.render("en")
        self.assertNotIn("races-distributed", en)
        self.assertIn("races and distributed-systems review", en)


class RebuttalTest(unittest.TestCase):
    def test_rebutted_refute_shows_card_with_localized_rebuttal_line(self):
        run, _, _ = new_run()
        findingsmod.add(run, base("quality", title="Kept finding", contrast={
            "model": "m", "verdict": "refute", "scope": "finding", "rebutted": True,
            "note": "El guard no cubre la ruta BACK/src/a.py:5"}))
        html = rendermod.render_report(filtered(run), "quality").read_text(encoding="utf-8")
        self.assertIn("Kept finding", html)
        self.assertIn("Refutación respondida", html)
        self.assertIn("El guard no cubre la ruta", html)

    def test_scope_severity_refute_shown_without_rebuttal_line(self):
        run, _, _ = new_run()
        findingsmod.add(run, base(title="Lowered", contrast={"model": "m", "verdict": "refute", "scope": "severity",
                                                              "note": "demasiado alta"}))
        html = rendermod.render_report(filtered(run), "correctness").read_text(encoding="utf-8")
        self.assertIn("Lowered", html)
        self.assertNotIn("Refutación respondida", html)

    def test_english_rebuttal_line(self):
        run, _, _ = new_run(lang="en")
        findingsmod.add(run, base(contrast={"model": "m", "verdict": "refute", "scope": "finding",
                                            "rebutted": True, "note": "Still reachable."}))
        html = rendermod.render_report(filtered(run), "correctness").read_text(encoding="utf-8")
        self.assertIn("Rebuttal to the contrast", html)
        self.assertIn("Still reachable.", html)

    def test_rebuttal_field_shown_next_to_the_contrast_note(self):
        for lang, objection, answer in (("es", "Objeción del contraste", "Refutación respondida"),
                                        ("en", "Contrast objection", "Rebuttal to the contrast")):
            run, _, _ = new_run(lang=lang)
            findingsmod.add(run, base(contrast={"model": "m", "verdict": "refute", "scope": "finding",
                                                "rebutted": True, "note": "The guard covers it.",
                                                "rebuttal": "The guard skips BACK/src/a.py:5."}))
            html = rendermod.render_report(filtered(run), "correctness").read_text(encoding="utf-8")
            self.assertIn(objection, html)
            self.assertIn("The guard covers it.", html)
            self.assertIn(answer, html)
            self.assertIn("The guard skips BACK/src/a.py:5.", html)

    def test_contrast_table_localizes_severity_refute_and_rebutted(self):
        for lang, sev, reb in (("es", "refuta la severidad", "refutación respondida"),
                               ("en", "refutes severity", "rebutted")):
            run, _, _ = new_run(lang=lang)
            findingsmod.add(run, base(title="Lowered", contrast={"model": "m", "verdict": "refute",
                                                                  "scope": "severity", "note": "too high"}))
            findingsmod.add(run, base(title="Kept", contrast={"model": "m", "verdict": "refute", "scope": "finding",
                                                               "rebutted": True, "rebuttal": "holds"}))
            html = rendermod.render_report(filtered(run), "correctness").read_text(encoding="utf-8")
            how = html[html.index('id="how"'):]
            self.assertIn(f"<td>{sev}</td>", how)
            self.assertIn(f"<td>{reb}</td>", how)


AWS_KEY = "AKIA" + "ABCDEFGHIJKLMNOP"


class SecretMaskTest(unittest.TestCase):
    def test_secret_in_cited_line_is_masked_in_html(self):
        src = SRC.replace("line 5\n", f"    key = '{AWS_KEY}'\n")
        run, _, _ = new_run(files={"src/a.py": src})
        findingsmod.add(run, base())
        html = rendermod.render_report(filtered(run), "correctness").read_text(encoding="utf-8")
        self.assertNotIn(AWS_KEY, html)
        self.assertIn("AKIA****", html)
        self.assertIn("    key = ", html)

    def test_secret_named_default_in_context_lines_is_masked_and_hygiene_is_clean(self):
        default = "s3cr3tDefault9"
        yml = "".join(f"k{n}: v\n" for n in range(1, 21)).replace(
            "k3: v\n", "    value: ${SECURITY_API_TOKEN_MASTER_VALUE:" + default + "}\n").replace(
            "k4: v\n", "    password: " + default + "\n")
        run, _, _ = new_run(files={"src/a.py": SRC, "src/application.yml": yml})
        findingsmod.add(run, base(evidence=[{"cite": "BACK/src/application.yml", "from": 6, "to": 7, "note": "n"}]))
        filtered(run)
        for report in ("correctness", "quality"):
            rendermod.render_report(run, report)
        html = "".join(p.read_text(encoding="utf-8") for p in run.glob("*.html"))
        self.assertNotIn(default, html)
        self.assertIn("${SECURITY_API_TOKEN_MASTER_VALUE:****}", html)
        self.assertIn("<pre data-config>", html)
        self.assertEqual(hygienemod.check_reports(run), [])

    def test_secret_named_value_in_prose_is_masked_by_render_for_any_dimension(self):
        run, _, _ = new_run()
        findingsmod.add(run, base())
        path = run / "findings" / "C-01.json"
        filtered(run)
        path.write_text(path.read_text(encoding="utf-8").replace(
            '"It breaks."', '"Sends {\\"api_key\\": \\"opaque1\\"}."'), encoding="utf-8")
        rendermod.render_report(run, "correctness")
        html = "".join(p.read_text(encoding="utf-8") for p in run.glob("*.html"))
        self.assertNotIn("opaque1", html)
        self.assertEqual(hygienemod.check_reports(run), [])

    def test_code_snippet_keeps_bare_assignments(self):
        src = SRC.replace("line 5\n", "    token = token_service.find(user)\n")
        run, _, _ = new_run(files={"src/a.py": src})
        text = rendermod.snippet(runmod.load(run)["repos"][0], "src/a.py", 5, 5)
        self.assertIn("token = token_service.find(user)", text)
        self.assertTrue(text.startswith("<pre>"))

    def test_findings_added_after_filter_warn_on_stderr(self):
        run, _, _ = new_run()
        findingsmod.add(run, base())
        filtered(run)
        late = findingsmod.add(run, base(title="Late"))
        result = run_cli(["render", "--run", str(run)])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(late, result.stderr)
        self.assertIn("ia.py filter", result.stderr)

    def test_footer_shows_render_date(self):
        run, _, _ = new_run()
        findingsmod.add(run, base())
        filtered(run)
        manifest = runmod.load(run)
        manifest["created"] = "2001-01-01"
        runmod.save(run, manifest)
        html = rendermod.render_report(run, "correctness").read_text(encoding="utf-8")
        footer = re.search(r'<span class="ver">.*?</span>', html, flags=re.S).group(0)
        self.assertIn(date.today().isoformat(), footer)
        self.assertNotIn("2001-01-01", footer)


PEM_BODY = ["MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7VJTUt9Us8cKj",
            "MBc3q2Jd8Fz1Qm0XyZpL4kWnHsRtUvAaBbCcDdEeFfGgHhIiJjKkLlMmNnOoPpQq"]


def pem(body=PEM_BODY):
    return ["-----BEGIN PRIVATE KEY-----", *body, "-----END PRIVATE KEY-----"]


class PrivateKeyMaskTest(unittest.TestCase):
    def leaked(self, html):
        return [b for b in PEM_BODY if b in html or b[:20] in html]

    def test_pem_body_in_cited_window_is_masked(self):
        src = "".join(l + "\n" for l in ["a", "b", *pem(), "c", "d", "e"])
        run, _, _ = new_run(files={"src/k.py": src})
        findingsmod.add(run, base(evidence=[{"cite": "BACK/src/k.py", "from": 3, "to": 6, "note": ""}]))
        html = rendermod.render_report(filtered(run), "correctness").read_text(encoding="utf-8")
        self.assertEqual(self.leaked(html), [])

    def test_window_starting_mid_key_is_masked(self):
        body = PEM_BODY + [b[::-1] for b in PEM_BODY]
        src = "".join(l + "\n" for l in pem(body))
        run, _, _ = new_run(files={"src/k.py": src})
        findingsmod.add(run, base(evidence=[{"cite": "BACK/src/k.py", "from": 5, "to": 5, "note": ""}]))
        html = rendermod.render_report(filtered(run), "correctness").read_text(encoding="utf-8")
        self.assertEqual(self.leaked(html), [])
        self.assertNotIn(body[3], html)
        self.assertNotIn(body[3][::-1], html)

    def test_rebuttal_and_test_notes_are_masked(self):
        run, _, _ = new_run()
        findingsmod.add(run, base(dimension="security", contrast={"model": "m", "same_family": False, "verdict": "refute",
                                  "rebutted": True, "note": f"see {AWS_KEY}"},
                                  tests=[{"path": "t.py", "red": "1", "green": "0", "note": f"n {AWS_KEY}"}],
                                  red_reason="r", branch="b", sha_test="a" * 40, confidence="docs"))
        html = rendermod.render_report(filtered(run), "correctness").read_text(encoding="utf-8")
        self.assertNotIn(AWS_KEY, html)

    def test_single_line_key_in_cited_line_is_masked(self):
        line = '{"private_key": "-----BEGIN PRIVATE KEY-----\\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcw\\n-----END PRIVATE KEY-----\\n"}'
        src = SRC.replace("line 5\n", line + "\n")
        run, _, _ = new_run(files={"src/a.py": src})
        findingsmod.add(run, base())
        html = rendermod.render_report(filtered(run), "correctness").read_text(encoding="utf-8")
        self.assertNotIn("MIIEvQIBADANBg", html)

    def test_title_secret_is_masked_for_any_dimension(self):
        run, _, _ = new_run()
        findingsmod.add(run, base(title=f"Leaks {AWS_KEY}"))
        html = rendermod.render_report(filtered(run), "correctness").read_text(encoding="utf-8")
        self.assertNotIn(AWS_KEY, html)

    def test_credentialed_remote_is_masked_in_report(self):
        run, _, _ = new_run(remote="https://user:tok123@github.com/o/r.git")
        findingsmod.add(run, base())
        html = rendermod.render_report(filtered(run), "correctness").read_text(encoding="utf-8")
        self.assertNotIn("tok123", html)


class SecurityProseMaskTest(unittest.TestCase):
    def test_security_finding_prose_is_masked(self):
        run, _, _ = new_run()
        findingsmod.add(run, base(dimension="security", what_happens=f"Leaks {AWS_KEY} to logs.",
                                  red_reason=f"Test reads {AWS_KEY}.",
                                  audience={"title": "", "what_happens": f"Aud {AWS_KEY}", "fix_summary": ""},
                                  evidence=[{"cite": "BACK/src/a.py", "from": 5, "to": 6, "note": f"key {AWS_KEY}"}]))
        html = rendermod.render_report(filtered(run), "correctness").read_text(encoding="utf-8")
        self.assertNotIn(AWS_KEY, html)
        self.assertIn("AKIA****", html)

    def test_security_prose_pem_block_is_masked(self):
        note = "\n".join(pem())
        run, _, _ = new_run()
        findingsmod.add(run, base(dimension="supply-chain", what_happens=note))
        html = rendermod.render_report(filtered(run), "correctness").read_text(encoding="utf-8")
        for b in PEM_BODY:
            self.assertNotIn(b, html)


class CliTest(unittest.TestCase):
    def test_render_both_marks_step_done(self):
        run, _, _ = new_run()
        findingsmod.add(run, base())
        findingsmod.add(run, base("quality"))
        filtered(run)
        result = run_cli(["render", "--run", str(run)])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((run / "demo-correctness.html").is_file())
        self.assertTrue((run / "demo-quality.html").is_file())
        self.assertIn("demo-quality.html", result.stdout)
        self.assertEqual(runmod.load(run)["steps"]["render"], "done")

    def test_render_without_filter_exits_1(self):
        run, _, _ = new_run()
        findingsmod.add(run, base())
        result = run_cli(["render", "--run", str(run)])
        self.assertEqual(result.returncode, 1)
        self.assertIn("ia.py filter", result.stderr)
        self.assertFalse((run / "demo-correctness.html").exists())
        self.assertNotIn("added after the filter", result.stderr)
        self.assertEqual(runmod.load(run)["steps"]["render"], "pending")

    def test_render_requires_run(self):
        self.assertEqual(run_cli(["render"]).returncode, 2)


if __name__ == "__main__":
    unittest.main()


class HistoryCiteRenderTest(unittest.TestCase):
    def history_run(self, **extra):
        run, repo, first = new_run(files={"src/a.py": SRC, "src/.env": "KEY=hunter2hunter2\n"})
        git(repo, "rm", "-q", "src/.env")
        git(repo, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "drop env")
        # the run was initialised before the removal commit; re-init at the new HEAD
        out = make_dir() / "run"
        self.assertEqual(run_cli(["init", "--system", "demo", "--out", str(out), "--repo", f"BACK={repo}",
                                  "--lang", "es"]).returncode, 0)
        return out, first

    def html_for(self, dimension, cite_path, commit):
        run, _ = self.history_run()
        findingsmod.add(run, base(dimension=dimension, evidence=[{"cite": f"BACK/{cite_path}@{commit[:7]}", "from": 1,
                                                                  "to": 1, "note": "old key"}]))
        return rendermod.render_report(filtered(run), "correctness").read_text(encoding="utf-8")

    def test_security_history_cite_shows_path_and_commit_and_no_snippet(self):
        run, first = self.history_run()
        findingsmod.add(run, base(dimension="security", evidence=[{"cite": f"BACK/src/.env@{first[:7]}", "from": 1,
                                                                   "to": 1, "note": "old key"}]))
        html = rendermod.render_report(filtered(run), "correctness").read_text(encoding="utf-8")
        self.assertIn("src/.env", html)
        self.assertIn(f"en el historial (commit {first[:7]})", html)
        self.assertNotIn("hunter2", html)
        self.assertNotIn("KEY=", html)

    def test_supply_chain_history_cite_has_no_snippet_either(self):
        run, first = self.history_run()
        findingsmod.add(run, base(dimension="supply-chain", evidence=[{"cite": f"BACK/src/.env@{first[:7]}", "from": 1,
                                                                       "to": 1, "note": ""}]))
        html = rendermod.render_report(filtered(run), "correctness").read_text(encoding="utf-8")
        self.assertIn("en el historial", html)
        self.assertNotIn("KEY=", html)

    def test_other_dimension_history_cite_shows_masked_snippet_at_that_commit(self):
        run, first = self.history_run()
        findingsmod.add(run, base(dimension="bug", evidence=[{"cite": f"BACK/src/a.py@{first[:7]}", "from": 2,
                                                              "to": 2, "note": ""}]))
        html = rendermod.render_report(filtered(run), "correctness").read_text(encoding="utf-8")
        self.assertIn(f"en el historial (commit {first[:7]})", html)
        self.assertIn("line 2", html)
        self.assertIn(f"/blob/{first}/src/a.py", html)

    def test_english_label(self):
        run, repo, sha = new_run(lang="en")
        findingsmod.add(run, base(evidence=[{"cite": f"BACK/src/a.py@{sha[:7]}", "from": 2, "to": 2, "note": ""}]))
        html = rendermod.render_report(filtered(run), "correctness").read_text(encoding="utf-8")
        self.assertIn(f"in history (commit {sha[:7]})", html)
