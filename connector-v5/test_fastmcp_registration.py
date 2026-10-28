"""Real FastMCP transport test; no Docker, credentials, or deployment calls."""
import json
import types
import unittest
from pathlib import Path

from fastmcp import Client
from marketing_live_patch import apply as marketing
from controlled_operations_patch import apply as controlled


class FastMCPRegistrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_registry_schema_and_confirmation_guard(self):
        source = Path(__file__).with_name('main.py').read_text()
        module = types.ModuleType('isolated_registry_candidate')
        module.__file__ = str(Path(__file__).with_name('main.py'))
        exec(compile(controlled(marketing(source)), module.__file__, 'exec'), module.__dict__)
        # Executing the module does not start the HTTP listener: __name__ differs.
        # A missing confirmation must return before any manifest/file lookup.
        def forbidden_access(*args, **kwargs):
            raise AssertionError('registration test attempted operational access')
        module._project_paths = forbidden_access
        module._manifest_path = forbidden_access
        module._audit = forbidden_access
        module._run = forbidden_access
        async with Client(module.mcp) as client:
            tools = await client.list_tools()
            matches = [tool for tool in tools if tool.name == 'project_manifest_branch_configure']
            self.assertEqual(len(matches), 1)
            schema = matches[0].inputSchema
            required = set(schema.get('required', []))
            self.assertTrue({'project_id', 'branch', 'expected_current_branch', 'expected_remote_commit'} <= required)
            result = await client.call_tool('project_manifest_branch_configure', {
                'project_id': 'isolated-test', 'branch': 'candidate',
                'expected_current_branch': 'previous', 'expected_remote_commit': 'a' * 40,
            })
            text = ''.join(item.text for item in result.content if hasattr(item, 'text'))
            data = json.loads(text)
            self.assertFalse(data['ok'])
            self.assertEqual(data['error'], 'confirmation_required')


if __name__ == '__main__':
    unittest.main()
