"""Real Maven and Gradle (in Docker) against the jvm plan: offline means offline, deps=install fills the cache, the
counts come from the JUnit reports. Opt-in: IA_DOCKER_JVM=1 and a running Docker (it pulls maven and gradle images
and downloads Spring Boot into throwaway Docker volumes, removed at the end)."""
from __future__ import annotations

import os
import shutil
import subprocess
import unittest
import uuid

from helpers import make_dir, make_git_repo

from ia import baseline as bl
from ia import detect
from ia import run as runmod

MAVEN_IMAGE = "maven:3.9-eclipse-temurin-21"
GRADLE_IMAGE = "gradle:8.10-jdk21"

# A shim per tool: the real tool in Docker on the current dir; an offline flag also cuts the network, so a plan that
# claims to run offline and still needs the network fails here.
SHIM = """#!/bin/sh
net=""
for a in "$@"; do [ "$a" = "{flag}" ] && net="--network none"; done
exec docker run --rm $net -v "$PWD":/w -w /w -v {volume}:{cache} {image} {tool} "$@"
"""

POM = """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <parent><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-parent</artifactId>
    <version>3.3.4</version></parent>
  <groupId>com.acme</groupId><artifactId>pagos</artifactId><version>0.1.0</version>
  <properties><java.version>21</java.version></properties>
  <dependencies>
    <dependency><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter</artifactId></dependency>
    <dependency><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-test</artifactId>
      <scope>test</scope></dependency>
  </dependencies>
</project>
"""
MAVEN_FILES = {
    "pom.xml": POM,
    "src/main/java/com/acme/pagos/PagosApplication.java": (
        "package com.acme.pagos;\nimport org.springframework.boot.SpringApplication;\n"
        "import org.springframework.boot.autoconfigure.SpringBootApplication;\n@SpringBootApplication\n"
        "public class PagosApplication { public static void main(String[] a) { "
        "SpringApplication.run(PagosApplication.class, a); } }\n"),
    "src/main/java/com/acme/pagos/cobros/Cobros.java": (
        "package com.acme.pagos.cobros;\nimport org.springframework.stereotype.Service;\n@Service\n"
        "public class Cobros { public int total(int a, int b) { return a + b; } }\n"),
    "src/main/java/com/acme/pagos/web/Web.java": "package com.acme.pagos.web;\npublic class Web {}\n",
    "src/main/resources/application.properties": "spring.main.banner-mode=off\n",
    "src/test/java/com/acme/pagos/cobros/CobrosTest.java": (
        "package com.acme.pagos.cobros;\nimport static org.junit.jupiter.api.Assertions.assertEquals;\n"
        "import org.junit.jupiter.api.Test;\nclass CobrosTest {\n"
        "  @Test void suma() { assertEquals(3, new Cobros().total(1, 2)); }\n"
        "  @Test void fallaAProposito() { assertEquals(5, new Cobros().total(1, 2)); }\n}\n"),
    "src/test/java/com/acme/pagos/PagosApplicationTests.java": (
        "package com.acme.pagos;\nimport org.junit.jupiter.api.Test;\n"
        "import org.springframework.boot.test.context.SpringBootTest;\n@SpringBootTest\n"
        "class PagosApplicationTests { @Test void contextLoads() {} }\n"),
}
GRADLE_FILES = {
    "settings.gradle.kts": 'rootProject.name = "inventario"\n',
    "build.gradle.kts": (
        'plugins {\n    id("org.springframework.boot") version "3.3.4"\n'
        '    id("io.spring.dependency-management") version "1.1.6"\n    kotlin("jvm") version "1.9.25"\n'
        '    kotlin("plugin.spring") version "1.9.25"\n}\ngroup = "io.acme"\nversion = "0.1.0"\n'
        "java { toolchain { languageVersion = JavaLanguageVersion.of(21) } }\nrepositories { mavenCentral() }\n"
        'dependencies {\n    implementation("org.springframework.boot:spring-boot-starter")\n'
        '    implementation("org.jetbrains.kotlin:kotlin-reflect")\n'
        '    testImplementation("org.springframework.boot:spring-boot-starter-test")\n'
        '    testImplementation("org.jetbrains.kotlin:kotlin-test-junit5")\n'
        '    testRuntimeOnly("org.junit.platform:junit-platform-launcher")\n}\n'
        "tasks.withType<Test> { useJUnitPlatform() }\n"),
    "src/main/kotlin/io/acme/inventario/InventarioApplication.kt": (
        "package io.acme.inventario\nimport org.springframework.boot.autoconfigure.SpringBootApplication\n"
        "import org.springframework.boot.runApplication\n@SpringBootApplication\nclass InventarioApplication\n"
        "fun main(args: Array<String>) { runApplication<InventarioApplication>(*args) }\n"),
    "src/main/kotlin/io/acme/inventario/stock/Stock.kt": (
        "package io.acme.inventario.stock\nimport org.springframework.stereotype.Service\n@Service\n"
        "class Stock { fun reservar(disponible: Int, pedido: Int): Boolean = pedido <= disponible }\n"),
    "src/main/kotlin/io/acme/inventario/api/Api.kt": "package io.acme.inventario.api\nclass Api\n",
    "src/main/resources/application.properties": "spring.main.banner-mode=off\n",
    "src/test/kotlin/io/acme/inventario/stock/StockTest.kt": (
        "package io.acme.inventario.stock\nimport kotlin.test.Test\nimport kotlin.test.assertTrue\n"
        "import kotlin.test.assertFalse\nimport org.junit.jupiter.api.Disabled\nclass StockTest {\n"
        "    @Test fun alcanza() { assertTrue(Stock().reservar(5, 3)) }\n"
        "    @Test fun fallaAProposito() { assertTrue(Stock().reservar(1, 3)) }\n"
        "    @Test fun noAlcanza() { assertFalse(Stock().reservar(1, 3)) }\n"
        "    @Disabled @Test fun salteado() {}\n}\n"),
    "src/test/kotlin/io/acme/inventario/InventarioApplicationTests.kt": (
        "package io.acme.inventario\nimport org.junit.jupiter.api.Test\n"
        "import org.springframework.boot.test.context.SpringBootTest\n@SpringBootTest\n"
        "class InventarioApplicationTests { @Test fun contextLoads() {} }\n"),
}


