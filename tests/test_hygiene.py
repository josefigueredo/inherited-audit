from __future__ import annotations

import unittest

from helpers import git, make_dir, make_git_repo, run_cli, write_tree

from ia import findings as findingsmod
from ia import hygiene
from ia import run as runmod
from test_branches import add_finding, commit_on, new_run

TOKEN40 = "AbCdEfGhIj" * 4  # 40 mixed-case alphanumerics: looks like a TruffleHog-style identifier
SHA40 = "0123456789abcdef" * 2 + "01234567"
AWS = "AKIAABCDEFGHIJKLMNOP"
GHP = "ghp_" + "a1B2c3D4e5" * 3 + "a1B2c3"


def _repo_with(files):
    repo, sha = make_git_repo({"a.py": "one\n"})
    commit_on(repo, "fix/x", files)
    return repo, sha


class CheckBranchTest(unittest.TestCase):
    def check(self, files):
        repo, sha = _repo_with(files)
        return hygiene.check_branch(repo, sha, "fix/x")

    def test_clean_branch(self):
        self.assertEqual(self.check({"a.py": "two\n"}), [])

    def test_mixed_40_char_token_flagged_and_masked(self):
        out = self.check({"t.py": f"ids = '{TOKEN40}'\n"})
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0].startswith("fix/x: 40-char identifier (TruffleHog false positive risk): "), out)
        self.assertNotIn(TOKEN40, out[0])
        self.assertIn("AbCd****", out[0])

    def test_hex_sha_in_lockfile_not_flagged(self):
        self.assertEqual(self.check({"lock.txt": f"resolved sha1-{SHA40}\nsha {SHA40}\n"}), [])

    def test_39_and_41_char_tokens_not_flagged(self):
        self.assertEqual(self.check({"t.py": f"{TOKEN40[:39]} {TOKEN40}x\n"}), [])

    def test_only_added_lines_count(self):
        repo, sha = make_git_repo({"a.py": f"old = '{TOKEN40}'\n"})
        commit_on(repo, "fix/x", {"a.py": f"old = '{TOKEN40}'\nnew = 1\n"})
        self.assertEqual(hygiene.check_branch(repo, sha, "fix/x"), [])

    def test_local_tooling_files_flagged(self):
        out = self.check({".serena/memories/m.md": "x\n", ".idea/w.xml": "x\n", "sub/.DS_Store": "x\n",
                          "a.py.swp": "x\n", ".vscode/s.json": "{}\n", ".cursor/r": "x\n", ".claude/s.json": "{}\n"})
        self.assertEqual(len(out), 7, out)
        self.assertTrue(all(": local tooling file: " in line for line in out), out)

    def test_normal_dotfiles_not_flagged(self):
        self.assertEqual(self.check({".gitignore": "x\n", ".github/w.yml": "x: 1\n", "src/idea.py": "x\n"}), [])

    def test_secret_patterns_flagged_and_masked(self):
        for secret in (AWS, "-----BEGIN RSA PRIVATE KEY-----", GHP, "xoxb-123456789012-abcdefghijkl"):
            with self.subTest(secret=secret):
                repo, sha = make_git_repo({"a.py": "one\n"})
                commit_on(repo, "fix/x", {"s.txt": f"key = {secret}\n"})
                out = hygiene.check_branch(repo, sha, "fix/x")
                self.assertEqual(len(out), 1, out)
                self.assertIn(": possible secret: ", out[0])
                self.assertNotIn(secret, out[0])
                # a private-key line is never excerpted at all
                self.assertIn("private key block" if "PRIVATE KEY" in secret else secret[:4] + "****", out[0])

    def test_excerpt_is_at_most_80_chars(self):
        out = self.check({"s.txt": "x" * 200 + f" {AWS} " + "y" * 200 + "\n"})
        excerpt = out[0].split(": possible secret: ", 1)[1]
        self.assertLessEqual(len(excerpt), 80)
        self.assertIn("AKIA****", excerpt)

    def test_pinned_action_is_info_not_problem(self):
        repo, sha = _repo_with({".github/workflows/ci.yml": f"      - uses: actions/checkout@{SHA40} # v4\n"})
        problems, info = hygiene.scan_branch(repo, sha, "fix/x")
        self.assertEqual(problems, [])
        self.assertEqual(len(info), 1)
        self.assertIn("actions/checkout", info[0])
        self.assertEqual(hygiene.check_branch(repo, sha, "fix/x"), [])

    def test_snake_case_40_char_id_flagged(self):
        ident = "test_" + "handles_the_empty_cart_case_ok_yes_please_now"[:35]
        self.assertEqual(len(ident), 40)
        out = self.check({"t.py": f"def {ident}():\n    pass\n"})
        self.assertEqual(len(out), 1, out)
        self.assertIn(": 40-char identifier", out[0])

    def test_line_with_secret_and_token_masks_both_everywhere(self):
        out = self.check({"s.txt": f"{AWS} {TOKEN40}\n"})
        self.assertEqual(len(out), 2, out)
        for line in out:
            self.assertNotIn(AWS, line)
            self.assertNotIn(TOKEN40, line)

    def test_added_line_starting_with_plusplus_is_scanned(self):
        repo, sha = make_git_repo({"a.py": "one\n"})
        commit_on(repo, "fix/x", {"s.txt": f"++{AWS}\n"})
        out = hygiene.check_branch(repo, sha, "fix/x")
        self.assertEqual(len(out), 1, out)
        self.assertIn(": possible secret: ", out[0])

    def test_missing_branch_flagged(self):
        repo, sha = make_git_repo({"a.py": "one\n"})
        out = hygiene.check_branch(repo, sha, "fix/nope")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0], "fix/nope: branch not found: not in the repo")


