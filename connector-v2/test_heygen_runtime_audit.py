import json
import subprocess
import unittest
from unittest.mock import patch
import heygen_runtime_audit as audit


class InventoryTests(unittest.TestCase):
    def payload(self):
        paths = ['includes/heygen_helper.php', 'includes/video_ai_helper.php',
                 'admin/reporter-ia.php', 'reporter-ia.php',
                 'admin/heygen-diagnostico.php', 'admin/status.php', 'status.php']
        return {'files': [{'path': p, 'sha256': 'b'*64,
                           'endpoint_literals': ['/v3/videos']} for p in paths]}

    def run_mock(self, payload):
        replies = [subprocess.CompletedProcess([], 0, 'a'*64+' sha256:'+'c'*64+' true', ''),
                   subprocess.CompletedProcess([], 0, json.dumps(payload), '')]
        with patch.object(audit.subprocess, 'run', side_effect=replies) as run:
            result = audit.inventory('production')
            commands = [call.args[0] for call in run.call_args_list]
        return result, commands

    def test_fixed_commands_no_shell_or_application_execution(self):
        result, commands = self.run_mock(self.payload())
        self.assertTrue(result['ok'])
        self.assertEqual(commands[0][:4], ['docker', 'inspect', '--format', '{{.Id}} {{.Image}} {{.State.Running}}'])
        self.assertEqual(commands[1][:6], ['docker', 'exec', 'tvsumare_web_prod', 'php', '-n', '-r'])
        self.assertEqual(result['paid_requests'], 0)

    def test_invalid_target_never_executes(self):
        with patch.object(audit.subprocess, 'run') as run:
            self.assertFalse(audit.inventory('production; env')['ok'])
            run.assert_not_called()

    def test_unknown_fields_are_not_returned(self):
        payload = self.payload()
        payload['secret'] = 'DO_NOT_RETURN'
        payload['files'][0]['content'] = 'DO_NOT_RETURN'
        result, _ = self.run_mock(payload)
        self.assertNotIn('DO_NOT_RETURN', json.dumps(result))

    def test_untrusted_path_and_endpoint_rejected(self):
        for field, value in [('path', '.env'), ('endpoint_literals', ['/v3/videos?key=secret'])]:
            payload = self.payload()
            payload['files'][0][field] = value
            result, _ = self.run_mock(payload)
            self.assertFalse(result['ok'])
            self.assertNotIn('secret', json.dumps(result))

    def test_missing_file_is_incomplete(self):
        payload = self.payload()
        payload['files'][0] = {'path': 'includes/heygen_helper.php', 'error': 'missing'}
        result, _ = self.run_mock(payload)
        self.assertFalse(result['ok'])

    def test_errors_never_echo_stderr(self):
        for value in [subprocess.CompletedProcess([], 1, 'secret', 'secret'),
                      subprocess.TimeoutExpired('docker', 30)]:
            kwargs = {'side_effect': value} if isinstance(value, Exception) else {'return_value': value}
            with patch.object(audit.subprocess, 'run', **kwargs):
                result = audit.inventory('production')
                self.assertFalse(result['ok'])
                self.assertNotIn('secret', json.dumps(result))


if __name__ == '__main__':
    unittest.main()
