"""Private read-only bridge for the Factory pilot."""

import httpx
from fastapi import FastAPI, HTTPException
from operational_v5 import read_factory, TOOLS

app = FastAPI(
    docs_url=None,
    redoc_url=None,
    openapi_url=None
)

@app.get("/healthz")
async def health():
    return {
        "alive": True,
        "mode": "read_only",
        "project": "factory"
    }

@app.get("/factory/{operation}")
async def factory_read(operation: str):
    if operation not in TOOLS:
        raise HTTPException(
            status_code=403,
            detail="operation_not_allowed"
        )

    transport = httpx.AsyncHTTPTransport(retries=0)

    try:
        result = await read_factory(
            operation,
            "factory",
            transport=transport
        )
        return result
    except (httpx.HTTPError, ValueError,
            TypeError, KeyError, AttributeError):
        raise HTTPException(
            status_code=502,
            detail="upstream_unavailable"
        ) from None
