"""Dev entrypoint for memory_mcp with hot-reloaded tool bodies."""

from __future__ import annotations

import importlib
import os

from fastmcp import FastMCP

from . import impl as _impl_module

mcp = FastMCP("memory-dev")


def _impl():
    global _impl_module
    if os.environ.get("RESEARCH_AGENT_DEV") == "1":
        _impl_module = importlib.reload(_impl_module)
    return _impl_module


@mcp.tool
def propose_hypothesis(text: str, parent_id: str | None = None, rationale: str = "") -> dict:
    """Create a new hypothesis node and optionally connect it to a parent."""
    return _impl().propose_hypothesis(text, parent_id=parent_id, rationale=rationale)


@mcp.tool
def attach_evidence(node_id: str, evidence_text: str, polarity: str) -> dict:
    """Create an evidence node and connect it to a target hypothesis."""
    return _impl().attach_evidence(node_id, evidence_text, polarity)


@mcp.tool
def mark_refuted(node_id: str, reason: str, evidence_ids: list[str] | None = None) -> dict:
    """Mark an existing node as refuted."""
    return _impl().mark_refuted(node_id, reason, evidence_ids=evidence_ids)


@mcp.tool
def get_active_frontier() -> list[dict]:
    """Return active question and hypothesis nodes ordered by recency."""
    return _impl().get_active_frontier()


@mcp.tool
def get_ancestors(node_id: str) -> list[dict]:
    """Return a node plus its ancestors up to the root."""
    return _impl().get_ancestors(node_id)


@mcp.tool
def record_failure(trigger: str, symptom: str, root_cause: str = "", resolution: str = "") -> dict:
    """Store a failure signature for later matching."""
    return _impl().record_failure(trigger, symptom, root_cause=root_cause, resolution=resolution)


@mcp.tool
def match_signatures(situation: str, k: int = 5) -> list[dict]:
    """FTS search prior failures ranked by BM25 relevance."""
    return _impl().match_signatures(situation, k=k)


@mcp.tool
def ingest_paper(paper_id: str, source: str, structured: dict) -> dict:
    """Store a compressed paper produced by the librarian."""
    return _impl().ingest_paper(paper_id, source, structured)


@mcp.tool
def query_literature(question: str, k: int = 10) -> list[dict]:
    """Return literature ranked by BM25 and trust level."""
    return _impl().query_literature(question, k=k)


@mcp.tool
def find_baselines_for(method_description: str, k: int = 5) -> list[dict]:
    """Return papers whose method descriptions best match the given method."""
    return _impl().find_baselines_for(method_description, k=k)


if __name__ == "__main__":
    mcp.run()

