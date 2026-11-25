import unittest
import json
import httpx
from operational_v5 import read_factory

class AdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_denied_operations_never_contact_upstream(self):
        def deny(request):
            self.fail("unexpected upstream call")
        for tool, project in [("deploy","factory"),("project_status","via")]:
            with self.assertRaises(ValueError):
                await read_factory(tool, project, transport=httpx.MockTransport(deny))

    async def test_read_protocol(self):
        methods = []
        def handler(request):
            self.assertEqual(str(request.url), "http://127.0.0.1:8867/mcp")
            if request.method == "DELETE":
                methods.append("delete")
                return httpx.Response(200)
            body = json.loads(request.content)
            method = body["method"]
            methods.append(method)
            if method == "initialize":
                return httpx.Response(200, headers={"Mcp-Session-Id":"test-session"},
                    json={"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-03-26"}})
            self.assertEqual(request.headers["Mcp-Session-Id"], "test-session")
            if method == "notifications/initialized":
                return httpx.Response(202)
            self.assertEqual(body["params"], {"name":"project_status","arguments":{"project_id":"factory"}})
            return httpx.Response(200,json={"jsonrpc":"2.0","id":2,"result":{"content":[]}})
        result = await read_factory("project_status","factory",transport=httpx.MockTransport(handler))
        self.assertEqual(result, {"content":[]})
        self.assertEqual(methods, ["initialize","notifications/initialized","tools/call","delete"])

    async def test_upstream_failure(self):
        with self.assertRaises(httpx.HTTPStatusError):
            await read_factory("project_status","factory",
                transport=httpx.MockTransport(lambda request: httpx.Response(503)))
