"""Cockpit backend: FastAPI, WebSocket, and mounted FastMCP app."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fastmcp import FastMCP

from .db import connect, ensure

cockpit_mcp = FastMCP("cockpit")


def _safe_rows(query: str, params: tuple = ()) -> list[dict]:
    con = connect()
    try:
        return [dict(row) for row in con.execute(query, params).fetchall()]
    except sqlite3.OperationalError:
        return []
    finally:
        con.close()


@cockpit_mcp.tool
def push_graph_delta(node_id: str, kind: str, text: str) -> dict:
    """Store a cockpit event so the browser can update in real time."""
    con = connect()
    try:
        con.execute(
            "INSERT INTO cockpit_events(kind, payload) VALUES(?,?)",
            ("graph_delta", json.dumps({"node_id": node_id, "kind": kind, "text": text}, ensure_ascii=True)),
        )
        con.commit()
    finally:
        con.close()
    return {"pushed": True}


class InterventionRequest(BaseModel):
    kind: str
    target: str | None = None
    payload: str


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure()
    yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/mcp", cockpit_mcp.http_app())


@app.get("/graph")
def get_graph() -> dict:
    return {
        "nodes": _safe_rows(
            "SELECT node_id, kind, text, state, created_at, parent_id FROM mem_nodes ORDER BY created_at"
        ),
        "edges": _safe_rows("SELECT edge_id, src, dst, relation, rationale FROM mem_edges"),
    }


@app.get("/failures")
def get_failures() -> list[dict]:
    return _safe_rows("SELECT * FROM mem_failures ORDER BY last_seen DESC LIMIT 100")


@app.post("/intervene")
def intervene(request: InterventionRequest) -> dict:
    con = connect()
    try:
        con.execute(
            "INSERT INTO cockpit_interventions(kind, target, payload) VALUES(?,?,?)",
            (request.kind, request.target, request.payload),
        )
        con.execute(
            "INSERT INTO cockpit_events(kind, payload) VALUES(?,?)",
            (
                "intervention",
                json.dumps(
                    {"kind": request.kind, "target": request.target, "payload": request.payload},
                    ensure_ascii=True,
                ),
            ),
        )
        con.commit()
    finally:
        con.close()
    return {"queued": True}


@app.websocket("/ws/state")
async def ws_state(ws: WebSocket) -> None:
    await ws.accept()
    last_id = 0
    try:
        while True:
            con = connect()
            try:
                rows = con.execute(
                    "SELECT id, kind, payload, created_at FROM cockpit_events WHERE id > ? ORDER BY id",
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
                await ws.send_json(
                    {"id": row["id"], "kind": row["kind"], "payload": parsed, "ts": row["created_at"]}
                )
                last_id = row["id"]
            await asyncio.sleep(0.3)
    except WebSocketDisconnect:
        return

