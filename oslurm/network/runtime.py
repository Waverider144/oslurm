from __future__ import annotations

from pathlib import Path
from typing import Any
import heapq
import itertools
import json
import math
import time

from ..profile.recorder import FlightRecorder
from ..profile.schema import TraceEventType
from ..visibility import AnalyticEllipsoidVisibilityProvider, TerminalFov, VisibilityQuery
from .joint import ComputeCandidate, JointComputeNetworkPlanner, JointDecision
from .models import BufferState, Constellation, ContactWindow, LinkKind, NetworkDomain, TransferIntent, TransferPlan
from .service import NetworkPlanningService


class MultiConstellationRuntime:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.constellations: dict[str, Constellation] = {}
        self.network = NetworkPlanningService()
        self.transfers: dict[str, TransferPlan] = {}
        self.last_decision: JointDecision | None = None
        self.now_s = 0.0
        self.connected: tuple[str, str] | None = None
        self.visibility = AnalyticEllipsoidVisibilityProvider(strict=True)
        self.positions_eci_m = _default_positions()
        self.jobs: dict[str, dict[str, Any]] = {}
        self.compute_profiles: dict[str, dict[str, Any]] = {}
        self.contact_metadata: dict[str, Any] = {}
        self.compute_available_at: dict[str, float] = {}
        self._pending_events: list[tuple] = []
        self._event_ids = itertools.count()

    def load_constellation(self, domain: str, path: str) -> str:
        file_path = Path(path)
        if not file_path.is_absolute():
            file_path = self.root / file_path
        data = _read_simple_yaml(file_path)
        constellation_id = str(data.get("constellation_id") or file_path.stem)
        nodes = [str(item) for item in data.get("nodes", [])]
        if not nodes:
            nodes = _default_nodes(domain)
        enum_domain = NetworkDomain(domain)
        profiles = {}
        if enum_domain == NetworkDomain.COMPUTE:
            profile_path = data.get("compute_profiles")
            if not profile_path:
                raise ValueError("compute constellation requires compute_profiles JSON path")
            profiles = json.loads((file_path.parent / str(profile_path)).read_text(encoding="utf-8"))
            if not isinstance(profiles, dict) or any(not isinstance(p, dict) for p in profiles.values()):
                raise ValueError("compute profiles must map node IDs to profile objects")
            if any(node not in profiles for node in nodes):
                raise ValueError("each compute node needs an explicit compute profile")
            if any(node in self.compute_available_at for node in nodes):
                raise ValueError("cannot reload compute nodes with scheduled jobs")
        self.constellations[constellation_id] = Constellation(constellation_id, enum_domain, nodes, data)
        self.compute_profiles.update(profiles)
        for node in nodes:
            if node not in self.network.buffers:
                self.network.set_buffer(node, BufferState(int(data.get("buffer_capacity_bytes", 128_000_000))))
        self._install_default_contacts()
        return f"loaded {domain} constellation {constellation_id} nodes={','.join(nodes)}"

    def connect(self, compute_id: str, comm_id: str) -> str:
        if compute_id not in self.constellations:
            return f"missing compute constellation {compute_id}"
        if comm_id not in self.constellations:
            return f"missing comm constellation {comm_id}"
        if (self.constellations[compute_id].domain != NetworkDomain.COMPUTE
                or self.constellations[comm_id].domain != NetworkDomain.COMM):
            raise ValueError("connect requires a compute constellation and a comm constellation")
        self.connected = (compute_id, comm_id)
        self._install_default_contacts()
        return f"connected constellations {compute_id} <-> {comm_id}"

    def submit_job(self, path: str, recorder: FlightRecorder | None) -> str:
        job = _read_simple_yaml(self.root / path if not Path(path).is_absolute() else Path(path))
        return self.submit_spec(job, recorder)

    def submit_spec(self, job: dict[str, Any], recorder: FlightRecorder | None, *,
                    schedule: bool = True, execution_mode: str = "modeled_compute_and_radio") -> str:
        if self.connected is None:
            raise ValueError("connect compute and comm constellations before submitting a job")
        job_id = str(job.get("job_id", "JOB001"))
        if job_id in self.jobs:
            raise ValueError(f"duplicate job ID {job_id}")
        input_source = str(job.get("input_source", "ground:MISSION-CONTROL"))
        result_destination = str(job.get("result_destination", "ground:MISSION-CONTROL"))
        deadline_s = self.now_s + _duration_s(str(job.get("deadline", "2h")))
        input_bytes = int(job.get("input_bytes", 24_000_000))
        result_bytes = int(job.get("result_bytes", 8_000_000))
        planner = JointComputeNetworkPlanner(self.network)
        candidates = []
        for node in self.constellations[self.connected[0]].nodes:
            profile = self.compute_profiles[node]
            causes = []
            current_soc = float(profile.get("soc", 1.0))
            predicted_soc = float(profile.get("predicted_min_soc", current_soc))
            current_temperature = float(profile.get("temperature_c", 20.0))
            predicted_temperature = float(profile.get("predicted_max_temperature_c", current_temperature))
            reserve = float(profile.get("reserve_soc", 0.30))
            thermal_limit = float(profile.get("thermal_limit_c", 70.0))
            if (not all(math.isfinite(v) for v in (current_soc, predicted_soc, current_temperature,
                                                  predicted_temperature, reserve, thermal_limit))
                    or not all(0 <= v <= 1 for v in (current_soc, predicted_soc, reserve))):
                raise ValueError(f"invalid resource profile for {node}")
            if min(current_soc, predicted_soc) < reserve:
                causes.append("POWER_RESERVE")
            if max(current_temperature, predicted_temperature) > thermal_limit:
                causes.append("THERMAL_LIMIT")
            candidates.append(ComputeCandidate(node, float(profile["compute_time_s"]), input_source,
                result_destination, input_bytes, result_bytes,
                max(float(profile.get("available_at_s", 0)), self.compute_available_at.get(node, 0)), tuple(causes)))
        started = time.perf_counter_ns()
        decision = planner.choose(job_id, candidates, now_s=self.now_s, deadline_s=deadline_s)
        self.network.reserve_plans([decision.input_plan, decision.result_plan], now_s=self.now_s, commit=True)
        planner_wall_ns = time.perf_counter_ns() - started
        self.last_decision = decision
        self.transfers[decision.input_plan.transfer_id] = decision.input_plan
        self.transfers[decision.result_plan.transfer_id] = decision.result_plan
        self.compute_available_at[decision.selected_node] = decision.compute_finish_s
        self.jobs[job_id] = {"decision": decision, "state": "input_pending"}
        if schedule:
            self._schedule_decision(decision)
        if recorder:
            cid = job_id
            for contact in self.network.contacts:
                recorder.emit(TraceEventType.LINK_GEOMETRY_AVAILABLE, _ns(self.now_s), node_id=contact.source, correlation_id=cid, payload={
                    "contact_id": contact.contact_id,
                    "source": contact.source,
                    "destination": contact.destination,
                    "bandwidth_bps": contact.bandwidth_bps,
                    "confidence": contact.confidence,
                    "start_s": contact.start_s,
                    "end_s": contact.end_s,
                })
            recorder.emit(TraceEventType.JOB_SUBMITTED, _ns(self.now_s), job_id=job_id, correlation_id=cid, payload={"input_bytes": input_bytes, "result_bytes": result_bytes})
            recorder.emit(TraceEventType.TRANSFER_SUBMITTED, _ns(self.now_s), job_id=job_id, correlation_id=cid, payload={"transfer_id": decision.input_plan.transfer_id, "source": input_source, "destination": decision.selected_node})
            recorder.emit(TraceEventType.TRANSFER_PLANNED, _ns(self.now_s), job_id=job_id, correlation_id=cid, payload=decision.input_plan.as_dict())
            recorder.emit(TraceEventType.TRANSFER_PLANNED, _ns(self.now_s), job_id=job_id, correlation_id=cid, payload=decision.result_plan.as_dict())
            self._record_reservations([decision.input_plan, decision.result_plan], recorder, job_id)
            recorder.emit(TraceEventType.JOINT_PLANNER_DECISION, _ns(self.now_s), job_id=job_id, node_id=decision.selected_node, correlation_id=cid, payload={
                "selected_node": decision.selected_node,
                "candidate_results": decision.candidate_reports,
                "rationale": decision.rationale,
                "network_changed_compute_placement": decision.selected_node != decision.compute_only_node,
                "compute_only_node": decision.compute_only_node,
                "compute_start_s": decision.compute_start_s,
                "compute_finish_s": decision.compute_finish_s,
                "execution_mode": execution_mode,
                "visibility_metrics": self.contact_metadata.get("metrics", self.visibility.metrics.as_dict()),
                "cost": {"wall_time_ns": planner_wall_ns, "candidates_evaluated": len(decision.candidate_reports)},
            })
            recorder.emit(TraceEventType.SCHEDULER_DECISION, _ns(self.now_s), job_id=job_id, node_id=decision.selected_node, correlation_id=cid, payload={
                "trigger": "JOINT_NETWORK_PLANNING",
                "selected_action": {"node_id": decision.selected_node, "changed": True},
                "candidates_feasible": sum(1 for r in decision.candidate_reports if r.get("feasible")),
                "candidate_results": decision.candidate_reports,
                "cost": {"wall_time_ns": planner_wall_ns, "candidates_evaluated": len(decision.candidate_reports)},
            })
        return f"submitted {job_id} selected={decision.selected_node} finish={decision.total_finish_s:.1f}s"

    def run(self, duration: str, recorder: FlightRecorder | None) -> str:
        end_s = self.now_s + _duration_s(duration)
        if not math.isfinite(end_s) or end_s < self.now_s:
            raise ValueError("run duration must be finite and non-negative")
        while self._pending_events and self._pending_events[0][0] <= end_s:
            at_s, _, event_type, job_id, node_id, payload = heapq.heappop(self._pending_events)
            if event_type == TraceEventType.TRANSFER_COMPLETED:
                plan = self.transfers[payload["transfer_id"]]
                self.network.complete_plan(plan, now_s=at_s)
                if recorder:
                    for reservation in self.network.reservations.values():
                        if reservation.transfer_id == plan.transfer_id:
                            recorder.emit(TraceEventType.LINK_RESERVATION_COMPLETED, _ns(at_s), job_id=job_id,
                                          correlation_id=job_id, payload={"reservation_id": reservation.reservation_id,
                                          "transfer_id": plan.transfer_id, "state": reservation.state.value})
            if job_id in self.jobs:
                state = {TraceEventType.JOB_STARTED: "computing", TraceEventType.COMPUTE_COMPLETED: "result_pending",
                         TraceEventType.MISSION_JOB_COMPLETED: "completed"}.get(event_type)
                if state:
                    self.jobs[job_id]["state"] = state
            if recorder:
                recorder.emit(event_type, _ns(at_s), job_id=job_id, node_id=node_id,
                              correlation_id=job_id, payload=payload)
        expired = self.network.expire(end_s)
        for reservation in expired:
            if recorder:
                recorder.emit(TraceEventType.LINK_RESERVATION_EXPIRED, _ns(end_s), payload={"reservation_id": reservation.reservation_id, "transfer_id": reservation.transfer_id})
        self.now_s = end_s
        return f"advanced network runtime to T+{self.now_s:.1f}s transfers={len(self.transfers)}"

    def _enqueue(self, at_s: float, event_type: TraceEventType, job_id: str | None,
                 node_id: str | None = None, payload: dict | None = None) -> None:
        heapq.heappush(self._pending_events, (at_s, next(self._event_ids), event_type, job_id, node_id, payload or {}))

    def _record_reservations(self, plans: list[TransferPlan], recorder: FlightRecorder,
                             job_id: str | None) -> None:
        transfer_ids = {p.transfer_id for p in plans}
        for reservation in self.network.reservations.values():
            if reservation.transfer_id not in transfer_ids:
                continue
            for event_type, state in ((TraceEventType.LINK_RESERVATION_CREATED, "accepted"),
                                      (TraceEventType.LINK_RESERVATION_COMMITTED, "committed")):
                recorder.emit(event_type, _ns(self.now_s), job_id=job_id, correlation_id=job_id, payload={
                    "reservation_id": reservation.reservation_id, "transfer_id": reservation.transfer_id,
                    "source": reservation.hop.source, "destination": reservation.hop.destination, "state": state})

    def _schedule_transfer(self, plan: TransferPlan, job_id: str | None) -> None:
        self._enqueue(plan.hops[0].start_s, TraceEventType.TRANSFER_STARTED, job_id,
                      payload={"transfer_id": plan.transfer_id, "path_kind": plan.path_kind.value})
        for index, hop in enumerate(plan.hops):
            self._enqueue(hop.start_s, TraceEventType.TRANSFER_HOP_BEGIN, job_id, hop.source,
                          {"transfer_id": plan.transfer_id, "contact_id": hop.contact_id,
                           "destination": hop.destination, "bytes": hop.reserved_bytes})
            self._enqueue(hop.end_s, TraceEventType.TRANSFER_HOP_END, job_id, hop.destination,
                          {"transfer_id": plan.transfer_id, "contact_id": hop.contact_id})
            if index < len(plan.hops) - 1:
                self._enqueue(hop.end_s, TraceEventType.TRANSFER_BUFFERED, job_id, hop.destination,
                              {"transfer_id": plan.transfer_id, "buffered_bytes": hop.reserved_bytes})
        self._enqueue(plan.predicted_finish_s, TraceEventType.TRANSFER_COMPLETED, job_id,
                      payload={"transfer_id": plan.transfer_id, "bytes": plan.hops[-1].reserved_bytes})

    def _schedule_decision(self, decision: JointDecision) -> None:
        self._schedule_transfer(decision.input_plan, decision.job_id)
        self._enqueue(decision.compute_start_s, TraceEventType.JOB_STARTED, decision.job_id, decision.selected_node)
        self._enqueue(decision.compute_finish_s, TraceEventType.COMPUTE_COMPLETED, decision.job_id, decision.selected_node)
        self._schedule_transfer(decision.result_plan, decision.job_id)
        for event_type in (TraceEventType.MISSION_JOB_COMPLETED, TraceEventType.JOB_COMPLETED):
            self._enqueue(decision.total_finish_s, event_type, decision.job_id, decision.selected_node)

    def show_jobs(self) -> str:
        return "\n".join(f"{job_id}: {job['state']} node={job['decision'].selected_node} "
                         f"compute={job['decision'].compute_start_s:.1f}-{job['decision'].compute_finish_s:.1f}s "
                         f"delivery={job['decision'].total_finish_s:.1f}s"
                         for job_id, job in self.jobs.items()) or "no jobs"

    def show_constellations(self) -> str:
        if not self.constellations:
            return "no constellations loaded"
        return "\n".join(f"{item.constellation_id}: {item.domain.value} nodes={','.join(item.nodes)}" for item in self.constellations.values())

    def show_network(self, domain: str | None = None) -> str:
        contacts = self.network.contacts
        if domain:
            contacts = [c for c in contacts if domain in c.kind.value]
        if not contacts:
            return "network contacts: empty"
        return "\n".join(f"{c.contact_id}: {c.source}->{c.destination} T+{c.start_s:.0f}-{c.end_s:.0f}s {c.bandwidth_bps}bps" for c in contacts[:20])

    def show_contacts(self, node: str) -> str:
        contacts = [c for c in self.network.contacts if c.source == node or c.destination == node]
        return "\n".join(f"{c.contact_id}: {c.source}->{c.destination} T+{c.start_s:.0f}-{c.end_s:.0f}s" for c in contacts) or f"no contacts for {node}"

    def show_transfers(self) -> str:
        if not self.transfers:
            return "no transfers"
        return "\n".join(f"{plan.transfer_id}: {plan.path_kind.value} finish={plan.predicted_finish_s:.1f}s node={plan.selected_for_compute_node or '-'}" for plan in self.transfers.values())

    def show_reservations(self) -> str:
        if not self.network.reservations:
            return "no reservations"
        return "\n".join(f"{r.reservation_id}: {r.transfer_id} {r.hop.source}->{r.hop.destination} {r.state.value}" for r in self.network.reservations.values())

    def visibility_check(self, source: str, destination: str) -> str:
        query = self._visibility_query(_canonical_node(source), _canonical_node(destination))
        result = self.visibility.evaluate(query)
        source_fov = _format_fov(result.source_fov_ok, result.source_fov_margin_rad, query.require_source_fov)
        destination_fov = _format_fov(result.destination_fov_ok, result.destination_fov_margin_rad, query.require_destination_fov)
        return "\n".join([
            f"SOURCE: {_canonical_node(source)}",
            f"DESTINATION: {_canonical_node(destination)}",
            "",
            "Earth LOS:",
            "CLEAR" if not result.earth_occulted else "BLOCKED",
            "",
            "Earth limb clearance:",
            f"{(result.limb_clearance_m or 0.0) / 1000.0:.3f} km",
            "",
            "Fidelity:",
            result.fidelity,
            "",
            "Source FOV:",
            source_fov,
            "",
            "Destination FOV:",
            destination_fov,
            "",
            "FINAL:",
            "VISIBLE" if result.geometrically_visible else "NOT VISIBLE",
            "",
            "Reason:",
            result.reason.value,
        ])

    def explain_link(self, source: str, destination: str) -> str:
        query = self._visibility_query(_canonical_node(source), _canonical_node(destination))
        result = self.visibility.evaluate(query)
        lines = [
            "Candidate rejected:" if not result.geometrically_visible else "Candidate accepted:",
            "",
            f"1. Earth occultation: {'FAIL' if result.earth_occulted else 'PASS'}",
            f"2. Source FOV: {_stage(result.source_fov_ok, query.require_source_fov)}",
            f"3. Destination FOV: {_stage(result.destination_fov_ok, query.require_destination_fov)}",
            f"4. Range: {'evaluated' if result.geometrically_visible else 'not evaluated'}",
            f"5. Terminal capability: {'evaluated' if result.geometrically_visible else 'not evaluated'}",
        ]
        return "\n".join(lines)

    def transfer_submit(self, args: list[str], recorder: FlightRecorder | None) -> str:
        if len(args) < 3:
            return "usage: transfer submit <source> <destination> <bytes>"
        transfer_id = f"XFER{len(self.transfers) + 1:03d}"
        intent = TransferIntent(transfer_id, args[0], args[1], int(args[2]), self.now_s, self.now_s + _duration_s("2h"))
        plans = self.network.plan_transfer(intent)
        if not plans:
            return f"transfer {transfer_id} no route"
        plan = plans[0]
        self.network.reserve_plans([plan], now_s=self.now_s, commit=True)
        self.transfers[transfer_id] = plan
        self._schedule_transfer(plan, None)
        if recorder:
            recorder.emit(TraceEventType.TRANSFER_PLANNED, _ns(self.now_s), payload=plan.as_dict())
            self._record_reservations([plan], recorder, None)
        return f"transfer {transfer_id} planned {plan.path_kind.value} finish={plan.predicted_finish_s:.1f}s"

    def _install_default_contacts(self) -> None:
        if self.network.contacts:
            return
        specs = [
            ("GROUND-SAT001-SLOW", "ground:MISSION-CONTROL", "compute:SAT001", 30, 1200, 2_000_000, 40_000_000, 120, 0.93, 0.75, LinkKind.COMPUTE_TO_GROUND),
            ("SAT001-GROUND-SLOW", "compute:SAT001", "ground:MISSION-CONTROL", 260, 1400, 2_000_000, 40_000_000, 120, 0.93, 0.75, LinkKind.COMPUTE_TO_GROUND),
            ("GROUND-RELAY-A", "ground:MISSION-CONTROL", "comm:RELAY-A", 0, 1600, 30_000_000, 300_000_000, 80, 0.99, 0.9, LinkKind.ACCESS),
            ("RELAY-A-SAT003", "comm:RELAY-A", "compute:SAT003", 40, 1600, 25_000_000, 250_000_000, 60, 0.98, 0.86, LinkKind.COMPUTE_TO_COMM),
            ("SAT003-RELAY-A", "compute:SAT003", "comm:RELAY-A", 270, 1900, 25_000_000, 250_000_000, 60, 0.98, 0.86, LinkKind.COMPUTE_TO_COMM),
            ("RELAY-A-GROUND", "comm:RELAY-A", "ground:MISSION-CONTROL", 275, 2000, 30_000_000, 300_000_000, 80, 0.99, 0.9, LinkKind.ACCESS),
            ("GROUND-RELAY-B", "ground:MISSION-CONTROL", "comm:RELAY-B", 15, 1500, 28_000_000, 280_000_000, 82, 0.99, 0.9, LinkKind.ACCESS),
            ("RELAY-B-SAT002", "comm:RELAY-B", "compute:SAT002", 55, 1500, 24_000_000, 240_000_000, 62, 0.98, 0.86, LinkKind.COMPUTE_TO_COMM),
            ("SAT002-RELAY-B", "compute:SAT002", "comm:RELAY-B", 255, 1800, 24_000_000, 240_000_000, 62, 0.98, 0.86, LinkKind.COMPUTE_TO_COMM),
            ("RELAY-B-GROUND", "comm:RELAY-B", "ground:MISSION-CONTROL", 265, 1950, 28_000_000, 280_000_000, 82, 0.99, 0.9, LinkKind.ACCESS),
        ]
        contacts = [contact for spec in specs if (contact := self._build_contact(*spec)) is not None]
        self.network.add_contacts(contacts)
        self.network.set_buffer("comm:RELAY-A", BufferState(512_000_000))
        self.network.set_buffer("comm:RELAY-B", BufferState(512_000_000))

    def _build_contact(self, contact_id: str, source: str, destination: str, start_s: float, end_s: float, bandwidth_bps: int, bytes_: int, latency_ms: float, survival: float, confidence: float, kind: LinkKind) -> ContactWindow | None:
        query = self._visibility_query(source, destination)
        result = self.visibility.evaluate(query)
        if not result.geometrically_visible:
            return None
        return ContactWindow(contact_id, source, destination, start_s, end_s, bandwidth_bps, bytes_, latency_ms, survival, confidence, kind,
                             source_terminal="radio0", destination_terminal="radio0", visibility=result)

    def _visibility_query(self, source: str, destination: str) -> VisibilityQuery:
        source = _canonical_node(source)
        destination = _canonical_node(destination)
        return VisibilityQuery(
            source_id=source,
            destination_id=destination,
            source_position_eci_m=self.positions_eci_m.get(source),
            destination_position_eci_m=self.positions_eci_m.get(destination),
            require_source_fov=source in _FOV_TERMINALS,
            require_destination_fov=destination in _FOV_TERMINALS,
            source_terminal=_FOV_TERMINALS.get(source),
            destination_terminal=_FOV_TERMINALS.get(destination),
        )


