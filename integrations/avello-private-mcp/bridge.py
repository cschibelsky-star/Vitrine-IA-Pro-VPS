"""Provider adapters; no process execution, filesystem mutation, or model-output execution."""
import json
import os
import threading
import urllib.error
import urllib.request

GPT_MODELS = ("gpt-6.1-sol", "gpt-6-sol", "gpt-6-luna", "gpt-5.6-terra", "gpt-5.6-sol", "gpt-5.6-luna")
GPT_DEFAULT_MODEL = "gpt-6.1-sol"
GPT_URL = "https://avellogateway.online/v1/responses"
# Tentative Anthropic-compatible endpoint; confirm exact vendor contract before enabling calls.
CLAUDE_URL = "https://avellogateway.online/v1/messages"
MAX_CHARS = 12000
MAX_RESPONSE_BYTES = 2_000_000
SLOTS = threading.BoundedSemaphore(2)

def _call(url, headers, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
    try:
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None
        opener = urllib.request.build_opener(NoRedirect())
        with opener.open(req, timeout=65) as resp:
            result = json.loads(resp.read(MAX_RESPONSE_BYTES + 1))
    except urllib.error.HTTPError as exc:
        return {"status": "provider_error", "http_status": exc.code}
    except (urllib.error.URLError, TimeoutError):
        return {"status": "network_error"}
    except (ValueError, TypeError):
        return {"status": "invalid_provider_response"}
    return result if isinstance(result, dict) else {"status": "invalid_provider_response"}

def ask(prompt, provider="gpt", model=None):
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_CHARS:
        return {"status": "rejected", "reason": "invalid_prompt"}
    if provider not in ("gpt", "claude"):
        return {"status": "rejected", "reason": "unsupported_provider"}
    if os.getenv("AVELLO_CALLS_ENABLED", "false").lower() != "true":
        return {"status": "blocked", "reason": "calls_disabled"}
    if provider == "gpt":
        model = model or GPT_DEFAULT_MODEL
        if model not in GPT_MODELS:
            return {"status": "rejected", "reason": "unsupported_model"}
        key = os.getenv("AVELLO_GPT_API_KEY", "")
        url = GPT_URL
        body = {"model": model, "input": prompt, "store": False}
        headers = {"Content-Type": "application/json", "Authorization": "Bearer " + key}
    else:
        configured_model = os.getenv("AVELLO_CLAUDE_MODEL", "")
        model = model or configured_model
        if not (model and model == configured_model and model.startswith("claude-")
                and len(model) <= 100 and all(c.isascii() and (c.isalnum() or c in "-._") for c in model)):
            return {"status": "rejected", "reason": "claude_model_unverified"}
        key = os.getenv("AVELLO_CLAUDE_API_KEY", "")
        url = CLAUDE_URL
        headers = {"Content-Type": "application/json", "Authorization": "Bearer " + key, "anthropic-version": "2023-06-01"}
        body = {"model": model, "max_tokens": 2048, "messages": [{"role": "user", "content": prompt}]}
    if not key:
        return {"status": "not_configured", "provider": provider}
    if not SLOTS.acquire(blocking=False):
        return {"status": "busy"}
    try:
        result = _call(url, headers, body)
    finally:
        SLOTS.release()
    if result.get("status") in ("provider_error", "network_error", "invalid_provider_response"):
        return result
    if provider == "gpt":
        text = "\n".join(str(part.get("text", "")) for item in result.get("output", [])
                         if isinstance(item, dict) for part in item.get("content", [])
                         if isinstance(part, dict) and part.get("type") == "output_text")
    else:
        text = "\n".join(str(part.get("text", "")) for part in result.get("content", [])
                         if isinstance(part, dict) and part.get("type") == "text")
    return {"status": "ok", "provider": provider, "requested_model": model,
            "provider_model": result.get("model"), "text": text[:60000],
            "usage": result.get("usage", {})}

# Read-only discovery; never submits inference or consumes the inference gate.
_CATALOG_CACHE = {}
_CATALOG_LOCK = threading.Lock()

def list_models(provider="gpt"):
    import logging
    if provider not in ("gpt", "claude"):
        return {"status": "rejected", "reason": "unsupported_provider"}
    with _CATALOG_LOCK:
        if provider in _CATALOG_CACHE:
            return _CATALOG_CACHE[provider]
        key_name = "AVELLO_GPT_API_KEY" if provider == "gpt" else "AVELLO_CLAUDE_API_KEY"
        key = os.getenv(key_name, "")
        result = {"status": "not_configured", "provider": provider}
        if key:
            headers = {"Authorization": "Bearer " + key, "Accept": "application/json"}
            if provider == "claude":
                headers["anthropic-version"] = "2023-06-01"
            request = urllib.request.Request("https://avellogateway.online/v1/models", headers=headers, method="GET")
            # Redirects are disabled so credentials stay at the fixed gateway.
            class NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, req, fp, code, msg, headers, newurl):
                    return None
            try:
                opener = urllib.request.build_opener(NoRedirect())
                with opener.open(request, timeout=12) as response:
                    raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise ValueError("catalog_too_large")
                payload = json.loads(raw)
                records = payload.get("data") if isinstance(payload, dict) else None
                if not isinstance(records, list):
                    raise ValueError("invalid_catalog")
                ids = sorted({row["id"] for row in records if isinstance(row, dict)
                              and isinstance(row.get("id"), str)
                              and 0 < len(row["id"]) <= 100
                              and all(c.isascii() and (c.isalnum() or c in "-._:/") for c in row["id"])})
                result = {"status": "ok", "provider": provider, "models": ids[:200]}
            except urllib.error.HTTPError as exc:
                result = {"status": "provider_error", "provider": provider, "http_status": exc.code}
            except (urllib.error.URLError, TimeoutError):
                result = {"status": "network_error", "provider": provider}
            except (ValueError, TypeError):
                result = {"status": "invalid_provider_response", "provider": provider}
        _CATALOG_CACHE[provider] = result
        logging.getLogger("avello.catalog").warning("AVELLO_MODEL_CATALOG %s", json.dumps(result))
        return result

