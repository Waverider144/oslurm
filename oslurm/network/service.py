from __future__ import annotations

import itertools

from .models import BufferState, ContactWindow, NetworkReservation, NetworkReservationState, TransferIntent, TransferPlan
from .routing import continuous_plans, temporal_plans


class NetworkPlanningService:
    def __init__(self) -> None:
        self.contacts: list[ContactWindow] = []
        self.buffers: dict[str, BufferState] = {}
        self.reservations: dict[str, NetworkReservation] = {}
        self._ids = itertools.count(1)

    def add_contacts(self, contacts: list[ContactWindow]) -> None:
        for contact in contacts:
            if contact.visibility is not None and not contact.visibility.geometrically_visible:
                raise ValueError(f"cannot add invisible contact {contact.contact_id}: {contact.visibility.reason.value}")
        self.contacts.extend(contacts)
        self.contacts.sort(key=lambda c: (c.start_s, c.source, c.destination, c.contact_id))

    def set_buffer(self, node_id: str, buffer: BufferState) -> None:
        self.buffers[node_id] = buffer

    def plan_transfer(self, intent: TransferIntent) -> list[TransferPlan]:
        plans = continuous_plans(intent, self.contacts)
        plans.extend(temporal_plans(intent, self.contacts, self.buffers))
        return sorted(plans, key=lambda p: (p.predicted_finish_s, len(p.hops), -p.bottleneck_bandwidth_bps, p.transfer_id))

    def reserve_plan(self, plan: TransferPlan, *, now_s: float, lease_s: float = 30.0) -> list[NetworkReservation]:
        created: list[NetworkReservation] = []
        for hop in plan.hops:
            reservation_id = f"NETRES-{next(self._ids):04d}"
            reservation = NetworkReservation(
                reservation_id=reservation_id,
                transfer_id=plan.transfer_id,
                hop=hop,
                state=NetworkReservationState.ACCEPTED,
                created_at_s=now_s,
                expires_at_s=now_s + lease_s,
                lease_s=lease_s,
            )
            self.reservations[reservation_id] = reservation
            created.append(reservation)
        return created

    def commit_plan(self, plan: TransferPlan) -> None:
        for reservation in self.reservations.values():
            if reservation.transfer_id == plan.transfer_id:
                reservation.state = NetworkReservationState.COMMITTED

    def expire(self, now_s: float) -> list[NetworkReservation]:
        expired: list[NetworkReservation] = []
        for reservation in self.reservations.values():
            if reservation.state == NetworkReservationState.ACCEPTED and reservation.expires_at_s <= now_s:
                reservation.state = NetworkReservationState.EXPIRED
                expired.append(reservation)
        return expired
