"""QA Office FastAPI backend — port 8005."""

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# backend/ must be on sys.path so `app.api.router` etc. resolve
sys.path.insert(0, str(Path(__file__).parent))
# qa-office root must be on sys.path so agents/, schemas, config/ resolve
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    from app.pipeline.runner import shutdown
    shutdown()


app = FastAPI(
    title="QA Office API",
    description="Multi-agent QA orchestration pipeline",
    version="1.0.0",
    lifespan=lifespan,
)

_allowed_origins = [
    o.strip()
    for o in os.environ.get(
        "CORS_ORIGINS",
        "http://localhost:3005,http://127.0.0.1:3005,http://localhost:3000",
    ).split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
    expose_headers=["Content-Disposition"],
)

app.include_router(api_router)


@app.get("/health")
async def health():
    """Health check."""
    return {"status": "healthy", "service": "qa-office", "version": "1.0.0"}


@app.get("/")
async def root():
    """Root."""
    return {"message": "QA Office API", "docs": "/docs"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8005, reload=True)
