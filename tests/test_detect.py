from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from helpers import SKILL, make_dir, make_git_repo, run_cli, write_tree
from ia import detect
from ia import run as runmod

PKG_VITEST = json.dumps({"scripts": {"test": "vitest run"}, "devDependencies": {"vitest": "1"}})
PKG_JEST = json.dumps({"scripts": {"test": "jest"}, "devDependencies": {"jest": "29"}})


def _tree(files):
    return write_tree(make_dir(), files)


class StackTests(unittest.TestCase):
    def test_ts_vitest(self):
        plan = detect.detect_repo(_tree({"package.json": PKG_VITEST}))
        self.assertEqual(plan["stack"], "ts-js")
        self.assertEqual(plan["test_cmd"], ["npm", "test", "--silent"])
        self.assertEqual(plan["coverage_cmd"], ["npx", "vitest", "run", "--coverage"])
        self.assertTrue({"dependency-cruiser", "knip", "jscpd"} <= set(plan["measure"]))
        self.assertTrue(plan["measured"])

    def test_ts_jest(self):
        plan = detect.detect_repo(_tree({"package.json": PKG_JEST}))
        self.assertEqual(plan["coverage_cmd"], ["npx", "jest", "--coverage"])

    def test_js_lockfile_picks_runner(self):
        for lock, runner in (("pnpm-lock.yaml", "pnpm"), ("yarn.lock", "yarn"), ("package-lock.json", "npm")):
            plan = detect.detect_repo(_tree({"package.json": PKG_VITEST, lock: "x"}))
            self.assertEqual(plan["test_cmd"][0], runner, lock)
        plan = detect.detect_repo(_tree({"package.json": PKG_VITEST}))
        self.assertEqual(plan["test_cmd"][0], "npm")

    def test_python_pytest(self):
        for files in ({"pyproject.toml": "[tool.pytest.ini_options]\n"}, {"pytest.ini": "[pytest]\n"}):
            plan = detect.detect_repo(_tree(files))
            self.assertEqual(plan["stack"], "python")
            self.assertEqual(plan["test_cmd"], ["python3", "-m", "pytest", "-q"])
            self.assertEqual(plan["coverage_cmd"], ["python3", "-m", "pytest", "-q", "--cov"])
            self.assertIn("ruff", plan["measure"])

    def test_python_unittest_fallback(self):
        plan = detect.detect_repo(_tree({"tests/test_a.py": "x = 1\n"}))
        self.assertEqual(plan["stack"], "python")
        self.assertEqual(plan["test_cmd"], ["python3", "-m", "unittest", "discover", "-s", "tests"])
        self.assertIsNone(plan["coverage_cmd"])

    def test_unknown_stack_marked_unmeasured(self):
        plan = detect.detect_repo(_tree({"Cargo.toml": "[package]\nname = 'x'\n"}))
        self.assertEqual(plan["stack"], "unknown")
        self.assertIs(plan["measured"], False)
        self.assertIsNone(plan["test_cmd"])
        self.assertIsNone(plan["coverage_cmd"])
        self.assertEqual((plan["deps"], plan["deps_dirs"], plan["install_cmd"]), ("none", [], None))

    def test_plan_carries_task5_fields(self):
        plan = detect.detect_repo(_tree({"package.json": PKG_VITEST}))
        self.assertEqual(plan["env"], {})
        self.assertEqual(plan["pre"], [])

    def test_python_keeps_python3_when_venv_is_not_symlinked(self):
        repo, sha = make_git_repo({"pyproject.toml": "[tool.pytest.ini_options]\n", "uv.lock": "a"})
        (repo / ".venv" / "bin").mkdir(parents=True)
        (repo / "uv.lock").write_text("b", encoding="utf-8")
        plan = detect.detect_repo(repo, sha)
        self.assertEqual(plan["deps"], "none")
        self.assertEqual(plan["test_cmd"][0], "python3")

    def test_install_cmd_by_lockfile(self):
        cases = (("package-lock.json", ["npm", "ci"]), ("pnpm-lock.yaml", ["pnpm", "install", "--frozen-lockfile"]),
                 ("yarn.lock", ["yarn", "install", "--frozen-lockfile"]))
        for lock, cmd in cases:
            plan = detect.detect_repo(_tree({"package.json": PKG_VITEST, lock: "x"}))
            self.assertEqual(plan["install_cmd"], cmd, lock)
            self.assertEqual(plan["deps_dirs"], ["node_modules"])

    def test_python_install_cmd(self):
        plan = detect.detect_repo(_tree({"pyproject.toml": "pytest"}))
        self.assertEqual(plan["install_cmd"], ["python3", "-m", "pip", "install", "-e", "."])
        self.assertEqual(plan["deps_dirs"], [".venv"])
        plan = detect.detect_repo(_tree({"tests/test_a.py": "x = 1\n"}))
        self.assertIsNone(plan["install_cmd"])
        self.assertEqual(plan["deps"], "none")

    def test_deps_symlink_when_dir_present_and_lockfile_matches(self):
        repo, sha = make_git_repo({"package.json": PKG_VITEST, "package-lock.json": "lock-a"})
        (repo / "node_modules").mkdir()
        self.assertEqual(detect.detect_repo(repo, sha)["deps"], "symlink")
        self.assertEqual(detect.detect_repo(repo)["deps"], "symlink")

    def test_deps_none_when_lockfile_differs_at_sha_install_only_suggested(self):
        repo, sha = make_git_repo({"package.json": PKG_VITEST, "package-lock.json": "lock-a"})
        (repo / "node_modules").mkdir()
        (repo / "package-lock.json").write_text("lock-b", encoding="utf-8")
        plan = detect.detect_repo(repo, sha)
        self.assertEqual(plan["deps"], "none")
        self.assertEqual(plan["install_cmd"], ["npm", "ci"])

    def test_deps_none_when_dir_missing_install_only_suggested(self):
        repo, sha = make_git_repo({"package.json": PKG_VITEST, "package-lock.json": "lock-a"})
        plan = detect.detect_repo(repo, sha)
        self.assertEqual(plan["deps"], "none")
        self.assertEqual(plan["install_cmd"], ["npm", "ci"])

    def test_python_uses_venv_interpreter_when_venv_exists(self):
        root = _tree({"pyproject.toml": "[tool.pytest.ini_options]\n", ".venv/bin/python": ""})
        plan = detect.detect_repo(root)
        self.assertEqual(plan["test_cmd"], [".venv/bin/python", "-m", "pytest", "-q"])
        self.assertEqual(plan["coverage_cmd"], [".venv/bin/python", "-m", "pytest", "-q", "--cov"])
        self.assertEqual(plan["deps"], "symlink")
        plan = detect.detect_repo(_tree({"tests/test_a.py": "x = 1\n", ".venv/bin/python": ""}))
        self.assertEqual(plan["test_cmd"], [".venv/bin/python", "-m", "unittest", "discover", "-s", "tests"])

    def test_lockfile_lookup_in_subdir(self):
        repo, sha = make_git_repo({"web/package.json": PKG_VITEST, "web/package-lock.json": "lock-a"})
        (repo / "web" / "node_modules").mkdir()
        self.assertEqual(detect.detect_repo(repo / "web", sha)["deps"], "symlink")


