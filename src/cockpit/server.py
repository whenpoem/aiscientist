"""Cockpit backend: FastAPI, WebSocket, and mounted FastMCP app."""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastmcp import FastMCP
from pydantic import BaseModel

from .db import connect, ensure

cockpit_mcp = FastMCP("cockpit")
mcp_http_app = cockpit_mcp.http_app(path="/mcp", transport="http")


def _safe_rows(query: str, params: tuple = ()) -> list[dict]:
    con = connect()
    try:
        return [dict(row) for row in con.execute(query, params).fetchall()]
    except sqlite3.OperationalError:
        return []
    finally:
        con.close()


def _safe_value(query: str, params: tuple = (), *, key: str = "value", default: int = 0) -> int:
    con = connect()
    try:
        row = con.execute(query, params).fetchone()
        if row is None:
            return default
        value = row[key]
        return default if value is None else int(value)
    except (sqlite3.OperationalError, ValueError, TypeError):
        return default
    finally:
        con.close()


def _record_event(kind: str, payload: dict) -> int:
    con = connect()
    try:
        cursor = con.execute(
            "INSERT INTO cockpit_events(kind, payload) VALUES(?,?)",
            (kind, json.dumps(payload, ensure_ascii=False)),
        )
        con.commit()
        return int(cursor.lastrowid or 0)
    finally:
        con.close()


def _allowed_origins() -> list[str]:
    origins = {"http://localhost:5173", "http://127.0.0.1:5173"}
    extra = os.getenv("COCKPIT_ALLOWED_ORIGINS", "")
    for origin in extra.split(","):
        cleaned = origin.strip()
        if cleaned:
            origins.add(cleaned)
    return sorted(origins)


def _absolute_url(request: Request, path: str) -> str:
    return f"{str(request.base_url).rstrip('/')}{path}"


def _ws_url(request: Request) -> str:
    scheme = "wss" if request.url.scheme == "https" else "ws"
    return f"{scheme}://{request.url.netloc}/ws/state"


def _state_payload(request: Request) -> dict:
    return {
        "graph": {
            "nodes": _safe_rows(
                "SELECT node_id, kind, text, state, created_at, parent_id "
                "FROM mem_nodes ORDER BY created_at"
            ),
            "edges": _safe_rows("SELECT edge_id, src, dst, relation, rationale FROM mem_edges"),
        },
        "failures": _safe_rows("SELECT * FROM mem_failures ORDER BY last_seen DESC LIMIT 100"),
        "interventions": _safe_rows(
            "SELECT id, kind, target, payload, created_at, delivered_at "
            "FROM cockpit_interventions ORDER BY created_at DESC LIMIT 20"
        ),
        "meta": {
            "api_base_url": str(request.base_url).rstrip("/"),
            "ws_url": _ws_url(request),
            "last_event_id": _safe_value(
                "SELECT COALESCE(MAX(id), 0) AS value FROM cockpit_events"
            ),
            "mcp": {
                "transport": "http",
                "url": _absolute_url(request, "/mcp"),
            },
        },
    }


@cockpit_mcp.tool
def push_graph_delta(node_id: str, kind: str, text: str) -> dict:
    """Store a cockpit event so the browser can update in real time."""
    event_id = _record_event("graph_delta", {"node_id": node_id, "kind": kind, "text": text})
    return {"pushed": True, "event_id": event_id}


class InterventionRequest(BaseModel):
    kind: str
    target: str | None = None
    payload: str


class HealthResponse(BaseModel):
    ok: bool
    last_event_id: int


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure()
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(mcp_http_app.lifespan(app))
        yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/graph")
def get_graph() -> dict:
    return {
        "nodes": _safe_rows(
            "SELECT node_id, kind, text, state, created_at, parent_id "
            "FROM mem_nodes ORDER BY created_at"
        ),
        "edges": _safe_rows("SELECT edge_id, src, dst, relation, rationale FROM mem_edges"),
    }


@app.get("/failures")
def get_failures() -> list[dict]:
    return _safe_rows("SELECT * FROM mem_failures ORDER BY last_seen DESC LIMIT 100")


@app.get("/interventions")
def get_interventions() -> list[dict]:
    return _safe_rows(
        "SELECT id, kind, target, payload, created_at, delivered_at "
        "FROM cockpit_interventions ORDER BY created_at DESC LIMIT 20"
    )


@app.get("/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    return HealthResponse(
        ok=True,
        last_event_id=_safe_value("SELECT COALESCE(MAX(id), 0) AS value FROM cockpit_events"),
    )


@app.get("/state")
def get_state(request: Request) -> dict:
    return _state_payload(request)


@app.post("/intervene")
def intervene(request: InterventionRequest) -> dict:
    payload = request.payload.strip()
    con = connect()
    try:
        con.execute(
            "INSERT INTO cockpit_interventions(kind, target, payload) VALUES(?,?,?)",
            (request.kind, request.target, payload),
        )
        con.commit()
    finally:
        con.close()
    event_id = _record_event(
        "intervention",
        {"kind": request.kind, "target": request.target, "payload": payload},
    )
    return {"queued": True, "event_id": event_id}


@app.websocket("/ws/state")
async def ws_state(ws: WebSocket) -> None:
    await ws.accept()
    try:
        last_id = max(0, int(ws.query_params.get("last_id", "0")))
    except ValueError:
        last_id = 0
    try:
        while True:
            con = connect()
            try:
                rows = con.execute(
                    "SELECT id, kind, payload, created_at "
                    "FROM cockpit_events WHERE id > ? ORDER BY id",
                    (last_id,),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
            finally:
                con.close()

            for row in rows:
                payload = row["payload"] or "{}"
                try:
                    parsed = json.loads(payload)
                except json.JSONDecodeError:
                    parsed = {"raw": payload}
                await ws.send_json({
                    "id": row["id"],
                    "kind": row["kind"],
                    "payload": parsed,
                    "ts": row["created_at"],
                })
                last_id = row["id"]
            await asyncio.sleep(0.3)
    except WebSocketDisconnect:
        return


app.mount("/", mcp_http_app)