def _docker_ready() -> bool:
    if os.environ.get("IA_DOCKER_JVM") != "1" or not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "info"], capture_output=True).returncode == 0


@unittest.skipUnless(_docker_ready(), "set IA_DOCKER_JVM=1 with a running Docker to run Maven and Gradle for real")
class JvmInDockerTest(unittest.TestCase):
    def shims(self, tool: str, image: str, cache: str, flag: str) -> dict:
        volume = f"ia-test-{tool}-{uuid.uuid4().hex[:8]}"
        self.addCleanup(subprocess.run, ["docker", "volume", "rm", "-f", volume], capture_output=True)
        bin_dir = make_dir()
        shim = bin_dir / tool
        shim.write_text(SHIM.format(flag=flag, volume=volume, cache=cache, image=image, tool=tool), encoding="utf-8")
        shim.chmod(0o755)
        return {"PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"}

    def audit(self, files: dict, env: dict, alias: str):
        repo, sha = make_git_repo(files)
        run = make_dir() / "run"
        runmod.init_run("sys", [(alias, repo, "")], run, "es", False, "unknown")
        manifest = runmod.load(run)
        plan = detect.detect_repo(repo, sha)
        plan["env"] = env
        manifest["baseline"][alias] = {"plan": plan}
        runmod.save(run, manifest)
        return run, plan

    def offline_then_install(self, run, alias: str):
        cold = bl.run_baseline(run, alias, 900)
        self.assertFalse(cold["measured"], cold)
        self.assertIn("deps=install", cold["error"])
        bl.set_plan(run, alias, {"deps": "install"})
        return bl.run_baseline(run, alias, 900)

    def test_maven_spring_boot(self):
        run, plan = self.audit(MAVEN_FILES, self.shims("mvn", MAVEN_IMAGE, "/root/.m2", "-o"), "PAGOS")
        self.assertEqual((plan["stack"], plan["framework"]), ("jvm", "spring-boot"))
        warm = self.offline_then_install(run, "PAGOS")
        self.assertEqual((warm["passed"], warm["failed"], warm["total"], warm["runner"]), (2, 1, 3, "junit-xml"), warm)

    def test_gradle_kotlin_spring_boot(self):
        env = self.shims("gradle", GRADLE_IMAGE, "/home/gradle/.gradle", "--offline")
        run, plan = self.audit(GRADLE_FILES, env, "INV")
        self.assertEqual((plan["stack"], plan["framework"]), ("jvm", "spring-boot"))
        warm = self.offline_then_install(run, "INV")
        self.assertEqual((warm["passed"], warm["failed"], warm["total"], warm["runner"]), (3, 1, 4, "junit-xml"), warm)


if __name__ == "__main__":
    unittest.main()