POM_SPRING = ("<project><parent><groupId>org.springframework.boot</groupId>"
              "<artifactId>spring-boot-starter-parent</artifactId></parent></project>")
GRADLE_KTS_SPRING = 'plugins { id("org.springframework.boot") version "3.3.0"; kotlin("jvm") }\n'


class JvmStackTests(unittest.TestCase):
    def test_maven_runs_offline_and_reads_surefire_reports(self):
        plan = detect.detect_repo(_tree({"pom.xml": "<project/>"}))
        self.assertEqual((plan["stack"], plan["measured"]), ("jvm", True))
        self.assertEqual(plan["test_cmd"], ["mvn", "-B", "-ntp", "-o", "-Dmaven.test.failure.ignore=true", "test"])
        self.assertEqual(plan["junit"], ["**/target/surefire-reports/TEST-*.xml"])
        # dependency:go-offline leaves jars and the surefire provider out (measured in Docker on 2026-10-22): the
        # warm-up is the suite itself, online, failures ignored
        self.assertEqual(plan["install_cmd"], ["mvn", "-B", "-ntp", "-Dmaven.test.failure.ignore=true", "test"])
        self.assertEqual((plan["deps"], plan["deps_dirs"], plan["coverage_cmd"]), ("none", [], None))
        self.assertNotIn("framework", plan)

    def test_maven_wrapper_is_preferred(self):
        plan = detect.detect_repo(_tree({"pom.xml": "<project/>", "mvnw": "#!/bin/sh\n"}))
        self.assertEqual(plan["test_cmd"][0], "./mvnw")
        self.assertEqual(plan["install_cmd"][0], "./mvnw")

    def test_gradle_kotlin_dsl_with_wrapper_runs_offline_and_reads_test_results(self):
        plan = detect.detect_repo(_tree({"build.gradle.kts": GRADLE_KTS_SPRING, "gradlew": "#!/bin/sh\n"}))
        self.assertEqual(plan["stack"], "jvm")
        self.assertEqual(plan["test_cmd"], ["./gradlew", "test", "--offline", "--continue", "--console=plain"])
        self.assertEqual(plan["junit"], ["**/build/test-results/**/TEST-*.xml"])
        # `gradle dependencies` leaves the jars out; `test` exits 1 on a failing test, and the warm-up only fills the
        # cache: the offline run right after reports anything still missing
        self.assertEqual(plan["install_cmd"], ["sh", "-c", "./gradlew test --continue --console=plain || true"])
        self.assertEqual(plan["framework"], "spring-boot")

    def test_gradle_groovy_without_wrapper(self):
        plan = detect.detect_repo(_tree({"build.gradle": "apply plugin: 'java'\n"}))
        self.assertEqual(plan["test_cmd"][0], "gradle")

    def test_spring_boot_in_a_pom(self):
        self.assertEqual(detect.detect_repo(_tree({"pom.xml": POM_SPRING}))["framework"], "spring-boot")

    def test_jvm_wins_over_a_frontend_build_package_json(self):
        plan = detect.detect_repo(_tree({"pom.xml": POM_SPRING, "package.json": PKG_VITEST}))
        self.assertEqual(plan["stack"], "jvm")


