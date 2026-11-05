# Vitrine Avello Private MCP (HML only)

Status: source only. Not deployed. Not authenticated to Avello. No paid requests executed.

This is a separate, read-only model gateway for private authorized testing. It neither runs shell commands nor edits GitHub repositories. It does not use the Windows installer.

## Deployment preconditions
1. Independent project/service and a verified deploy capability; keep Core/VIA/V5/Super services unchanged.
2. Python 3.11+, `pip install -r requirements.txt`.
3. Store `MCP_BEARER_TOKEN` (>=32 characters) and `AVELLO_API_KEY` in approved server-side secret storage only. Do not write secrets to repository, chat, issue, PR, or logs.
4. Keep `AVELLO_PAID_ENABLED=false` and single worker. Concurrency semaphore is per process, not a distributed limit.
5. Run `uvicorn server:app --host 127.0.0.1 --port 8765` behind authenticated HTTPS reverse proxy; streamable HTTP route /mcp.
6. Verify unauthorized responses (401), disabled paid tool response, status tool and health; then connect the authenticated MCP URL privately. Client authentication compatibility must be validated.
7. DO NOT enable paid calls until Avello's actual rates, usage reporting and a server-enforced total budget with idempotent billing safeguards are implemented and tested.

## Verification
Run `python -m unittest discover -s tests -v` for static offline checks; this does not prove MCP runtime or Avello provider compatibility.

## Limitations
- Endpoint /v1/responses and model IDs are based on vendor documentation, not a successful real API call.
- Provider request is blocking; evaluate async/execution timeout before public deployment.
- No server-side total money cap or idempotency ledger; paid mode must remain disabled.
- No remote execution, deployment, file modifications, CLI installation, or repository access.
- No claim of a live ChatGPT plugin until endpoint, authentication, capability and real call are verified.