class CheckOutputsTest(unittest.TestCase):
    def test_secret_in_saved_output_flagged(self):
        run = make_dir()
        write_tree(run, {"outputs/BACK-baseline.txt": f"ok\nTOKEN={AWS}\n", "outputs/clean.txt": "fine\n"})
        out = hygiene.check_outputs(run)
        self.assertEqual(len(out), 1, out)
        self.assertTrue(out[0].startswith("outputs/BACK-baseline.txt: possible secret: "), out)
        self.assertNotIn(AWS, out[0])

    def test_secret_and_token_on_one_line_masked_in_outputs(self):
        run = make_dir()
        write_tree(run, {"outputs/o.txt": f"{AWS} {TOKEN40} {GHP}\n"})
        out = hygiene.check_outputs(run)
        self.assertTrue(out)
        for line in out:
            for raw in (AWS, TOKEN40, GHP):
                self.assertNotIn(raw, line)

    def test_clean_or_missing_outputs(self):
        run = make_dir()
        self.assertEqual(hygiene.check_outputs(run), [])
        write_tree(run, {"outputs/a.txt": f"{TOKEN40}\n"})  # the 40-char rule is for branches only
        self.assertEqual(hygiene.check_outputs(run), [])


class CheckRunDirTest(unittest.TestCase):
    def manifest(self, repo):
        return {"repos": [{"alias": "BACK", "path": str(repo), "subdir": "", "sha": "x", "remote": ""}]}

    def test_run_dir_inside_repo_unignored_flagged(self):
        repo, _ = make_git_repo({"a.py": "one\n"})
        run = repo / "audit"
        run.mkdir()
        out = hygiene.check_run_dir(run, self.manifest(repo))
        self.assertEqual(len(out), 1, out)
        self.assertIn("not ignored by git", out[0])

    def test_run_dir_inside_repo_ignored_ok(self):
        repo, _ = make_git_repo({".gitignore": "audit/\n"})
        run = repo / "audit"
        run.mkdir()
        self.assertEqual(hygiene.check_run_dir(run, self.manifest(repo)), [])

    def test_run_dir_outside_repo_ok(self):
        repo, _ = make_git_repo({"a.py": "one\n"})
        self.assertEqual(hygiene.check_run_dir(make_dir() / "run", self.manifest(repo)), [])


PEM_LINES = ["MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7VJTUt9Us8cKj",
             "MBc3q2Jd8Fz1Qm0XyZpL4kWnHsRtUvAaBbCcDdEeFfGgHhIiJjKkLlMmNnOoPpQq"]
PEM = "\n".join(["-----BEGIN RSA PRIVATE KEY-----", *PEM_LINES, "-----END RSA PRIVATE KEY-----"]) + "\n"


