"""Top-level API router: mounts every versioned route group."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import auth, runs, sat

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(sat.router)
api_router.include_router(runs.router)