class JvmModuleTests(unittest.TestCase):
    def test_spring_package_children_are_modules(self):
        root = _tree({
            "pom.xml": POM_SPRING,
            "src/main/java/com/acme/shop/ShopApplication.java": "x",
            "src/main/java/com/acme/shop/orders/OrderController.java": "x",
            "src/main/java/com/acme/shop/billing/Invoice.java": "x",
            "src/main/resources/application.yml": "x",
            "src/test/java/com/acme/shop/orders/OrderTest.java": "x",
        })
        self.assertEqual(detect.detect_modules(root), [
            "src/main/java/com/acme/shop/.", "src/main/java/com/acme/shop/billing",
            "src/main/java/com/acme/shop/orders", "src/main/resources"])

    def test_kotlin_multi_module_gradle(self):
        root = _tree({
            "settings.gradle.kts": 'include("api", "core")\n', "build.gradle.kts": GRADLE_KTS_SPRING,
            "api/build.gradle.kts": "x", "api/src/main/kotlin/io/acme/api/web/Routes.kt": "x",
            "core/build.gradle.kts": "x", "core/src/main/kotlin/io/acme/core/domain/Order.kt": "x",
            "core/src/main/kotlin/io/acme/core/Core.kt": "x",
        })
        self.assertEqual(detect.detect_modules(root), [
            "api/src/main/kotlin/io/acme/api/web", "core/src/main/kotlin/io/acme/core/.",
            "core/src/main/kotlin/io/acme/core/domain"])


