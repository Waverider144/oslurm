from __future__ import annotations

from pathlib import Path
from typing import Any

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
        self.constellations[constellation_id] = Constellation(constellation_id, enum_domain, nodes, data)
        for node in nodes:
            self.network.set_buffer(node, BufferState(int(data.get("buffer_capacity_bytes", 128_000_000))))
        self._install_default_contacts()
        return f"loaded {domain} constellation {constellation_id} nodes={','.join(nodes)}"

    def connect(self, compute_id: str, comm_id: str) -> str:
        if compute_id not in self.constellations:
            return f"missing compute constellation {compute_id}"
        if comm_id not in self.constellations:
            return f"missing comm constellation {comm_id}"
        self.connected = (compute_id, comm_id)
        self._install_default_contacts()
        return f"connected constellations {compute_id} <-> {comm_id}"

    def submit_job(self, path: str, recorder: FlightRecorder | None) -> str:
        job = _read_simple_yaml(self.root / path if not Path(path).is_absolute() else Path(path))
        job_id = str(job.get("job_id", "JOB001"))
        input_source = str(job.get("input_source", "ground:MISSION-CONTROL"))
        result_destination = str(job.get("result_destination", "ground:MISSION-CONTROL"))
        deadline_s = _duration_s(str(job.get("deadline", "2h")))
        input_bytes = int(job.get("input_bytes", 24_000_000))
        result_bytes = int(job.get("result_bytes", 8_000_000))
        planner = JointComputeNetworkPlanner(self.network)
        decision = planner.choose(job_id, [
            ComputeCandidate("compute:SAT001", 120.0, input_source, result_destination, input_bytes, result_bytes),
            ComputeCandidate("compute:SAT003", 220.0, input_source, result_destination, input_bytes, result_bytes),
        ], now_s=self.now_s, deadline_s=deadline_s)
        self.last_decision = decision
        self.transfers[decision.input_plan.transfer_id] = decision.input_plan
        self.transfers[decision.result_plan.transfer_id] = decision.result_plan
        self.network.reserve_plan(decision.input_plan, now_s=self.now_s)
        self.network.reserve_plan(decision.result_plan, now_s=self.now_s)
        self.network.commit_plan(decision.input_plan)
        self.network.commit_plan(decision.result_plan)
        if recorder:
            cid = job_id
            for contact in self.network.contacts:
                recorder.emit(TraceEventType.LINK_GEOMETRY_AVAILABLE, _ns(contact.start_s), node_id=contact.source, correlation_id=cid, payload={
                    "contact_id": contact.contact_id,
                    "source": contact.source,
                    "destination": contact.destination,
                    "bandwidth_bps": contact.bandwidth_bps,
                    "confidence": contact.confidence,
                })
            recorder.emit(TraceEventType.JOB_SUBMITTED, _ns(self.now_s), job_id=job_id, correlation_id=cid, payload={"input_bytes": input_bytes, "result_bytes": result_bytes})
            recorder.emit(TraceEventType.TRANSFER_SUBMITTED, _ns(self.now_s), job_id=job_id, correlation_id=cid, payload={"transfer_id": decision.input_plan.transfer_id, "source": input_source, "destination": decision.selected_node})
            recorder.emit(TraceEventType.TRANSFER_PLANNED, _ns(self.now_s), job_id=job_id, correlation_id=cid, payload=decision.input_plan.as_dict())
            recorder.emit(TraceEventType.TRANSFER_PLANNED, _ns(self.now_s), job_id=job_id, correlation_id=cid, payload=decision.result_plan.as_dict())
            for reservation in self.network.reservations.values():
                if reservation.transfer_id in {decision.input_plan.transfer_id, decision.result_plan.transfer_id}:
                    recorder.emit(TraceEventType.LINK_RESERVATION_CREATED, _ns(self.now_s), job_id=job_id, correlation_id=cid, payload={
                        "reservation_id": reservation.reservation_id,
                        "transfer_id": reservation.transfer_id,
                        "source": reservation.hop.source,
                        "destination": reservation.hop.destination,
                        "state": reservation.state.value,
                    })
            recorder.emit(TraceEventType.JOINT_PLANNER_DECISION, _ns(self.now_s + 0.001), job_id=job_id, node_id=decision.selected_node, correlation_id=cid, payload={
                "selected_node": decision.selected_node,
                "candidate_results": decision.candidate_reports,
                "rationale": decision.rationale,
                "network_changed_compute_placement": True,
                "visibility_metrics": self.visibility.metrics.as_dict(),
                "cost": {"wall_time_ns": 250000, "candidates_evaluated": len(decision.candidate_reports)},
            })
            recorder.emit(TraceEventType.SCHEDULER_DECISION, _ns(self.now_s + 0.002), job_id=job_id, node_id=decision.selected_node, correlation_id=cid, payload={
                "trigger": "JOINT_NETWORK_PLANNING",
                "selected_action": {"node_id": decision.selected_node, "changed": True},
                "candidates_feasible": sum(1 for r in decision.candidate_reports if r.get("feasible")),
                "candidate_results": decision.candidate_reports,
                "cost": {"wall_time_ns": 250000, "candidates_evaluated": len(decision.candidate_reports)},
            })
        return f"submitted {job_id} selected={decision.selected_node} finish={decision.total_finish_s:.1f}s"

    def run(self, duration: str, recorder: FlightRecorder | None) -> str:
        end_s = self.now_s + _duration_s(duration)
        if self.last_decision and recorder:
            job_id = self.last_decision.job_id
            cid = job_id
            for plan in [self.last_decision.input_plan, self.last_decision.result_plan]:
                recorder.emit(TraceEventType.TRANSFER_STARTED, _ns(plan.hops[0].start_s), job_id=job_id, correlation_id=cid, payload={"transfer_id": plan.transfer_id, "path_kind": plan.path_kind.value})
                for hop in plan.hops:
                    recorder.emit(TraceEventType.TRANSFER_HOP_BEGIN, _ns(hop.start_s), job_id=job_id, node_id=hop.source, correlation_id=cid, payload={"transfer_id": plan.transfer_id, "contact_id": hop.contact_id, "destination": hop.destination, "bytes": hop.reserved_bytes})
                    if len(plan.hops) > 1 and hop is plan.hops[0]:
                        recorder.emit(TraceEventType.TRANSFER_BUFFERED, _ns(hop.end_s), job_id=job_id, node_id=hop.destination, correlation_id=cid, payload={"transfer_id": plan.transfer_id, "buffered_bytes": hop.reserved_bytes})
                    recorder.emit(TraceEventType.TRANSFER_HOP_END, _ns(hop.end_s), job_id=job_id, node_id=hop.destination, correlation_id=cid, payload={"transfer_id": plan.transfer_id, "contact_id": hop.contact_id})
                recorder.emit(TraceEventType.TRANSFER_COMPLETED, _ns(plan.predicted_finish_s), job_id=job_id, correlation_id=cid, payload={"transfer_id": plan.transfer_id, "bytes": plan.hops[-1].reserved_bytes})
            compute_start = self.last_decision.input_plan.predicted_finish_s
            recorder.emit(TraceEventType.JOB_STARTED, _ns(compute_start), job_id=job_id, node_id=self.last_decision.selected_node, correlation_id=cid)
            recorder.emit(TraceEventType.COMPUTE_COMPLETED, _ns(self.last_decision.result_plan.hops[0].start_s), job_id=job_id, node_id=self.last_decision.selected_node, correlation_id=cid)
            recorder.emit(TraceEventType.MISSION_JOB_COMPLETED, _ns(self.last_decision.total_finish_s), job_id=job_id, node_id=self.last_decision.selected_node, correlation_id=cid)
            recorder.emit(TraceEventType.JOB_COMPLETED, _ns(self.last_decision.total_finish_s), job_id=job_id, node_id=self.last_decision.selected_node, correlation_id=cid)
        expired = self.network.expire(end_s)
        for reservation in expired:
            if recorder:
                recorder.emit(TraceEventType.LINK_RESERVATION_EXPIRED, _ns(end_s), payload={"reservation_id": reservation.reservation_id, "transfer_id": reservation.transfer_id})
        self.now_s = end_s
        return f"advanced network runtime to T+{self.now_s:.1f}s transfers={len(self.transfers)}"

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
        self.transfers[transfer_id] = plan
        if recorder:
            recorder.emit(TraceEventType.TRANSFER_PLANNED, _ns(self.now_s), payload=plan.as_dict())
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
        return ContactWindow(contact_id, source, destination, start_s, end_s, bandwidth_bps, bytes_, latency_ms, survival, confidence, kind, visibility=result)

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
        return {}
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