class PrivateKeyTest(unittest.TestCase):
    def test_mask_text_masks_whole_block_inclusive(self):
        out = hygiene.mask_text("before\n" + PEM + "after\n")
        for line in PEM_LINES:
            self.assertNotIn(line[:12], out)
        self.assertIn("before", out)
        self.assertIn("after", out)

    def test_mask_text_state_survives_blank_and_keeps_line_count(self):
        text = PEM + "ok\n"
        self.assertEqual(len(hygiene.mask_text(text).split("\n")), len(text.split("\n")))

    def test_in_key_at_detects_window_starting_mid_key(self):
        lines = PEM.splitlines()
        self.assertFalse(hygiene.in_key_at(lines, 0))
        self.assertTrue(hygiene.in_key_at(lines, 1))
        self.assertTrue(hygiene.in_key_at(lines, 2))
        self.assertTrue(hygiene.in_key_at(lines, 3))
        self.assertFalse(hygiene.in_key_at(lines, 4))

    def test_outputs_and_reports_never_echo_body_lines(self):
        run = make_dir()
        write_tree(run, {"outputs/k.txt": PEM, "r-correctness.html": "<pre>\n" + PEM + "</pre>\n"})
        out = hygiene.check_outputs(run) + hygiene.check_reports(run)
        self.assertTrue(out)
        for line in out:
            for body in PEM_LINES:
                self.assertNotIn(body[:12], line)

    def test_publish_files_with_credentials_flagged(self):
        run = make_dir()
        write_tree(run, {"publish/commands.sh": "gh issue create --repo https://user:tok@github.com/o/r.git\n",
                         "publish/issue-C-01.md": f"key {AWS}\n", "publish/pr-1.md": "fine\n"})
        out = hygiene.check_publish(run)
        self.assertEqual(len(out), 2, out)
        text = "\n".join(out)
        self.assertIn("publish/commands.sh", text)
        self.assertIn("publish/issue-C-01.md", text)
        self.assertNotIn("tok@", text)
        self.assertNotIn(AWS, text)
        self.assertEqual(hygiene.check_publish(make_dir()), [])

    def test_cli_flags_credentials_in_publish(self):
        repo, sha = make_git_repo({"a.py": "one\n"})
        run = new_run(repo)
        write_tree(run, {"publish/commands.sh": "git remote add o https://u:tok@h.example/o/r\n"})
        res = run_cli(["hygiene", "--run", str(run)])
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertIn("publish/commands.sh", res.stdout)
        self.assertNotIn("tok@", res.stdout + res.stderr)


class KeyMaterialScanTest(unittest.TestCase):
    def test_mid_key_hunk_in_branch_reports_without_excerpt(self):
        body = [f"{PEM_LINES[0][:-3]}{n:03d}" for n in range(12)]
        key = "\n".join(["-----BEGIN PRIVATE KEY-----", *body, "-----END PRIVATE KEY-----"]) + "\n"
        repo, sha = make_git_repo({"k.pem": key})
        commit_on(repo, "fix/x", {"k.pem": key.replace(body[8], PEM_LINES[1])})
        out = hygiene.check_branch(repo, sha, "fix/x")
        self.assertEqual(len(out), 1, out)
        self.assertTrue(out[0].endswith("possible key material"), out)
        self.assertNotIn(PEM_LINES[1][:12], out[0])

    def test_token_inside_long_base64_run_has_no_excerpt(self):
        repo, sha = make_git_repo({"a.py": "one\n"})
        blob = "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSj+AgEAAoIBAQC7VJTUt9Us8cKjMBc3q2Jd8Fz1Qm0Xy"
        commit_on(repo, "fix/x", {"a.py": f"blob = '{blob}'\n"})
        out = hygiene.check_branch(repo, sha, "fix/x")
        self.assertTrue(out)
        for line in out:
            self.assertNotIn(blob[:12], line)
            self.assertTrue(line.endswith("possible key material"), line)

    def test_ssh_userinfo_with_password_is_masked_plain_git_user_is_not(self):
        self.assertNotIn("pw1", hygiene.mask_line("ssh://u:pw1@h.example/o/r"))
        self.assertEqual(hygiene.mask_line("ssh://git@github.com/o/r"), "ssh://git@github.com/o/r")
        self.assertNotIn("tok", hygiene.mask_line("https://tok@h.example/o/r"))


ONE_LINE_KEY = '{"private_key": "-----BEGIN PRIVATE KEY-----\\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcw\\n-----END PRIVATE KEY-----\\n", "x": 1}'
ONE_BODY = "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcw"


