"""Read-only MCP health; never submits provider inference, even when enabled."""
import http.client
import json
import os
import sys

HOST = "avello.hml.vitrineiapro.com.br"
ORIGIN = "https://"+HOST


def probe(public):
    token = os.getenv("MCP_BEARER_TOKEN", "")
    if len(token)<32:
        raise RuntimeError("private_diagnostic_token_missing")
    conn = http.client.HTTPSConnection(HOST, timeout=8) if public else http.client.HTTPConnection("127.0.0.1",8765,timeout=8)
    def request(path, payload=None, auth=None):
        headers = {"Accept":"application/json, text/event-stream", "Content-Type":"application/json", "MCP-Protocol-Version":"2025-03-26"}
        if auth:
            headers["Authorization"] = "Bearer "+auth
        conn.request("POST" if payload else "GET", path, body=json.dumps(payload) if payload else None, headers=headers)
        r = conn.getresponse()
        return r.status, r.read(1000000), dict(r.getheaders())
    try:
        for candidate in (None, "invalid-healthcheck-token"):
            status, _, headers = request("/mcp", auth=candidate)
            if status!=401:
                raise RuntimeError("unauthenticated_request_not_rejected")
        def rpc(method, params, n):
            status, body, _ = request("/mcp", {"jsonrpc":"2.0", "id":n,"method":method,"params":params}, token)
            if status!=200:
                raise RuntimeError("authenticated_request_failed")
            data = json.loads(body)
            if "error" in data:
                raise RuntimeError("rpc_failed")
            return data["result"]
        rpc("initialize", {"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"avello-health","version":"2"}},1)
        names = {x["name"] for x in rpc("tools/list",{},2)["tools"]}
        if not {"avello_status", "avello_ask"} <= names:
            raise RuntimeError("tools_missing")
        result = rpc("tools/call",{"name":"avello_status","arguments":{}},3)
        state = result.get("structuredContent") or json.loads(next(x["text"] for x in result["content"] if x["type"]=="text"))
        expected = os.getenv("AVELLO_CALLS_ENABLED","false").lower()=="true"
        if state["calls_enabled"] != expected:
            raise RuntimeError("runtime_flag_mismatch")
        if os.getenv("AVELLO_OAUTH_ENABLED","false").lower()=="true":
            for path in ("/.well-known/oauth-protected-resource/mcp", "/.well-known/oauth-authorization-server"):
                status, body, _ = request(path)
                if status!=200:
                    raise RuntimeError("oauth_discovery_failed")
                data = json.loads(body)
                if "issuer" in data:
                    if data["issuer"].rstrip("/")!=ORIGIN or "S256" not in data["code_challenge_methods_supported"]:
                        raise RuntimeError("oauth_metadata_invalid")
                elif data.get("resource")!=ORIGIN+"/mcp":
                    raise RuntimeError("oauth_resource_invalid")
            status, _, _ = request("/oauth/google/callback")
            if status!=400:
                raise RuntimeError("unbound_google_callback_accepted")
        print(json.dumps({"scope":"public_https" if public else "local", "authentication":"ok", "tools":"ok", "google_oauth":state.get("google_oauth_enabled",False), "calls_enabled":expected}), flush=True)
    finally:
        conn.close()


if __name__=="__main__":
    try:
        probe(False)
        probe(True)
    except Exception as exc:
        print("MCP_HEALTHCHECK_FAILED:"+type(exc).__name__, flush=True)
        sys.exit(1)