def _default_nodes(domain: str) -> list[str]:
    if domain == "compute":
        return ["compute:SAT001", "compute:SAT002", "compute:SAT003", "compute:SAT004"]
    if domain == "comm":
        return ["comm:RELAY-A", "comm:RELAY-B"]
    return ["ground:MISSION-CONTROL"]


def _default_positions() -> dict[str, tuple[float, float, float]]:
    r = 6_371_000.0
    return {
        "compute:SAT001": (r + 550_000.0, 0.0, 0.0),
        "compute:SAT002": (r + 550_000.0, 850_000.0, 0.0),
        "compute:SAT003": (0.0, r + 650_000.0, 0.0),
        "compute:SAT004": (0.0, 0.0, r + 650_000.0),
        "comm:RELAY-A": (0.0, r + 1_200_000.0, 250_000.0),
        "comm:RELAY-B": (4_500_000.0, r + 1_600_000.0, 500_000.0),
        "comm:R1": (r + 1_000_000.0, 0.0, 0.0),
        "comm:R2": (r + 1_000_000.0, 500_000.0, 0.0),
        "comm:R3": (0.0, r + 1_000_000.0, 0.0),
        "comm:R4": (-(r + 1_000_000.0), 0.0, 0.0),
        "compute:SAT-A": (r + 700_000.0, 0.0, 0.0),
        "compute:SAT-B": (r + 700_000.0, 500_000.0, 0.0),
        "compute:SAT-C": (-(r + 700_000.0), 0.0, 0.0),
        "compute:SAT-D": (r + 700_000.0, 600_000.0, 0.0),
        "comm:R2": (r + 900_000.0, 400_000.0, 0.0),
        "ground:MISSION-CONTROL": (0.0, r, 0.0),
        "ground:GS1": (6_371_000.0, 0.0, 0.0),
    }


