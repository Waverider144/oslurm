from __future__ import annotations

from dataclasses import dataclass

from .models import TransferIntent, TransferPlan
from .service import NetworkPlanningService


@dataclass(frozen=True)
class ComputeCandidate:
    node_id: str
    compute_time_s: float
    input_source: str
    result_destination: str
    input_bytes: int
    result_bytes: int


@dataclass(frozen=True)
class JointDecision:
    job_id: str
    selected_node: str
    input_plan: TransferPlan
    result_plan: TransferPlan
    total_finish_s: float
    candidate_reports: list[dict]
    rationale: str


class JointComputeNetworkPlanner:
    def __init__(self, network: NetworkPlanningService) -> None:
        self.network = network

    def choose(self, job_id: str, candidates: list[ComputeCandidate], *, now_s: float, deadline_s: float) -> JointDecision:
        reports: list[dict] = []
        feasible: list[tuple[float, ComputeCandidate, TransferPlan, TransferPlan]] = []
        for candidate in candidates:
            input_intent = TransferIntent(
                transfer_id=f"{job_id}-INPUT-{candidate.node_id}",
                source=candidate.input_source,
                destination=candidate.node_id,
                bytes=candidate.input_bytes,
                earliest_start_s=now_s,
                deadline_s=deadline_s,
                job_id=job_id,
            )
            input_plans = self.network.plan_transfer(input_intent)
            if not input_plans:
                reports.append({"node_id": candidate.node_id, "feasible": False, "rejection_causes": ["NETWORK_INPUT"]})
                continue
            result_intent = TransferIntent(
                transfer_id=f"{job_id}-RESULT-{candidate.node_id}",
                source=candidate.node_id,
                destination=candidate.result_destination,
                bytes=candidate.result_bytes,
                earliest_start_s=input_plans[0].predicted_finish_s + candidate.compute_time_s,
                deadline_s=deadline_s,
                job_id=job_id,
            )
            result_plans = self.network.plan_transfer(result_intent)
            if not result_plans:
                reports.append({"node_id": candidate.node_id, "feasible": False, "rejection_causes": ["NETWORK_RESULT"]})
                continue
            total_finish_s = result_plans[0].predicted_finish_s
            reports.append({
                "node_id": candidate.node_id,
                "feasible": True,
                "compute_time_s": candidate.compute_time_s,
                "input_finish_s": input_plans[0].predicted_finish_s,
                "result_finish_s": total_finish_s,
                "network_path_kind": result_plans[0].path_kind.value,
            })
            feasible.append((total_finish_s, candidate, input_plans[0], result_plans[0]))
        if not feasible:
            raise RuntimeError(f"no network-feasible compute candidate for {job_id}")
        feasible.sort(key=lambda item: (item[0], item[1].compute_time_s, item[1].node_id))
        total_finish_s, candidate, input_plan, result_plan = feasible[0]
        input_plan.selected_for_compute_node = candidate.node_id
        result_plan.selected_for_compute_node = candidate.node_id
        return JointDecision(
            job_id=job_id,
            selected_node=candidate.node_id,
            input_plan=input_plan,
            result_plan=result_plan,
            total_finish_s=total_finish_s,
            candidate_reports=reports,
            rationale=f"selected {candidate.node_id}: slower compute is acceptable because network delivery finishes first",
        )
