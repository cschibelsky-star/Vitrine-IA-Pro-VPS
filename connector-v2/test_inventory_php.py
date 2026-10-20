"""Exercise the actual PHP scanner against synthetic files, without Docker/API."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from heygen_runtime_audit import PHP_SCAN


@unittest.skipUnless(shutil.which('php'), 'PHP is supplied by isolated CI')
class PhpScannerTests(unittest.TestCase):
    def test_token_scan_never_executes_application_or_returns_secrets(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            paths = ['includes/heygen_helper.php', 'includes/video_ai_helper.php',
                     'admin/reporter-ia.php', 'reporter-ia.php',
                     'admin/heygen-diagnostico.php', 'admin/status.php', 'status.php']
            for name in paths:
                path = root/name
                path.parent.mkdir(exist_ok=True)
                path.write_text("<?php throw new Exception('EXECUTED'); $key='SENSITIVE'; "
                                "$a='/v2/video/generate'; $b='/v3/videos'; "
                                "// '/v1/video_status.get' comment must not count\n")
            script = PHP_SCAN.replace("'/var/www/html/'", json.dumps(folder+'/'))
            result = subprocess.run(['php', '-n', '-r', script], capture_output=True,
                                    text=True, check=True, timeout=10)
            body = json.loads(result.stdout)
            self.assertEqual(len(body['files']), 7)
            for row in body['files']:
                self.assertEqual(set(row['endpoint_literals']), {'/v2/video/generate', '/v3/videos'})
                self.assertEqual(len(row['sha256']), 64)
            self.assertNotIn('SENSITIVE', result.stdout)
            self.assertNotIn('EXECUTED', result.stdout)

    def test_missing_files_reported_without_content(self):
        with tempfile.TemporaryDirectory() as folder:
            script = PHP_SCAN.replace("'/var/www/html/'", json.dumps(folder+'/'))
            result = subprocess.run(['php', '-n', '-r', script], capture_output=True,
                                    text=True, check=True, timeout=10)
            self.assertTrue(all(row['error'] == 'missing_or_unsafe'
                                for row in json.loads(result.stdout)['files']))