# Explicit, fixed connectivity probes; general inference remains disabled.
import hashlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor
_SMOKE_EXECUTOR = ThreadPoolExecutor(max_workers=1)
_SMOKE_LEDGER_PATH = "/data/avello-smoke.sqlite3"
_SMOKE_PROMPT = "Responda somente com o texto AVELLO_OK."
def _smoke_database():
    db = sqlite3.connect(_SMOKE_LEDGER_PATH, timeout=10)
    db.execute("CREATE TABLE IF NOT EXISTS probes (run_id TEXT, provider TEXT, state TEXT, result TEXT, PRIMARY KEY(run_id, provider))")
    db.commit()
    return db

def _perform_smoke(run_id, provider):
    import logging
    model = GPT_DEFAULT_MODEL if provider == "gpt" else os.getenv("AVELLO_CLAUDE_MODEL", "")
    result = {"provider":provider, "requested_model":model, "run_id":run_id,
              "prompt_sha256":hashlib.sha256(_SMOKE_PROMPT.encode()).hexdigest(),
              "max_output_tokens":64}
    try:
        key = os.getenv("AVELLO_GPT_API_KEY" if provider == "gpt" else "AVELLO_CLAUDE_API_KEY", "")
        headers = {"Content-Type":"application/json", "Authorization":"Bearer "+key,
                   "Idempotency-Key":run_id+"-"+provider}
        if provider == "gpt":
            body = {"model":model,"input":_SMOKE_PROMPT,"store":False,"max_output_tokens":64}
            url = GPT_URL
        else:
            headers["anthropic-version"] = "2023-06-01"
            body = {"model":model,"max_tokens":64,"messages":[{"role":"user","content":_SMOKE_PROMPT}]}
            url = CLAUDE_URL
        response = _call(url,headers,body)
        if response.get("status") in ("provider_error","network_error","invalid_provider_response"):
            result.update({k:response[k] for k in ("status","http_status") if k in response})
        else:
            records = response.get("output",[]) if provider == "gpt" else []
            parts = [p for row in records if isinstance(row,dict) for p in row.get("content",[]) if isinstance(p,dict)] if provider=="gpt" else response.get("content",[])
            text_value = "\n".join(p.get("text","") for p in parts if isinstance(p,dict) and p.get("type") in ("text","output_text") and isinstance(p.get("text"),str))
            reported_model = response.get("model")
            result.update({"status":"ok" if "AVELLO_OK" in text_value else "unexpected_output",
                           "text":text_value[:512],
                           "provider_model":reported_model if isinstance(reported_model,str) and len(reported_model)<=100 else None})
            usage = response.get("usage")
            result["usage"] = {k:v for k,v in usage.items() if k in ("input_tokens","output_tokens","total_tokens","cache_creation_input_tokens","cache_read_input_tokens") and isinstance(v,int) and v>=0} if isinstance(usage,dict) else {}
    except Exception as exc:
        result.update({"status":"execution_error","error_type":type(exc).__name__})
    with _smoke_database() as db:
        db.execute("UPDATE probes SET state='finished', result=? WHERE run_id=? AND provider=?",(json.dumps(result),run_id,provider))
    logging.getLogger("avello.smoke").warning("AVELLO_SMOKE_RESULT %s",json.dumps(result))
    return result

def smoke_probe(provider="gpt"):
    if os.getenv("AVELLO_SMOKE_ENABLED","false").lower()!="true":
        return {"status":"blocked","reason":"smoke_disabled"}
    run_id = os.getenv("AVELLO_SMOKE_RUN_ID","")
    if not run_id or len(run_id)>80 or not all(c.isascii() and (c.isalnum() or c in "-_") for c in run_id):
        return {"status":"blocked","reason":"run_id_required"}
    if provider not in ("gpt","claude"):
        return {"status":"rejected","reason":"unsupported_provider"}
    model = GPT_DEFAULT_MODEL if provider=="gpt" else os.getenv("AVELLO_CLAUDE_MODEL","")
    if (provider=="gpt" and model not in GPT_MODELS) or (provider=="claude" and model!="claude-opus-5"):
        return {"status":"blocked","reason":"probe_model_not_authorized"}
    key_name = "AVELLO_GPT_API_KEY" if provider=="gpt" else "AVELLO_CLAUDE_API_KEY"
    if not os.getenv(key_name):
        return {"status":"not_configured","provider":provider}
    db = _smoke_database()
    try:
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute("SELECT state,result FROM probes WHERE run_id=? AND provider=?",(run_id,provider)).fetchone()
        if existing:
            db.commit()
            return json.loads(existing[1]) if existing[1] else {"status":"queued_or_unknown","provider":provider,"run_id":run_id}
        count = db.execute("SELECT COUNT(*) FROM probes WHERE run_id=?",(run_id,)).fetchone()[0]
        if count>=2:
            db.commit()
            return {"status":"blocked","reason":"probe_limit_reached"}
        db.execute("INSERT INTO probes(run_id,provider,state,result) VALUES(?,?,'reserved',NULL)",(run_id,provider))
        db.commit()
    finally:
        db.close()
    _SMOKE_EXECUTOR.submit(_perform_smoke,run_id,provider)
    return {"status":"accepted","provider":provider,"run_id":run_id}
