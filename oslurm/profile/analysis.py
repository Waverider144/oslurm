from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .schema import TraceEvent, TraceEventType


BOTTLENECK_LABELS = {
    "COMPUTE_LIMITED": "COMPUTE_CAPACITY",
    "POWER_LIMITED": "POWER",
    "THERMAL_LIMITED": "THERMAL",
    "TOPOLOGY_LIMITED": "TOPOLOGY",
    "QUEUE_LIMITED": "QUEUEING",
    "MIGRATION_LIMITED": "MIGRATION",
    "CHECKPOINT_LIMITED": "CHECKPOINT_TRANSFER",
    "SCHEDULER_LIMITED": "SCHEDULER_DECISION",
    "CONTROL_PLANE_LIMITED": "CONTROL_PLANE",
    "RECOVERY_LIMITED": "FAILURE_RECOVERY",
    "GROUND_LIMITED": "GROUND_DEPENDENCY",
    "NETWORK_LIMITED": "NETWORK",
    "JOINT_LIMITED": "JOINT_PLANNER",
}


def load_events(run_dir: Path) -> list[TraceEvent]:
    path = run_dir / "events.jsonl"
    events = []
    if not path.exists():
        return events
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            events.append(TraceEvent.from_dict(json.loads(line)))
        except Exception:
            continue
    return sorted(events, key=lambda event: (event.header.simulation_time_ns, event.header.sequence))


def latest_profile(root: Path) -> Path | None:
    profiles = root / "profiles"
    if not profiles.exists():
        return None
    runs = [path for path in profiles.iterdir() if path.is_dir() and (path / "events.jsonl").exists()]
    if not runs:
        return None
    return max(runs, key=lambda path: (path / "events.jsonl").stat().st_mtime)