class SingleLineKeyTest(unittest.TestCase):
    def test_mask_text_and_mask_line_hide_the_body_keep_the_rest(self):
        for out in (hygiene.mask_text(ONE_LINE_KEY), hygiene.mask_line(ONE_LINE_KEY)):
            self.assertNotIn(ONE_BODY[:12], out)
            self.assertIn('"x": 1', out)

    def test_begin_without_end_masks_to_end_of_line(self):
        out = hygiene.mask_text('k = "-----BEGIN PRIVATE KEY-----\\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcw')
        self.assertNotIn("MIIEvQ", out)
        self.assertIn('k = "', out)

    def test_excerpt_never_prints_a_begin_line(self):
        self.assertNotIn(ONE_BODY[:12], hygiene._excerpt(ONE_LINE_KEY))
        self.assertNotIn("PRIVATE", hygiene._excerpt("-----BEGIN PRIVATE KEY-----"))

    def test_scan_branch_never_prints_single_line_key(self):
        repo, sha = make_git_repo({"a.py": "one\n"})
        commit_on(repo, "fix/x", {"c.json": ONE_LINE_KEY + "\n"})
        out = hygiene.check_branch(repo, sha, "fix/x")
        self.assertTrue(out)
        self.assertNotIn(ONE_BODY[:12], "\n".join(out))

    def test_outputs_scan_never_prints_single_line_key(self):
        run = make_dir()
        write_tree(run, {"outputs/o.txt": ONE_LINE_KEY + "\n"})
        out = hygiene.check_outputs(run)
        self.assertTrue(out)
        self.assertNotIn(ONE_BODY[:12], "\n".join(out))

    def test_git_ssh_user_without_password_is_not_a_credential(self):
        for url in ("git+ssh://git@github.com/o/r", "ssh://git@github.com/o/r"):
            self.assertEqual(hygiene.mask_line(url), url)
        self.assertNotIn("pw", hygiene.mask_line("git+ssh://u:pw@h/o/r"))
        self.assertNotIn("tok", hygiene.mask_line("HTTPS://tok@h/o/r"))


class OneRuleTest(unittest.TestCase):
    def test_git_https_scheme_with_user_is_a_credential_everywhere(self):
        url = "git+https://tok@github.com/o/r"
        self.assertTrue(hygiene.has_credentials(url))
        self.assertEqual(hygiene.strip_userinfo(url), "git+https://github.com/o/r")
        self.assertNotIn("tok", hygiene.mask_line(url))
        self.assertFalse(hygiene.has_credentials("git+ssh://git@github.com/o/r"))
        self.assertTrue(hygiene.has_credentials("git+ssh://u:pw@github.com/o/r"))

    def test_closed_key_followed_by_unclosed_begin_masks_the_next_line(self):
        first = "a -----BEGIN PRIVATE KEY-----QUJD-----END PRIVATE KEY----- b -----BEGIN PRIVATE KEY-----"
        out = hygiene.mask_text(first + "\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcw\n-----END PRIVATE KEY-----\nafter")
        self.assertNotIn("MIIEvQ", out)
        self.assertNotIn("QUJD", out)
        self.assertTrue(out.endswith("after"))

    def test_end_then_new_begin_on_the_same_line_stays_inside(self):
        out = hygiene.mask_text("-----BEGIN PRIVATE KEY-----\nAAA\n-----END PRIVATE KEY----- -----BEGIN PRIVATE KEY-----\n"
                                "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcw\n-----END PRIVATE KEY-----")
        self.assertNotIn("MIIEvQ", out)