class GoTests(unittest.TestCase):
    def test_go_runs_offline_with_the_local_toolchain(self):
        plan = detect.detect_repo(_tree({"go.mod": "module example.com/shop\n\ngo 1.22\n"}))
        self.assertEqual((plan["stack"], plan["measured"]), ("go", True))
        self.assertEqual(plan["test_cmd"], ["env", "GOPROXY=off", "GOTOOLCHAIN=local", "go", "test", "-json", "./..."])
        self.assertEqual(plan["coverage_cmd"][:2], ["sh", "-c"])
        self.assertIn("go tool cover -func", plan["coverage_cmd"][2])
        self.assertIn("GOPROXY=off", plan["coverage_cmd"][2])
        self.assertEqual(plan["install_cmd"], ["go", "mod", "download"])
        self.assertEqual((plan["deps"], plan["deps_dirs"], plan["measure"]), ("none", [], ["golangci-lint"]))

    def test_go_wins_over_a_tooling_package_json(self):
        plan = detect.detect_repo(_tree({"go.mod": "module m\n", "package.json": PKG_VITEST}))
        self.assertEqual(plan["stack"], "go")

    def test_go_layout_modules(self):
        root = _tree({
            "go.mod": "module m\n", "main.go": "package main\n",
            "cmd/api/main.go": "x", "cmd/worker/main.go": "x",
            "internal/orders/orders.go": "x", "internal/billing/b.go": "x", "internal/db.go": "x",
            "pkg/client/c.go": "x", "handlers/h.go": "x", "docs/readme.md": "x",
            "internal/orders/testdata/f.json": "x", "vendor/x/y.go": "x", "testdata/a.txt": "x",
        })
        self.assertEqual(detect.detect_modules(root), [
            ".", "cmd/api", "cmd/worker", "handlers", "internal/.", "internal/billing", "internal/orders",
            "pkg/client"])


class ToolAndWorkerTests(unittest.TestCase):
    def test_tool_status_uses_which(self):
        status = detect.tool_status(["python3", "definitely-not-a-tool-xyz"])
        self.assertEqual(status, {"python3": True, "definitely-not-a-tool-xyz": False})

    def test_worker_table_covers_every_spec_step_for_both_hosts(self):
        need = {"correctness-bugs", "security", "races", "static", "unit-tests", "e2e", "quality", "measure", "contrast"}
        for host in ("claude-code", "cursor"):
            steps = {w["step"] for w in detect.WORKERS[host]}
            self.assertTrue(need <= steps, (host, need - steps))
            for w in detect.WORKERS[host]:
                self.assertEqual(set(w), {"step", "worker", "check", "install", "fallback"})

    def test_cursor_contrast_uses_agent_ask_mode(self):
        w = [w for w in detect.WORKERS["cursor"] if w["step"] == "contrast"][0]
        self.assertIn("agent -p --mode ask --model", w["worker"])
        self.assertIn("--output-format json", w["worker"])

    def test_exact_install_strings(self):
        installs = {w["install"] for h in detect.WORKERS.values() for w in h}
        for s in ("/plugin install claude-security@claude-plugins-official",
                  "/plugin marketplace add openai/codex-plugin-cc && /plugin install codex@openai-codex",
                  "brew install semgrep", "brew install gitleaks", "brew install trivy", "brew install osv-scanner",
                  "npx -y dependency-cruiser --version", "npx -y knip --version", "npx -y jscpd --version",
                  "/add-plugin superpowers"):
            self.assertIn(s, installs)

    def test_every_pass_name_is_a_fallback_somewhere(self):
        names = ("baseline-inventory", "correctness-general", "races-distributed", "security",
                 "supply-chain-container", "red-test-proof", "unit-tests", "e2e-infra", "quality-lenses", "contrast",
                 "verify-high", "owner-prose")
        fallbacks = {w["fallback"] for h in detect.WORKERS.values() for w in h}
        for name in names:
            self.assertIn(f"references/passes/{name}.md", fallbacks, name)
        for host in detect.WORKERS:
            self.assertEqual([w["fallback"] for w in detect.WORKERS[host] if w["step"] == "unit-tests"],
                             ["references/passes/unit-tests.md"])
            for step in ("baseline", "proof", "verify", "prose"):
                self.assertIn(step, {w["step"] for w in detect.WORKERS[host]})

    def test_races_uses_own_pass(self):
        for host in ("claude-code", "cursor"):
            w = [w for w in detect.WORKERS[host] if w["step"] == "races"][0]
            self.assertEqual((w["worker"], w["install"], w["fallback"]),
                             ("own pass", "", "references/passes/races-distributed.md"))

    def test_worker_status_available(self):
        by = {(w["step"], w["worker"]): w["available"] for w in detect.worker_status("claude-code")}
        self.assertIsNone(by[("security", "claude-security")])
        self.assertIs(by[("races", "own pass")], True)
        self.assertIsInstance(by[("static", "semgrep")], bool)

    def test_npx_measure_rows_need_asking_unless_dependency(self):
        root = _tree({"package.json": json.dumps({"devDependencies": {"knip": "5"}, "dependencies": {"x": "1"}})})
        with mock.patch.object(detect.shutil, "which", return_value="/usr/bin/npx"):
            bare = {w["worker"]: w["available"] for w in detect.worker_status("claude-code") if w["step"] == "measure"}
            dep = {w["worker"]: w["available"]
                   for w in detect.worker_status("claude-code", [root]) if w["step"] == "measure"}
        self.assertEqual(bare, {"dependency-cruiser": None, "knip": None, "jscpd": None})
        self.assertEqual(dep, {"dependency-cruiser": None, "knip": True, "jscpd": None})

    def test_npx_measure_rows_ignore_broken_package_json(self):
        root = _tree({"package.json": "{not json"})
        with mock.patch.object(detect.shutil, "which", return_value="/usr/bin/npx"):
            rows = [w for w in detect.worker_status("cursor", [root]) if w["step"] == "measure"]
        self.assertTrue(rows)
        self.assertTrue(all(w["available"] is None for w in rows))

    def test_cursor_wshobson_install_is_a_cursor_command(self):
        w = [w for w in detect.WORKERS["cursor"] if w["step"] == "quality"][0]
        self.assertEqual(w["install"], "/add-plugin (Cursor 2.5+ marketplace: https://github.com/wshobson/agents)")
        self.assertNotIn("/plugin marketplace", " ".join(r["install"] for r in detect.WORKERS["cursor"]))

    def test_unknown_host_rejected(self):
        with self.assertRaises(runmod.UsageError):
            detect.worker_status("vim")


