"""Normalize a real mission trace for the existing recorded Mission Control UI."""
from __future__ import annotations

import json
from pathlib import Path

from .telemetry import NodeTelemetry


def compute_ephemeris(states):
    return {"frames": states.get("frames", []), "samples": [{**s, "node_id": s["node_id"].split(":", 1)[1].lower()}
                        for s in states["samples"] if s["node_id"].startswith("compute:")], "events": []}


def add_telemetry(recorder, states, result, decision, end_s, profiles=None):
    if not decision:
        return
    if any("in_sunlight" not in s for s in states["samples"] if s["node_id"].startswith("compute:")):
        return
    def record(at, kind, source, node, **payload):
        recorder.emit(kind, int(at * 1e9), source=source, node_id=node, job_id=result["job_id"], payload=payload)
    telemetry = NodeTelemetry(compute_ephemeris(states))
    for name, state in telemetry.state.items():
        profile = (profiles or {}).get(f"compute:{name.upper()}", {})
        state.update(soc=float(profile.get("soc", .70)), temperature_c=float(profile.get("temperature_c", 42)))
    telemetry.emit = record
    telemetry.snapshot(None)
    start = min(end_s, decision.compute_start_s)
    telemetry.advance(start)
    finish = min(end_s, result.get("actual_compute_finish_s", start))
    telemetry.advance(finish, decision.selected_node.split(":", 1)[1].lower())
    telemetry.snapshot(None)
    telemetry.advance(end_s)


def write_bundle(run_dir: Path, states: dict, result: dict, publish: Path | None = None):
    events = [json.loads(line) for line in (run_dir / "events.jsonl").read_text().splitlines()]
    def node(name):
        if name and name.startswith("compute:"):
            return name.split(":", 1)[1].lower()
        if name and name.startswith("comm:"):
            return name.split(":", 1)[1]
        return name
    transfers, completed = [], {e["payload"].get("transfer_id") for e in events if e["header"]["event_type"] == "TRANSFER_COMPLETED"}
    requested = {e["payload"]["transfer_id"]: e["payload"].get("ready_s", 0)
                 for e in events if e["header"]["event_type"] == "TRANSFER_COMPLETED"}
    for event in events:
        event["header"]["node_id"] = node(event["header"]["node_id"])
        payload = event["payload"]
        if "selected_action" in payload:
            payload["selected_action"]["node_id"] = node(payload["selected_action"]["node_id"])
        if event["header"]["event_type"] == "TRANSFER_PLANNED" and payload["transfer_id"] in completed:
            hops = [{**hop, "source": node(hop["source"]), "destination": node(hop["destination"])} for hop in payload["hops"]]
            transfers.append({"transfer_id": payload["transfer_id"], "hops": hops,
                "requested_s": requested[payload["transfer_id"]], "finish_s": payload["predicted_finish_s"],
                "bytes": hops[0]["reserved_bytes"], "stage": "input" if "-INPUT-" in payload["transfer_id"] else "result"})
    replay_result = {**result, "mission_kind": "joint-axb", "horizon_s": max(.001, result.get("completion_sim_s", result.get("failed_at_sim_s", 0))),
        "execution_backend": result["backend"], "gmat_backend": "REAL" if result.get("contact_generation", {}).get("source") == "real GMAT" else "PROVIDED",
        "policy": "joint earliest ground delivery", "iteration": result.get("iterations", 0),
        "converged": result["status"] == "completed"}
    relays = [{**s, "node_id": node(s["node_id"])} for s in states["samples"] if s["node_id"].startswith("comm:")]
    bundle = {"schema_version": 1, "run_id": result["run_id"], "result": replay_result,
        "ephemeris": compute_ephemeris(states), "events": events,
        "communication": {"ephemeris": {"samples": relays}, "relay_ids": sorted({s["node_id"] for s in relays}),
                          "transfers": transfers, "kind": "mission input/result"}}
    content = json.dumps(bundle, separators=(",", ":"))
    (run_dir / "execution-trace.json").write_text(content, encoding="utf-8")
    if publish:
        temporary = publish.with_suffix(".incoming")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(publish)
    return bundle