class CliTest(unittest.TestCase):
    def setup_run(self, files):
        repo, sha = make_git_repo({"a.py": "one\n"})
        run = new_run(repo)
        commit_on(repo, "fix/x", files)
        add_finding(run, "BACK", "fix/x")
        return repo, run

    def test_clean_exit_0_with_info(self):
        _, run = self.setup_run({".github/w.yml": f"- uses: actions/checkout@{SHA40} # v4\n"})
        res = run_cli(["hygiene", "--run", str(run)])
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("info:", res.stdout)
        self.assertIn("actions/checkout", res.stdout)

    def test_problems_exit_1_and_never_print_secret(self):
        _, run = self.setup_run({"s.txt": f"k = {AWS}\n", ".idea/x": "x\n"})
        write_tree(run, {"outputs/o.txt": f"{GHP}\n"})
        res = run_cli(["hygiene", "--run", str(run)])
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertIn("fix/x: possible secret", res.stdout)
        self.assertIn("fix/x: local tooling file", res.stdout)
        self.assertIn("outputs/o.txt: possible secret", res.stdout)
        self.assertNotIn(AWS, res.stdout + res.stderr)
        self.assertNotIn(GHP, res.stdout + res.stderr)

    def test_tests_branch_is_checked(self):
        repo, run = self.setup_run({"a.py": "two\n"})
        commit_on(repo, "tests/x", {"t.py": f"k = '{AWS}'\n"})
        manifest = runmod.load(run)
        manifest["baseline"]["BACK"] = {"tests_branch": "tests/x"}
        runmod.save(run, manifest)
        res = run_cli(["hygiene", "--run", str(run)])
        self.assertEqual(res.returncode, 1)
        self.assertIn("tests/x: possible secret", res.stdout)

    def test_raw_secret_in_rendered_html_flagged(self):
        _, run = self.setup_run({"a.py": "two\n"})
        write_tree(run, {"s-correctness.html": f"<pre>{AWS}</pre>\n", "s-quality.html": "<pre>AKIA****</pre>\n"})
        res = run_cli(["hygiene", "--run", str(run)])
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertIn("s-correctness.html: possible secret", res.stdout)
        self.assertNotIn("s-quality.html", res.stdout)
        self.assertNotIn(AWS, res.stdout + res.stderr)

    def test_raw_secret_in_findings_json_flagged(self):
        _, run = self.setup_run({"a.py": "two\n"})
        write_tree(run, {"findings/C-09.json": '{"measurement": {"tool": "rg %s"}}\n' % AWS})
        self.assertEqual(len(hygiene.check_findings(run)), 1)
        res = run_cli(["hygiene", "--run", str(run)])
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertIn("findings/C-09.json: possible secret", res.stdout)
        self.assertNotIn(AWS, res.stdout + res.stderr)


    def test_masked_credential_url_in_a_finding_is_not_flagged_again(self):
        _, run = self.setup_run({"a.py": "two\n"})
        findingsmod.add(run, {"report": "correctness", "category": "x", "dimension": "security", "title": "t",
                              "verdict": "candidate", "severity": "low", "confidence": "docs", "source": "t",
                              "what_happens": "CI clones https://x-access-token:tok123@github.com/o/r.git",
                              "evidence": [{"cite": "BACK/a.py", "from": 1, "to": 1, "note": ""}]})
        self.assertNotIn("tok123", "".join(p.read_text() for p in (run / "findings").glob("*.json")))
        self.assertEqual(hygiene.check_findings(run), [])
        write_tree(run, {"findings/C-08.json": '{"what_happens": "https://u:pw@github.com/o/r"}\n'})
        self.assertEqual(len(hygiene.check_findings(run)), 1)

    def test_bad_run_is_an_error(self):
        res = run_cli(["hygiene", "--run", str(make_dir())])
        self.assertNotEqual(res.returncode, 0)


class AtSignInPasswordTest(unittest.TestCase):
    def test_password_with_one_or_two_at_signs_is_masked_whole(self):
        for url in ("https://user:p@ss@github.com/o/r", "https://user:p@s@s@github.com/o/r?x=1",
                    "ssh://user:p@ss@h.example/o/r", "https://tok@en@h.example#frag"):
            masked = hygiene.mask_line(url)
            self.assertIn("://****@", masked, url)
            self.assertNotIn("ss@", masked.replace("****@", ""), url)
            self.assertNotIn("user", masked, url)
            self.assertTrue(hygiene.has_credentials(url))
            self.assertFalse(hygiene._raw_userinfo(masked), masked)
        self.assertEqual(hygiene.strip_userinfo("https://user:p@ss@github.com/o/r"), "https://github.com/o/r")

    def test_partly_masked_userinfo_is_still_raw(self):
        self.assertTrue(hygiene._raw_userinfo("https://****@ss@github.com/o/r"))

    def test_already_masked_url_is_clean_and_raw_after_masked_is_flagged(self):
        run = make_dir()
        write_tree(run, {"findings/C-01.json": '{"a": "https://****@github.com/o/r"}\n'})
        self.assertEqual(hygiene.check_findings(run), [])
        write_tree(run, {"findings/C-02.json": '{"a": "https://****@a.example/x https://u:p@ss@b.example/y"}\n'})
        out = hygiene.check_findings(run)
        self.assertEqual(len(out), 1, out)
        self.assertTrue(out[0].startswith("findings/C-02.json: credentials in a URL"), out)
        self.assertNotIn("p@ss", out[0])
        self.assertNotIn("ss@b", out[0])