class DetectCliTests(unittest.TestCase):
    def _run(self, host="claude-code"):
        repo, sha = make_git_repo({"package.json": PKG_VITEST, "package-lock.json": "l", ".gitignore": "out/\n"})
        out = repo / "out"
        res = run_cli(["init", "--system", "s", "--repo", f"app={repo}", "--out", str(out), "--host", host])
        self.assertEqual(res.returncode, 0, res.stderr)
        return repo, sha, out

    def test_detect_writes_manifest(self):
        repo, sha, out = self._run()
        res = run_cli(["detect", "--run", str(out)])
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("deps: none  (suggested install, ask first: npm ci)", res.stdout)
        m = runmod.load(out)
        plan = m["baseline"]["app"]["plan"]
        self.assertEqual(plan["stack"], "ts-js")
        self.assertEqual(plan["deps"], "none")
        self.assertEqual(plan["install_cmd"], ["npm", "ci"])
        self.assertIn("dependency-cruiser", m["tools"])
        self.assertIn("semgrep", m["tools"])
        self.assertIn("claude-code", m["workers"])
        self.assertNotIn("cursor", m["workers"])

    def test_detect_preserves_result(self):
        repo, sha, out = self._run()
        m = runmod.load(out)
        m["baseline"]["app"] = {"result": {"passed": 3}}
        runmod.save(out, m)
        self.assertEqual(run_cli(["detect", "--run", str(out)]).returncode, 0)
        m = runmod.load(out)
        self.assertEqual(m["baseline"]["app"]["result"], {"passed": 3})
        self.assertIn("plan", m["baseline"]["app"])

    def test_detect_rerun_keeps_env_and_pre(self):
        repo, sha, out = self._run()
        self.assertEqual(run_cli(["detect", "--run", str(out)]).returncode, 0)
        m = runmod.load(out)
        m["baseline"]["app"]["plan"]["env"] = {"CI": "1"}
        m["baseline"]["app"]["plan"]["pre"] = [["make", "gen"]]
        runmod.save(out, m)
        self.assertEqual(run_cli(["detect", "--run", str(out)]).returncode, 0)
        plan = runmod.load(out)["baseline"]["app"]["plan"]
        self.assertEqual(plan["env"], {"CI": "1"})
        self.assertEqual(plan["pre"], [["make", "gen"]])
        self.assertEqual(plan["stack"], "ts-js")

    def test_detect_rerun_keeps_keys_edited_with_baseline_set(self):
        repo, sha, out = self._run()
        self.assertEqual(run_cli(["detect", "--run", str(out)]).returncode, 0)
        r = run_cli(["baseline", "--run", str(out), "--set", "app", 'test_cmd=["make","test"]', "deps=install"])
        self.assertEqual(r.returncode, 0, r.stderr)
        plan = runmod.load(out)["baseline"]["app"]["plan"]
        self.assertEqual(sorted(plan["edited"]), ["deps", "test_cmd"])
        self.assertEqual(run_cli(["detect", "--run", str(out)]).returncode, 0)
        plan = runmod.load(out)["baseline"]["app"]["plan"]
        self.assertEqual((plan["test_cmd"], plan["deps"]), (["make", "test"], "install"))
        self.assertEqual(plan["coverage_cmd"], ["npx", "vitest", "run", "--coverage"])
        self.assertEqual(sorted(plan["edited"]), ["deps", "test_cmd"])

    def test_edited_is_not_settable(self):
        repo, sha, out = self._run()
        self.assertEqual(run_cli(["detect", "--run", str(out)]).returncode, 0)
        r = run_cli(["baseline", "--run", str(out), "--set", "app", 'edited=["x"]'])
        self.assertEqual(r.returncode, 2)

    def test_missing_workers_table_line(self):
        repo, sha, out = self._run()
        empty = make_dir()
        res = subprocess.run([sys.executable, str(SKILL / "ia.py"), "detect", "--run", str(out)],
                             capture_output=True, text=True, env={**os.environ, "PATH": str(empty)})
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("missing workers", res.stdout)
        self.assertIn("  [claude-code] static: semgrep  ->  brew install semgrep  "
                      "(fallback: references/passes/supply-chain-container.md)", res.stdout)

    def test_detect_lists_npx_rows_to_ask_about(self):
        repo, sha, out = self._run()
        res = run_cli(["detect", "--run", str(out)])
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("ask before using", res.stdout)
        self.assertIn("[claude-code] measure: knip  ->  npx -y knip --version", res.stdout)
        workers = {w["worker"]: w["available"] for w in runmod.load(out)["workers"]["claude-code"]}
        self.assertIsNone(workers["knip"])

    def test_detect_marks_npx_row_available_when_repo_depends_on_it(self):
        pkg = json.dumps({"scripts": {"test": "vitest run"}, "devDependencies": {"vitest": "1", "jscpd": "4"}})
        repo, sha = make_git_repo({"package.json": pkg, "package-lock.json": "l", ".gitignore": "out/\n"})
        out = repo / "out"
        self.assertEqual(run_cli(["init", "--system", "s", "--repo", f"app={repo}", "--out", str(out),
                                  "--host", "cursor"]).returncode, 0)
        empty_npx = make_dir()
        (empty_npx / "npx").write_text("#!/bin/sh\n")
        (empty_npx / "npx").chmod(0o755)
        res = subprocess.run([sys.executable, str(SKILL / "ia.py"), "detect", "--run", str(out)], capture_output=True,
                             text=True, env={**os.environ, "PATH": f"{empty_npx}:/usr/bin:/bin"})
        self.assertEqual(res.returncode, 0, res.stderr)
        workers = {w["worker"]: w["available"] for w in runmod.load(out)["workers"]["cursor"]}
        self.assertIs(workers["jscpd"], True)
        self.assertIsNone(workers["knip"])

    def test_npx_measure_rows_only_for_ts_js_runs(self):
        repo, sha = make_git_repo({"pyproject.toml": "[tool.pytest.ini_options]\n", ".gitignore": "out/\n"})
        out = repo / "out"
        self.assertEqual(run_cli(["init", "--system", "s", "--repo", f"app={repo}", "--out", str(out),
                                  "--host", "claude-code"]).returncode, 0)
        res = run_cli(["detect", "--run", str(out)])
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertNotIn("ask before using", res.stdout)
        self.assertNotIn("knip", res.stdout)
        workers = [w["worker"] for w in runmod.load(out)["workers"]["claude-code"]]
        self.assertNotIn("knip", workers)
        self.assertIn("semgrep", workers)

    def test_unknown_host_detects_both(self):
        repo, sha, out = self._run("unknown")
        self.assertEqual(run_cli(["detect", "--run", str(out)]).returncode, 0)
        self.assertEqual(set(runmod.load(out)["workers"]), {"claude-code", "cursor"})

    def test_missing_run_fails(self):
        res = run_cli(["detect", "--run", str(make_dir())])
        self.assertEqual(res.returncode, 1)


if __name__ == "__main__":
    unittest.main()
