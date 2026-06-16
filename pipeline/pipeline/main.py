from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from pipeline.client import EdgeFunctionClient
from pipeline.config import settings
from pipeline.errors import AdapterError, EdgeFunctionError, EdgeFunctionTimeout, ValidationError


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.http = httpx.AsyncClient(timeout=30)
    app.state.client = EdgeFunctionClient(
        http=app.state.http,
        supabase_url=settings.supabase_url,
        service_role_key=settings.supabase_service_role_key,
        max_retries=settings.max_retries,
        retry_backoff_base=settings.retry_backoff_base,
    )
    yield
    await app.state.http.aclose()


app = FastAPI(title="KnowledgeForest Ingestion Pipeline", version="0.1.0", lifespan=lifespan)


# ── Exception handlers ─────────────────────────────────────────────


@app.exception_handler(ValidationError)
async def handle_validation(request: Request, exc: ValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"error": str(exc)})


@app.exception_handler(AdapterError)
async def handle_adapter(request: Request, exc: AdapterError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"error": str(exc)})


@app.exception_handler(EdgeFunctionError)
async def handle_edge_error(request: Request, exc: EdgeFunctionError) -> JSONResponse:
    return JSONResponse(
        status_code=502,
        content={"error": "Edge function error", "detail": str(exc)},
    )


@app.exception_handler(EdgeFunctionTimeout)
async def handle_edge_timeout(request: Request, exc: EdgeFunctionTimeout) -> JSONResponse:
    return JSONResponse(
        status_code=504,
        content={"error": "Edge function timeout", "detail": str(exc)},
    )


# ── Health ─────────────────────────────────────────────────────────


@app.get("/api/v1/health")
async def health() -> dict:
    return {"status": "ok", "supabase_url": settings.supabase_url}


# ── Register route modules ────────────────────────────────────────

from pipeline.api import ingest  # noqa: E402

app.include_router(ingest.router, prefix="/api/v1/ingest")