class MaskLineTest(unittest.TestCase):
    def test_mask_line_keeps_whitespace_and_masks_secrets(self):
        self.assertEqual(hygiene.mask_line(f"    k = '{AWS}'  "), "    k = 'AKIA****'  ")
        self.assertEqual(hygiene.mask_line("plain"), "plain")


DEFAULT = "s3cr3tDefault9"  # a readable default: no secret pattern of its own
IDENT40 = "provideObservabilityConfigurationService"
RANDOM40 = "q8ZtR2vXk9LmP4wNs7YbH3jDf6GcA1eUo5TiK0rB"


class NamedSecretTest(unittest.TestCase):
    def test_placeholder_default_of_a_secret_named_variable_is_masked(self):
        line = "      value: ${SECURITY_API_TOKEN_MASTER_VALUE:" + DEFAULT + "}"
        self.assertEqual(hygiene.mask_named(line), "      value: ${SECURITY_API_TOKEN_MASTER_VALUE:****}")
        self.assertEqual(hygiene.mask_named("x=${DB_PASSWORD:-" + DEFAULT + "}"), "x=${DB_PASSWORD:-****}")
        self.assertNotIn(DEFAULT, hygiene.mask_line("@Value(\"${app.client-secret:" + DEFAULT + "}\")"))

    def test_placeholder_of_a_plain_variable_is_kept(self):
        for line in ("source: ${SECURITY_API_TOKEN_MASTER_SOURCE:env}", "port: ${SERVER_PORT:8080}",
                     "password: ${DB_PASSWORD}", "password: ${DB_PASSWORD:}"):
            self.assertEqual(hygiene.mask_named(line, config=True), line)

    def test_bare_config_assignment_masked_only_in_config_files(self):
        self.assertEqual(hygiene.mask_named("  password: " + DEFAULT, config=True), "  password: ****")
        self.assertEqual(hygiene.mask_named("spring.datasource.password=" + DEFAULT, config=True),
                         "spring.datasource.password=****")
        self.assertEqual(hygiene.mask_named("  api-key: " + DEFAULT + "  # dev", config=True), "  api-key: ****  # dev")
        code = "    String token = tokenService.find(id);"
        self.assertEqual(hygiene.mask_named(code), code)
        self.assertEqual(hygiene.mask_named("  password: " + DEFAULT), "  password: " + DEFAULT)

    def test_quoted_literal_and_screaming_env_masked_in_any_file(self):
        self.assertEqual(hygiene.mask_named('const apiKey = "' + DEFAULT + '";'), 'const apiKey = "****";')
        self.assertEqual(hygiene.mask_named('{"client_secret": "' + DEFAULT + '"}'), '{"client_secret": "****"}')
        self.assertEqual(hygiene.mask_named("export DB_PASSWORD=" + DEFAULT), "export DB_PASSWORD=****")

    def test_assignment_nested_after_another_key_is_still_seen(self):
        self.assertEqual(hygiene.mask_named("env: DB_PASSWORD=" + DEFAULT), "env: DB_PASSWORD=****")
        self.assertEqual(hygiene.mask_named("  args: API_TOKEN=" + DEFAULT, config=True), "  args: API_TOKEN=****")
        self.assertEqual(hygiene.mask_named('{"what": "Sends {"api_key": "' + DEFAULT + '"}"}'),
                         '{"what": "Sends {"api_key": "****"}"}')

    def test_curl_header_with_a_secret_name_masked(self):
        line = "  -H 'X-API-Token: " + DEFAULT + "' \\"
        self.assertEqual(hygiene.mask_named(line), "  -H 'X-API-Token: ****' \\")
        self.assertNotIn(DEFAULT, hygiene.mask_named('Authorization: Bearer ' + DEFAULT))

    def test_values_and_names_that_are_not_secrets_are_kept(self):
        for line in ("token-ttl: 3600", "token-enabled: true", "token-uri: https://oauth2.example.com/token",
                     "- key: DB_HOST", "key-store-type: PKCS12", "keycloak: realm", "cache-key-prefix: users",
                     "primaryKey: id", "token-header-name: X-API-Token", "password: ****",
                     "password: <your-password>", "api-key: $API_KEY", "tokenizer: standard",
                     'const val API_TOKEN_SOURCE_ATTRIBUTE = "apiTokenSource"', 'TOKEN_CLAIM = "sub"'):
            self.assertEqual(hygiene.mask_named(line, config=True), line)

    def test_masking_is_idempotent(self):
        for line, config in (("value: ${MASTER_TOKEN:" + DEFAULT + "}", False), ("password: " + DEFAULT, True),
                             ('secret = "' + DEFAULT + '"', False), ("-H 'X-API-Token: " + DEFAULT + "'", False)):
            once = hygiene.mask_named(line, config=config)
            self.assertNotIn(DEFAULT, once)
            self.assertEqual(hygiene.mask_named(once, config=config), once)

    def test_reports_flag_unmasked_named_secrets_without_echoing_them(self):
        run = make_dir()
        row = '<span class="ln"><i>192</i>      value: ${SECURITY_API_TOKEN_MASTER_VALUE:' + DEFAULT + '}</span>'
        cfg = '<span class="ln hl"><i>3</i>  password: ' + DEFAULT + '</span>'
        write_tree(run, {"r-correctness.html": '<figure class="code"><pre><span class="ln"><i>191</i>  x:</span>'
                                               + row + '</pre></figure>\n',
                         "r-quality.html": '<pre data-config><span class="ln"><i>2</i>a: 1</span>' + cfg + '</pre>\n'})
        out = hygiene.check_reports(run)
        self.assertEqual(len(out), 2, out)
        for line in out:
            self.assertNotIn(DEFAULT, line)
            self.assertIn(hygiene.R_NAMED, line)

    def test_reports_with_masked_or_non_config_values_are_clean(self):
        run = make_dir()
        write_tree(run, {"r.html": '<pre><span class="ln"><i>1</i>value: ${MASTER_TOKEN:****}</span>'
                                   '<span class="ln"><i>2</i>password: plain-in-code</span></pre>\n'
                                   '<p>The token: is rotated daily.</p>\n'})
        self.assertEqual(hygiene.check_reports(run), [])