_IDENTITY = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
_FOV_TERMINALS = {
    "compute:SAT-D": TerminalFov("fov-away", boresight_body=(-1.0, 0.0, 0.0), cone_half_angle_rad=0.5, require_pointing=True, body_to_inertial=_IDENTITY),
    "comm:R2": TerminalFov("relay-cone", boresight_body=(1.0, 0.0, 0.0), cone_half_angle_rad=1.3, require_pointing=True, body_to_inertial=_IDENTITY),
}


def _canonical_node(value: str) -> str:
    normalized = value.replace("/", ":")
    if ":" in normalized:
        domain, name = normalized.split(":", 1)
        return f"{domain.lower()}:{name}"
    if normalized.upper().startswith("SAT"):
        return f"compute:{normalized}"
    if normalized.upper().startswith("R"):
        return f"comm:{normalized}"
    if normalized.upper().startswith("GS"):
        return f"ground:{normalized}"
    return normalized


def _format_fov(ok: bool, margin: float | None, required: bool) -> str:
    if not required:
        return "N/A"
    text = "PASS" if ok else "FAIL"
    if margin is not None:
        text += f"\nmargin={margin * 180.0 / 3.141592653589793:.2f} deg"
    return text


def _stage(ok: bool, required: bool) -> str:
    if not required:
        return "N/A"
    return "PASS" if ok else "FAIL"


def _duration_s(value: str) -> float:
    stripped = value.strip().lower()
    if stripped.endswith("ms"):
        return float(stripped[:-2]) / 1000.0
    if stripped.endswith("h"):
        return float(stripped[:-1]) * 3600.0
    if stripped.endswith("m"):
        return float(stripped[:-1]) * 60.0
    if stripped.endswith("s"):
        return float(stripped[:-1])
    return float(stripped)


def _ns(seconds: float) -> int:
    return int(seconds * 1_000_000_000)


def _read_simple_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    data: dict[str, Any] = {}
    current_list: str | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line:
            continue
        if line.startswith("  - ") and current_list:
            data.setdefault(current_list, []).append(line[4:].strip().strip('"'))
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip().strip('"')
        if value == "":
            current_list = key
            data[current_list] = []
            continue
        current_list = None
        if value.isdigit():
            data[key] = int(value)
        else:
            data[key] = value
    return data
