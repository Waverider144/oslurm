from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .analysis import load_events
from .recorder import digest_state
from .schema import TraceEventType


@dataclass(frozen=True)
class ReplayResult:
    final_topology_hash: str
    final_node_state_digest: str
    final_job_state_digest: str
    event_count: int


def replay_trace(run_dir: Path) -> ReplayResult:
    topology_edges: set[str] = set()
    nodes: dict[str, dict[str, Any]] = {}
    jobs: dict[str, str] = {}
    for event in load_events(run_dir):
        et = event.header.event_type
        if et == TraceEventType.GLOBAL_SNAPSHOT.value:
            state = event.payload.get("state", {})
            topology_edges = set(state.get("topology_edges", sorted(topology_edges)))
            nodes.update(state.get("nodes", {}))
            jobs.update(state.get("jobs", {}))
            continue
        if et == TraceEventType.TOPOLOGY_EDGE_ADDED.value and event.payload.get("edge_id"):
            topology_edges.add(event.payload["edge_id"])
        if et == TraceEventType.TOPOLOGY_EDGE_REMOVED.value and event.payload.get("edge_id"):
            topology_edges.discard(event.payload["edge_id"])
        if et == TraceEventType.NODE_OPERATING_SNAPSHOT.value and event.header.node_id:
            nodes[event.header.node_id] = dict(event.payload)
        if event.header.job_id and et.startswith("JOB_"):
            jobs[event.header.job_id] = et
    return ReplayResult(
        final_topology_hash=digest_state({"edges": sorted(topology_edges)}),
        final_node_state_digest=digest_state(nodes),
        final_job_state_digest=digest_state(jobs),
        event_count=len(load_events(run_dir)),
    )
