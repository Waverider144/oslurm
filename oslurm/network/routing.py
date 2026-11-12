from __future__ import annotations

from .models import BufferState, ContactWindow, TransferHop, TransferIntent, TransferPlan, TransportPathKind


def _hop(intent: TransferIntent, contact: ContactWindow, start_after_s: float) -> TransferHop | None:
    start_s = max(contact.start_s, start_after_s)
    duration_s = contact.acquisition_s + intent.bytes * 8.0 / max(1, contact.bandwidth_bps) + contact.latency_ms / 1000.0
    end_s = start_s + duration_s
    if end_s > contact.end_s:
        return None
    if contact.capacity_for(start_s) < intent.bytes:
        return None
    return TransferHop(contact.source, contact.destination, contact.contact_id, start_s, end_s, intent.bytes, contact.bandwidth_bps)


def continuous_plans(intent: TransferIntent, contacts: list[ContactWindow]) -> list[TransferPlan]:
    plans: list[TransferPlan] = []
    for contact in contacts:
        if contact.source != intent.source or contact.destination != intent.destination:
            continue
        hop = _hop(intent, contact, intent.earliest_start_s)
        if hop is None:
            continue
        if intent.deadline_s is not None and hop.end_s > intent.deadline_s:
            continue
        plans.append(TransferPlan(
            transfer_id=intent.transfer_id,
            path_kind=TransportPathKind.CONTINUOUS,
            hops=[hop],
            predicted_finish_s=hop.end_s,
            bottleneck_bandwidth_bps=contact.bandwidth_bps,
            survival_probability=contact.survival_probability,
            confidence=contact.confidence,
            rationale=f"direct contact {contact.contact_id}",
        ))
    return sorted(plans, key=lambda plan: (plan.predicted_finish_s, -plan.bottleneck_bandwidth_bps, plan.hops[0].contact_id))


def temporal_plans(intent: TransferIntent, contacts: list[ContactWindow], buffers: dict[str, BufferState]) -> list[TransferPlan]:
    plans: list[TransferPlan] = []
    for first in contacts:
        if first.source != intent.source:
            continue
        if buffers.get(first.destination, BufferState(0)).available_bytes < intent.bytes:
            continue
        first_hop = _hop(intent, first, intent.earliest_start_s)
        if first_hop is None:
            continue
        for second in contacts:
            if second.source != first.destination or second.destination != intent.destination:
                continue
            second_hop = _hop(intent, second, first_hop.end_s)
            if second_hop is None:
                continue
            if intent.deadline_s is not None and second_hop.end_s > intent.deadline_s:
                continue
            plans.append(TransferPlan(
                transfer_id=intent.transfer_id,
                path_kind=TransportPathKind.TEMPORAL_STORE_CARRY_FORWARD,
                hops=[first_hop, second_hop],
                predicted_finish_s=second_hop.end_s,
                bottleneck_bandwidth_bps=min(first.bandwidth_bps, second.bandwidth_bps),
                survival_probability=first.survival_probability * second.survival_probability,
                confidence=min(first.confidence, second.confidence),
                rationale=f"store-carry-forward via {first.destination}",
            ))
    return sorted(plans, key=lambda plan: (plan.predicted_finish_s, len(plan.hops), -plan.bottleneck_bandwidth_bps, plan.hops[0].contact_id))
