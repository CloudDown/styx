"""Dashboard API for Styx — mounted at /api/plugins/styx/."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

_ROOT = Path(__file__).resolve().parents[1]


def _supervisor():
    parent = str(_ROOT.parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    return importlib.import_module("styx.backend.supervisor")


class StartBody(BaseModel):
    client_auth: bool = False


@router.get("/status")
def get_status() -> dict:
    return _supervisor().status()


@router.post("/start")
def post_start(body: StartBody | None = None) -> dict:
    body = body or StartBody()
    try:
        return _supervisor().start(wait=True, client_auth=body.client_auth)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/stop")
def post_stop() -> dict:
    try:
        _supervisor().stop()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _supervisor().status()