class NamedSecretRunFilesTest(unittest.TestCase):
    def test_outputs_findings_and_publish_flag_named_values_without_echoing_them(self):
        run = make_dir()
        write_tree(run, {"outputs/C-01-red.txt": "env: DB_PASSWORD=" + DEFAULT + "\n",
                         "findings/C-01.json": '{"what_happens": "Sends {\\"api_key\\": \\"' + DEFAULT + '\\"}"}\n',
                         "publish/pr-1.md": "curl -H 'X-API-Token: " + DEFAULT + "' https://x\n"})
        for check in (hygiene.check_outputs, hygiene.check_findings, hygiene.check_publish):
            out = check(run)
            self.assertEqual(len(out), 1, (check.__name__, out))
            self.assertIn(hygiene.R_NAMED, out[0])
            self.assertNotIn(DEFAULT, out[0])

    def test_masked_values_and_bare_config_lines_in_outputs_are_clean(self):
        run = make_dir()
        write_tree(run, {"outputs/a.txt": "DB_PASSWORD=****\npassword: plain-in-a-log\n",
                         "findings/C-01.json": '{"what_happens": "Sends {\\"api_key\\": \\"****\\"}"}\n'})
        self.assertEqual(hygiene.check_outputs(run) + hygiene.check_findings(run), [])

    def test_reports_report_each_named_hit_once(self):
        run = make_dir()
        write_tree(run, {"r.html": '<pre><span class="ln"><i>1</i>x = "a"; DB_PASSWORD=' + DEFAULT + '</span></pre>\n'})
        self.assertEqual(len(hygiene.check_reports(run)), 1, hygiene.check_reports(run))