class ProfileAnalyzer:
    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self.events = load_events(run_dir)
        manifest_path = run_dir / "manifest.json"
        self.manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}

    def summary(self) -> dict[str, Any]:
        categories = Counter(event.category for event in self.events)
        jobs = self._job_states()
        topology = self.topology_metrics()
        scheduler = self.scheduler_metrics()
        bottlenecks = self.bottleneck_summary()
        first = self.events[0].header.simulation_time_ns if self.events else 0
        last = self.events[-1].header.simulation_time_ns if self.events else 0
        wall_first = self.events[0].header.wall_time_ns if self.events else 0
        wall_last = self.events[-1].header.wall_time_ns if self.events else 0
        wall_s = max(0.0, (wall_last - wall_first) / 1e9)
        sim_s = max(0.0, (last - first) / 1e9)
        metrics = self._metrics()
        return {
            "run_id": self.manifest.get("run_id", self.run_dir.name),
            "scenario": self.manifest.get("scenario", "unknown"),
            "simulated_duration_s": sim_s,
            "wall_duration_s": wall_s,
            "speedup": sim_s / wall_s if wall_s else None,
            "events": {"total": len(self.events), **dict(categories)},
            "topology": topology,
            "scheduler": scheduler,
            "jobs": {
                "total": len(jobs),
                "completed": sum(1 for state in jobs.values() if state.get("completed")),
                "deadline_misses": sum(1 for state in jobs.values() if state.get("deadline_missed")),
                "migrations": sum(int(state.get("migrations", 0)) for state in jobs.values()),
            },
            "safety": {
                "energy_violations": self._count_payload("safety_type", "ENERGY_RESERVE"),
                "thermal_violations": self._count_payload("safety_type", "THERMAL_HARD_LIMIT"),
            },
            "compute": self.constellation_utilization(),
            "network": self.network_metrics(),
            "bottleneck": bottlenecks["dominant"],
            "trace": {
                "events_written": metrics.get("events_emitted", len(self.events)),
                "bytes": metrics.get("trace_bytes_written", 0),
                "profiler_overhead_ns": metrics.get("profiler_wall_overhead_ns", 0),
            },
        }

    def topology_metrics(self) -> dict[str, Any]:
        edge_added = [e for e in self.events if e.header.event_type == TraceEventType.TOPOLOGY_EDGE_ADDED.value]
        edge_removed = [e for e in self.events if e.header.event_type == TraceEventType.TOPOLOGY_EDGE_REMOVED.value]
        splits = [e for e in self.events if e.header.event_type == TraceEventType.TOPOLOGY_COMPONENT_SPLIT.value]
        merges = [e for e in self.events if e.header.event_type == TraceEventType.TOPOLOGY_COMPONENT_MERGE.value]
        epochs = [e for e in self.events if e.header.event_type == TraceEventType.TOPOLOGY_EPOCH_BEGIN.value]
        visibility_metrics = self.visibility_metrics()
        decisions = [
            e for e in self.events
            if e.header.event_type in {TraceEventType.SCHEDULER_DECISION.value, TraceEventType.SCHEDULER_REEVALUATION.value}
            and e.payload.get("trigger") == "TOPOLOGY_CHANGE"
        ]
        migrations = [e for e in self.events if e.header.event_type == TraceEventType.JOB_MIGRATION_BEGIN.value and e.payload.get("trigger") == "TOPOLOGY_CHANGE"]
        lifetime_ns = []
        created: dict[str, int] = {}
        for event in self.events:
            edge = event.payload.get("edge_id")
            if not edge:
                continue
            if event.header.event_type == TraceEventType.TOPOLOGY_EDGE_ADDED.value:
                created[edge] = event.header.simulation_time_ns
            if event.header.event_type == TraceEventType.TOPOLOGY_EDGE_REMOVED.value and edge in created:
                lifetime_ns.append(event.header.simulation_time_ns - created[edge])
        changes = len(edge_added) + len(edge_removed) + len(splits) + len(merges)
        no_op = sum(int(e.payload.get("changed") is False) for e in decisions)
        return {
            "epochs": len(epochs),
            "edges_created": len(edge_added),
            "edges_destroyed": len(edge_removed),
            "component_splits": len(splits),
            "component_merges": len(merges),
            "average_edge_lifetime_s": (sum(lifetime_ns) / len(lifetime_ns) / 1e9) if lifetime_ns else 0.0,
            "p50_edge_lifetime_s": percentile_seconds(lifetime_ns, 50),
            "p95_edge_lifetime_s": percentile_seconds(lifetime_ns, 95),
            "topology_changes": changes,
            "scheduler_reevaluations": len(decisions),
            "actual_placement_changes": sum(int(e.payload.get("selected_action", {}).get("changed", False)) for e in decisions),
            "topology_triggered_migrations": len(migrations),
            "topology_triggered_deadline_misses": self._count_payload("trigger", "TOPOLOGY_CHANGE", TraceEventType.JOB_DEADLINE_MISSED.value),
            "decision_amplification": len(decisions) / changes if changes else 0.0,
            "migration_amplification": len(migrations) / changes if changes else 0.0,
            "reevaluation_no_op_ratio": no_op / len(decisions) if decisions else 0.0,
            "visibility": visibility_metrics,
        }

    def visibility_metrics(self) -> dict[str, Any]:
        events = [e for e in self.events if e.category == "VISIBILITY" or e.header.event_type in {
            TraceEventType.LINK_GEOMETRY_AVAILABLE.value,
            TraceEventType.JOINT_PLANNER_DECISION.value,
        }]
        metrics = Counter()
        for event in events:
            payload_metrics = event.payload.get("visibility_metrics", {})
            for key, value in payload_metrics.items():
                metrics[key] += int(value)
            reason = event.payload.get("reason")
            if reason:
                metrics[str(reason).lower()] += 1
        return {
            "candidate_pairs": metrics.get("candidate_pairs", 0),
            "horizon_prefilter_rejected": metrics.get("horizon_prefilter_rejected", 0),
            "exact_occultation_tests": metrics.get("exact_occultation_tests", 0),
            "earth_occultation_rejected": metrics.get("earth_occultation_rejected", 0),
            "source_fov_rejected": metrics.get("source_fov_rejected", 0),
            "destination_fov_rejected": metrics.get("destination_fov_rejected", 0),
            "range_rejected": metrics.get("range_rejected", 0),
            "terminal_rejected": metrics.get("terminal_rejected", 0),
            "links_created": metrics.get("links_created", 0),
        }

    def network_metrics(self) -> dict[str, Any]:
        link_events = [e for e in self.events if e.category in {"COMM_LINK", "COMM_TOPOLOGY", "ACCESS_LINK"}]
        plans = [e for e in self.events if e.header.event_type == TraceEventType.TRANSFER_PLANNED.value]
        completed = [e for e in self.events if e.header.event_type == TraceEventType.TRANSFER_COMPLETED.value]
        buffered = [e for e in self.events if e.header.event_type == TraceEventType.TRANSFER_BUFFERED.value]
        reservations = [e for e in self.events if e.category == "NETWORK_RESERVATION"]
        path_kinds = Counter(str(e.payload.get("path_kind", "unknown")) for e in plans)
        transfer_bytes = sum(int(e.payload.get("bytes", 0)) for e in completed)
        peak_buffered = max([int(e.payload.get("buffered_bytes", 0)) for e in buffered] or [0])
        joint = [e for e in self.events if e.header.event_type == TraceEventType.JOINT_PLANNER_DECISION.value]
        return {
            "link_events": len(link_events),
            "transfer_plans": len(plans),
            "completed_transfers": len(completed),
            "path_kinds": dict(path_kinds),
            "transfer_bytes_completed": transfer_bytes,
            "peak_buffered_bytes": peak_buffered,
            "reservation_events": len(reservations),
            "reservation_expiries": sum(1 for e in self.events if e.header.event_type == TraceEventType.LINK_RESERVATION_EXPIRED.value),
            "network_changed_compute_placements": sum(1 for e in joint if e.payload.get("network_changed_compute_placement")),
            "deadline_misses": sum(1 for e in self.events if e.header.event_type == TraceEventType.TRANSFER_FAILED.value and e.payload.get("reason") == "DEADLINE"),
        }

    def scheduler_metrics(self) -> dict[str, Any]:
        decisions = [e for e in self.events if e.header.event_type in {TraceEventType.SCHEDULER_DECISION.value, TraceEventType.SCHEDULER_REEVALUATION.value}]
        costs = [int(e.payload.get("cost", {}).get("wall_time_ns", 0)) for e in decisions]
        rejections = Counter()
        for event in decisions:
            for candidate in event.payload.get("candidate_results", []):
                for reason in candidate.get("rejection_causes", []):
                    rejections[reason] += 1
        evaluated = sum(int(e.payload.get("cost", {}).get("candidates_evaluated", 0)) for e in decisions)
        feasible = sum(int(e.payload.get("candidates_feasible", 0)) for e in decisions)
        no_op = sum(int(e.payload.get("selected_action", {}).get("changed") is False) for e in decisions)
        return {
            "decisions": len(decisions),
            "p50_ns": percentile(costs, 50),
            "p95_ns": percentile(costs, 95),
            "p99_ns": percentile(costs, 99),
            "candidate_rejection": percent_counter(rejections),
            "candidate_discovery_efficiency": feasible / evaluated if evaluated else 0.0,
            "feasible_candidate_ratio": feasible / evaluated if evaluated else 0.0,
            "reevaluation_no_op_ratio": no_op / len(decisions) if decisions else 0.0,
        }

    def job_report(self, job_id: str) -> dict[str, Any]:
        events = [e for e in self.events if e.header.job_id == job_id]
        if not events:
            return {"job_id": job_id, "found": False}
        submitted = first_time(events, TraceEventType.JOB_SUBMITTED.value)
        completed = first_time(events, TraceEventType.JOB_COMPLETED.value)
        breakdown = Counter()
        for event in events:
            if event.header.event_type == TraceEventType.OPERATING_REGIME_EXIT.value:
                category = BOTTLENECK_LABELS.get(str(event.payload.get("regime")), "UNKNOWN")
                breakdown[category] += int(event.payload.get("duration_ns", 0))
            if event.header.event_type == TraceEventType.JOB_MIGRATION_END.value:
                breakdown["MIGRATION"] += int(event.payload.get("duration_ns", 0))
            if event.header.event_type == TraceEventType.JOB_CHECKPOINT_END.value:
                breakdown["CHECKPOINT_TRANSFER"] += int(event.payload.get("duration_ns", 0))
        scheduler_delay = sum(int(e.payload.get("cost", {}).get("wall_time_ns", 0)) for e in events if e.category == "SCHEDULER")
        if scheduler_delay:
            breakdown["SCHEDULER_DECISION"] += scheduler_delay
        total = (completed - submitted) if submitted is not None and completed is not None else sum(breakdown.values())
        ordered = breakdown.most_common()
        return {
            "job_id": job_id,
            "found": True,
            "submitted_s": submitted / 1e9 if submitted is not None else None,
            "completed_s": completed / 1e9 if completed is not None else None,
            "total_latency_s": total / 1e9 if total else None,
            "breakdown_s": {key: value / 1e9 for key, value in ordered},
            "dominant": ordered[0][0] if ordered else "UNKNOWN",
            "secondary": ordered[1][0] if len(ordered) > 1 else None,
            "topology_events_affecting_job": sum(
                1 for e in self.events
                if e.category == "TOPOLOGY" and e.header.correlation_id and e.header.correlation_id in {item.header.correlation_id for item in events}
            ),
            "migrations": sum(1 for e in events if e.header.event_type == TraceEventType.JOB_MIGRATION_BEGIN.value),
        }

    def bottleneck_summary(self) -> dict[str, Any]:
        delays = Counter()
        for event in self.events:
            if event.header.event_type == TraceEventType.OPERATING_REGIME_EXIT.value:
                delays[BOTTLENECK_LABELS.get(str(event.payload.get("regime")), "UNKNOWN")] += int(event.payload.get("duration_ns", 0))
            if event.header.event_type == TraceEventType.JOB_MIGRATION_END.value:
                delays["MIGRATION"] += int(event.payload.get("duration_ns", 0))
            if event.header.event_type == TraceEventType.JOB_CHECKPOINT_END.value:
                delays["CHECKPOINT_TRANSFER"] += int(event.payload.get("duration_ns", 0))
            if event.header.event_type == TraceEventType.TRANSFER_COMPLETED.value:
                delays["NETWORK"] += int(event.header.simulation_time_ns)
            if event.header.event_type == TraceEventType.JOINT_PLANNER_DECISION.value:
                delays["JOINT_PLANNER"] += int(event.payload.get("cost", {}).get("wall_time_ns", 0))
        if not delays:
            return {"dominant": "UNKNOWN", "percentages": {}}
        return {"dominant": delays.most_common(1)[0][0], "percentages": percent_counter(delays)}

    def constellation_utilization(self) -> dict[str, float]:
        samples = [e.payload for e in self.events if e.header.event_type == TraceEventType.NODE_OPERATING_SNAPSHOT.value]
        if not samples:
            return {
                "aggregate_compute_utilization": 0.0,
                "stranded_compute": 0.0,
                "topology_efficiency": 0.0,
                "scheduler_efficiency": 0.0,
            }
        total = sum(float(s.get("available_cpu", 0)) for s in samples)
        sched = sum(float(s.get("schedulable_compute", s.get("available_cpu", 0))) for s in samples)
        util = sum(float(s.get("cpu_utilization", 0)) for s in samples) / len(samples)
        return {
            "aggregate_compute_utilization": util,
            "total_available_compute": total,
            "schedulable_compute": sched,
            "topology_stranded_compute": max(0.0, total - sched),
            "stranded_compute": max(0.0, total - sched),
            "topology_efficiency": sched / total if total else 0.0,
            "scheduler_efficiency": util,
        }

    def timeline(self, target: str) -> list[str]:
        lines = []
        for event in self.events:
            if event.header.job_id == target or event.header.node_id == target:
                lines.append(f"T+{event.header.simulation_time_ns / 1e9:.3f}s {event.header.event_type} {event.header.node_id or ''} {event.header.job_id or ''}".strip())
        return lines

    def cause(self, event_or_job: str) -> list[str]:
        if event_or_job.startswith(self.run_dir.name):
            seed = next((e for e in self.events if e.header.event_id == event_or_job), None)
        else:
            seed = next((e for e in reversed(self.events) if e.header.job_id == event_or_job), None)
        if seed is None:
            return []
        cid = seed.header.correlation_id
        if cid:
            chain = [e for e in self.events if e.header.correlation_id == cid]
        else:
            chain = []
            current = seed
            ids = {event.header.event_id: event for event in self.events}
            while current:
                chain.append(current)
                current = ids.get(current.header.parent_event_id or "")
            chain.reverse()
        return [f"{e.header.event_type} {e.header.node_id or ''} {e.header.job_id or ''}".strip() for e in chain]

    def failures(self) -> list[dict[str, Any]]:
        return [event.to_dict() for event in self.events if event.category == "FAILURE"]

    def visibility_invariant_violations(self) -> list[dict[str, Any]]:
        occulted: dict[tuple[str | None, str | None], int] = {}
        violations: list[dict[str, Any]] = []
        for event in self.events:
            pair = (event.payload.get("source") or event.header.node_id, event.payload.get("destination"))
            if event.header.event_type == TraceEventType.EARTH_OCCULTATION_BEGIN.value:
                occulted[pair] = event.header.simulation_time_ns
            elif event.header.event_type == TraceEventType.EARTH_OCCULTATION_END.value:
                occulted.pop(pair, None)
            elif event.header.event_type == TraceEventType.LINK_ACTIVE.value and pair in occulted:
                violations.append({
                    "event_id": event.header.event_id,
                    "source": pair[0],
                    "destination": pair[1],
                    "occultation_begin_ns": occulted[pair],
                    "link_active_ns": event.header.simulation_time_ns,
                })
        return violations

    def export_perfetto(self, output: Path, *, time_axis: str = "wall") -> None:
        trace_events = []
        for event in self.events:
            ts = event.header.simulation_time_ns / 1000 if time_axis == "simulation" else event.header.wall_time_ns / 1000
            dur = event.payload.get("duration_ns")
            trace_events.append({
                "name": event.header.event_type,
                "cat": event.category,
                "ph": "X" if dur else "i",
                "ts": ts,
                "dur": int(dur) / 1000 if dur else 0,
                "pid": event.header.run_id,
                "tid": event.header.node_id or event.header.job_id or event.category,
                "args": event.payload,
                "s": "t",
            })
        output.write_text(json.dumps({"traceEvents": trace_events}, indent=2, sort_keys=True), encoding="utf-8")

    def export_node_csv(self, node_id: str, output: Path) -> None:
        rows = [e for e in self.events if e.header.node_id == node_id and e.header.event_type == TraceEventType.NODE_OPERATING_SNAPSHOT.value]
        with output.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=["simulation_time", "soc", "power_w", "temperature_c", "thermal_headroom", "compute_utilization", "queue_length", "active_jobs", "component_id"])
            writer.writeheader()
            for event in rows:
                writer.writerow({key: event.payload.get(key, "") for key in writer.fieldnames})

    def export_job_csv(self, job_id: str, output: Path) -> None:
        rows = [e for e in self.events if e.header.job_id == job_id]
        with output.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=["time", "node", "state", "progress", "remaining_work", "predicted_finish", "soc_margin", "thermal_margin", "connectivity_margin"])
            writer.writeheader()
            for event in rows:
                writer.writerow({
                    "time": event.header.simulation_time_ns,
                    "node": event.header.node_id or "",
                    "state": event.header.event_type,
                    "progress": event.payload.get("progress", ""),
                    "remaining_work": event.payload.get("remaining_work_s", ""),
                    "predicted_finish": event.payload.get("predicted_finish", ""),
                    "soc_margin": event.payload.get("soc_margin", ""),
                    "thermal_margin": event.payload.get("thermal_margin", ""),
                    "connectivity_margin": event.payload.get("connectivity_margin", ""),
                })

    def _job_states(self) -> dict[str, dict[str, Any]]:
        jobs: dict[str, dict[str, Any]] = defaultdict(dict)
        for event in self.events:
            job = event.header.job_id
            if not job:
                continue
            if event.header.event_type == TraceEventType.JOB_COMPLETED.value:
                jobs[job]["completed"] = True
            if event.header.event_type == TraceEventType.JOB_DEADLINE_MISSED.value:
                jobs[job]["deadline_missed"] = True
            if event.header.event_type == TraceEventType.JOB_MIGRATION_BEGIN.value:
                jobs[job]["migrations"] = int(jobs[job].get("migrations", 0)) + 1
        return jobs

    def _metrics(self) -> dict[str, Any]:
        path = self.run_dir / "metrics.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def _count_payload(self, key: str, value: Any, event_type: str | None = None) -> int:
        return sum(1 for event in self.events if (event_type is None or event.header.event_type == event_type) and event.payload.get(key) == value)


def first_time(events: list[TraceEvent], event_type: str) -> int | None:
    for event in events:
        if event.header.event_type == event_type:
            return event.header.simulation_time_ns
    return None


def percentile(values: list[int], pct: int) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((pct / 100) * (len(ordered) - 1)))
    return int(ordered[index])


def percentile_seconds(values: list[int], pct: int) -> float:
    return percentile(values, pct) / 1e9


def percent_counter(counter: Counter) -> dict[str, float]:
    total = sum(counter.values())
    if not total:
        return {}
    return {str(key): round(value * 100.0 / total, 3) for key, value in counter.most_common()}
