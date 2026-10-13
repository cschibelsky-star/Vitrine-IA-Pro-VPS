from __future__ import annotations

import ast
import os
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path


def load_bootstrap():
    source = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    helper = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_project_validation_bootstrap"
    )
    namespace = {}
    exec(compile(ast.Module(body=[helper], type_ignores=[]), "<bootstrap>", "exec"), namespace)
    return namespace["_project_validation_bootstrap"]


class ProjectValidationBootstrapTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source project"
        self.base = self.root / "base"
        self.work = self.root / "work"
        self.bin = self.root / "bin"
        for directory in [self.source, self.base / "vendor", self.bin]:
            directory.mkdir(parents=True)
        (self.source / "bootstrap" / "cache").mkdir(parents=True)
        (self.source / "storage").mkdir()
        (self.source / ".git").mkdir()
        (self.source / "vendor").mkdir()
        (self.source / "artisan").write_text("fixture-project-artisan")
        (self.source / "bootstrap" / "app.php").write_text("fixture-project-bootstrap")
        (self.source / "bootstrap" / "cache" / "packages.php").write_text("fixture-stale-cache")
        (self.source / ".env").write_text("FIXTURE_DO_NOT_COPY=1")
        (self.source / ".env.runtime").write_text("FIXTURE_DO_NOT_COPY=2")
        (self.source / "storage" / "customer-data").write_text("fixture-client-data")
        (self.source / ".git" / "config").write_text("fixture-checkout-credentials")
        (self.source / "vendor" / "wrong").write_text("fixture-source-vendor")
        (self.base / "vendor" / "autoload.php").write_text("fixture-tested-vendor")
        (self.base / "foreign.php").write_text("fixture-other-app")
        self.trace = self.root / "trace"
        php = self.bin / "php"
        php.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$VALIDATION_TRACE"\n')
        php.chmod(0o755)

    def run_bootstrap(self, command="php artisan test --colors=never"):
        script = load_bootstrap()(command)
        script = script.replace("/var/www/html", shlex.quote(str(self.base)))
        script = script.replace("/source", shlex.quote(str(self.source)))
        script = script.replace("/work", shlex.quote(str(self.work)))
        env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ["PATH"])
        env["VALIDATION_TRACE"] = str(self.trace)
        return subprocess.run(["sh", "-c", script], env=env, capture_output=True, text=True)

    def test_only_project_source_and_tested_vendor_are_materialized(self):
        result = self.run_bootstrap()
        self.assertEqual(0, result.returncode, result.stderr)
        project = self.work / "project"
        self.assertEqual("fixture-project-artisan", (project / "artisan").read_text())
        self.assertEqual("fixture-tested-vendor", (project / "vendor" / "autoload.php").read_text())
        for path in ["foreign.php", ".git", ".env.runtime", "vendor/wrong",
                     "storage/customer-data", "bootstrap/cache/packages.php"]:
            self.assertFalse((project / path).exists(), path)
        self.assertEqual("", (project / ".env").read_text())
        self.assertEqual(
            ["artisan package:discover --no-interaction", "artisan test --colors=never"],
            self.trace.read_text().splitlines(),
        )

    def test_source_configuration_and_cache_are_preserved(self):
        result = self.run_bootstrap("php artisan migrate --pretend --no-interaction")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("FIXTURE_DO_NOT_COPY=1", (self.source / ".env").read_text())
        self.assertEqual("fixture-stale-cache",
                         (self.source / "bootstrap/cache/packages.php").read_text())
        self.assertTrue((self.work / "project/storage/framework/sessions").is_dir())

    def test_missing_project_bootstrap_stops_before_artisan(self):
        (self.source / "bootstrap/cache/packages.php").unlink()
        (self.source / "bootstrap/cache").rmdir()
        (self.source / "bootstrap/app.php").unlink()
        (self.source / "bootstrap").rmdir()
        result = self.run_bootstrap()
        self.assertNotEqual(0, result.returncode)
        self.assertFalse(self.trace.exists())


if __name__ == "__main__":
    unittest.main()