class FixRunTest(unittest.TestCase):
    def make(self):
        repo, _ = make_git_repo({"a.py": "one\n"})
        run = new_run(repo)
        add_finding(run, "BACK", "")
        path = run / "findings" / "Q-01.json"
        path.write_text(path.read_text(encoding="utf-8").replace(
            '"w"', '"Sends {\\"api_key\\": \\"' + DEFAULT + '\\"}"'), encoding="utf-8")
        write_tree(run, {"outputs/log.txt": f"ok\nX DB_PASSWORD={DEFAULT}\ncall {IDENT40}\n{GHP}\n",
                         "outputs/clean.txt": "nothing here\n",
                         "publish/pr-1.md": "-H 'X-API-Token: " + DEFAULT + "'\n"})
        return run

    def test_fix_masks_outputs_publish_and_findings_and_says_where(self):
        run = self.make()
        before = (run / "outputs" / "clean.txt").stat().st_mtime_ns
        fixed = hygiene.fix_run(run)
        self.assertEqual(fixed, [("findings/Q-01.json", 1), ("outputs/log.txt", 2), ("publish/pr-1.md", 1)])
        text = "".join((run / d / n).read_text(encoding="utf-8")
                       for d, n in (("outputs", "log.txt"), ("publish", "pr-1.md"), ("findings", "Q-01.json")))
        self.assertNotIn(DEFAULT, text)
        self.assertNotIn(GHP, text)
        self.assertIn(IDENT40, text)
        self.assertIn("ok\nX DB_PASSWORD=****\n", text)
        self.assertEqual((run / "outputs" / "clean.txt").stat().st_mtime_ns, before)
        self.assertEqual(hygiene.check_outputs(run) + hygiene.check_findings(run) + hygiene.check_publish(run), [])
        self.assertEqual(hygiene.fix_run(run), [])

    def test_cli_fix_reports_files_never_values_then_checks(self):
        run = self.make()
        res = run_cli(["hygiene", "--run", str(run), "--fix"])
        self.assertIn("fixed: outputs/log.txt (2 lines)", res.stdout)
        self.assertIn("fixed: findings/Q-01.json (1 line)", res.stdout)
        self.assertNotIn(DEFAULT, res.stdout + res.stderr)
        self.assertNotIn("outputs/log.txt: ", res.stdout)
        self.assertIn("hygiene: clean", res.stdout)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)

    def test_fix_leaves_40_char_tokens_in_outputs_alone(self):
        run = make_dir()
        evidence = ("integrity sha512-" + RANDOM40 + "/3BpcCysb5Vffu+B3==\n"
                    "tests/t.py::test_list_tools_v2_returns_all_the_tools[a] PASSED\n")
        write_tree(run, {"outputs/a.txt": evidence})
        self.assertEqual(hygiene.fix_run(run), [])
        self.assertEqual((run / "outputs" / "a.txt").read_text(encoding="utf-8"), evidence)

    def test_binary_files_are_never_rewritten_and_still_reported(self):
        run = self.make()
        blob = b"\xff\xfe DB_PASSWORD=" + DEFAULT.encode() + b"\n"
        (run / "outputs" / "blob.bin").write_bytes(blob)
        self.assertNotIn("outputs/blob.bin", [rel for rel, _ in hygiene.fix_run(run)])
        self.assertEqual((run / "outputs" / "blob.bin").read_bytes(), blob)
        out = hygiene.check_outputs(run)
        self.assertEqual(len(out), 1, out)
        self.assertNotIn(DEFAULT, out[0])

    def test_without_fix_nothing_is_rewritten(self):
        run = self.make()
        res = run_cli(["hygiene", "--run", str(run)])
        self.assertEqual(res.returncode, 1)
        self.assertIn(DEFAULT, (run / "outputs" / "log.txt").read_text(encoding="utf-8"))


class ProseIdentifierTest(unittest.TestCase):
    def test_prose_keeps_a_40_char_code_identifier(self):
        text = f"Rename the bean to {IDENT40}."
        self.assertEqual(hygiene.mask_text(text, prose=True), text)
        for ident in ("get_the_observability_configuration_svcs", "GET_THE_OBSERVABILITY_CONFIGURATION_SVCS",
                      "ProvideObservabilityConfigurationService"):
            self.assertEqual(len(ident), 40)
            self.assertEqual(hygiene.mask_line(ident, prose=True), ident)

    def test_prose_still_masks_random_tokens_and_secrets(self):
        out = hygiene.mask_text(f"token {RANDOM40} and {AWS}", prose=True)
        self.assertNotIn(RANDOM40, out)
        self.assertNotIn(AWS, out)

    def test_strict_mode_still_masks_identifiers(self):
        self.assertNotIn(IDENT40, hygiene.mask_line(IDENT40))
        self.assertNotIn(IDENT40, hygiene.mask_text(IDENT40))

    def test_masked_tokens_counts_only_what_prose_mode_rewrites(self):
        self.assertEqual(hygiene.masked_tokens(f"{IDENT40} {SHA40}"), 0)
        self.assertEqual(hygiene.masked_tokens(f"{RANDOM40} x {RANDOM40[::-1]}"), 2)


if __name__ == "__main__":
    unittest.main()
