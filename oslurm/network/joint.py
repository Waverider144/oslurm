from __future__ import annotations

from dataclasses import dataclass
import math

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
    available_at_s: float = 0.0
    rejection_causes: tuple[str, ...] = ()


@dataclass(frozen=True)
class JointDecision:
    job_id: str
    selected_node: str
    input_plan: TransferPlan
    result_plan: TransferPlan
    total_finish_s: float
    candidate_reports: list[dict]
    rationale: str
    compute_start_s: float
    compute_finish_s: float
    compute_only_node: str


class JointPlanningError(RuntimeError):
    def __init__(self, job_id: str, reports: list[dict]) -> None:
        self.candidate_reports = reports
        reasons = "; ".join(f"{r['node_id']}={','.join(r.get('rejection_causes', []))}" for r in reports)
        super().__init__(f"no joint-feasible compute candidate for {job_id}: {reasons}")


class JointComputeNetworkPlanner:
    def __init__(self, network: NetworkPlanningService) -> None:
        self.network = network

    def choose(self, job_id: str, candidates: list[ComputeCandidate], *, now_s: float, deadline_s: float) -> JointDecision:
        reports: list[dict] = []
        feasible: list[tuple[float, ComputeCandidate, TransferPlan, TransferPlan]] = []
        if not math.isfinite(now_s) or not math.isfinite(deadline_s) or deadline_s <= now_s:
            raise ValueError("deadline must be finite and later than now")
        for candidate in candidates:
            if (not math.isfinite(candidate.compute_time_s) or candidate.compute_time_s <= 0
                    or not math.isfinite(candidate.available_at_s)
                    or candidate.input_bytes <= 0 or candidate.result_bytes <= 0):
                raise ValueError(f"invalid compute candidate {candidate.node_id}")
        eligible = [c for c in candidates if not c.rejection_causes]
        compute_only = min(eligible, key=lambda c: (max(now_s, c.available_at_s) + c.compute_time_s, c.node_id), default=None)
        for candidate in candidates:
            if candidate.rejection_causes:
                reports.append({"node_id": candidate.node_id, "feasible": False,
                                "rejection_causes": list(candidate.rejection_causes)})
                continue
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
            pairs = []
            for input_plan in input_plans:
                trial = self.network.fork()
                try:
                    trial.reserve_plan(input_plan, now_s=now_s)
                except ValueError:
                    continue
                compute_start = max(input_plan.predicted_finish_s, candidate.available_at_s)
                result_intent = TransferIntent(
                    transfer_id=f"{job_id}-RESULT-{candidate.node_id}",
                    source=candidate.node_id,
                    destination=candidate.result_destination,
                    bytes=candidate.result_bytes,
                    earliest_start_s=compute_start + candidate.compute_time_s,
                    deadline_s=deadline_s,
                    job_id=job_id,
                )
                for result_plan in trial.plan_transfer(result_intent):
                    try:
                        trial.reserve_plans([result_plan], now_s=now_s)
                    except ValueError:
                        continue
                    pairs.append((result_plan.predicted_finish_s, input_plan, result_plan))
                    break
            if not pairs:
                reports.append({"node_id": candidate.node_id, "feasible": False, "rejection_causes": ["NETWORK_RESULT"]})
                continue
            total_finish_s, input_plan, result_plan = min(pairs, key=lambda p: p[0])
            compute_start = max(input_plan.predicted_finish_s, candidate.available_at_s)
            reports.append({
                "node_id": candidate.node_id,
                "feasible": True,
                "compute_time_s": candidate.compute_time_s,
                "input_finish_s": input_plan.predicted_finish_s,
                "compute_start_s": compute_start,
                "compute_finish_s": compute_start + candidate.compute_time_s,
                "result_finish_s": total_finish_s,
                "network_path_kind": result_plan.path_kind.value,
            })
            feasible.append((total_finish_s, candidate, input_plan, result_plan))
        if not feasible:
            raise JointPlanningError(job_id, reports)
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
            rationale=f"selected {candidate.node_id}: earliest feasible ground delivery at T+{total_finish_s:.3f}s",
            compute_start_s=max(input_plan.predicted_finish_s, candidate.available_at_s),
            compute_finish_s=max(input_plan.predicted_finish_s, candidate.available_at_s) + candidate.compute_time_s,
            compute_only_node=compute_only.node_id,
        )
