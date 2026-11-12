from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

from .models import BufferState, ContactWindow, NetworkReservation, NetworkReservationState, TransferIntent, TransferPlan
from .routing import continuous_plans, temporal_plans


class NetworkPlanningService:
    def __init__(self) -> None:
        self.contacts: list[ContactWindow] = []
        self.buffers: dict[str, BufferState] = {}
        self.reservations: dict[str, NetworkReservation] = {}
        self._next_reservation_id = 1
        self._buffer_allocations: dict[str, dict[str, int]] = {}

    def add_contacts(self, contacts: list[ContactWindow]) -> None:
        for contact in contacts:
            if contact.visibility is not None and not contact.visibility.geometrically_visible:
                raise ValueError(f"cannot add invisible contact {contact.contact_id}: {contact.visibility.reason.value}")
        self.contacts.extend(contacts)
        self.contacts.sort(key=lambda c: (c.start_s, c.source, c.destination, c.contact_id))

    def set_buffer(self, node_id: str, buffer: BufferState) -> None:
        self.buffers[node_id] = buffer

    def fork(self) -> NetworkPlanningService:
        """Isolated planning snapshot; probing routes must not consume live capacity."""
        return deepcopy(self)

    def reserve_plans(self, plans: list[TransferPlan], *, now_s: float,
                      lease_s: float = 30.0, commit: bool = False) -> list[NetworkReservation]:
        """Validate a mission's paths together before publishing any reservation.

        The simulator is single-threaded. Concurrent callers must serialize this
        transaction with contact updates and other reservations.
        """
        trial = self.fork()
        created = []
        for plan in plans:
            created.extend(trial.reserve_plan(plan, now_s=now_s, lease_s=lease_s))
        if commit:
            for plan in plans:
                trial.commit_plan(plan)
        self._adopt_planning_state(trial)
        return created

    def _adopt_planning_state(self, trial: NetworkPlanningService) -> None:
        for key, reservation in trial.reservations.items():
            if key in self.reservations:
                self.reservations[key].state = reservation.state
            else:
                self.reservations[key] = reservation
        for node, buffer in trial.buffers.items():
            self.buffers[node].reserved_bytes = buffer.reserved_bytes
        self._buffer_allocations = trial._buffer_allocations
        self._next_reservation_id = trial._next_reservation_id

    def replan_transfer(self, previous: TransferPlan, intent: TransferIntent, *, now_s: float) -> TransferPlan | None:
        """Replace an unused speculative reservation after actual compute finishes.

        Callers must not use this for a transfer that has already transmitted.
        No route leaves the old reservation intact for explicit failure cleanup.
        """
        reservations = [r for r in self.reservations.values() if r.transfer_id == previous.transfer_id]
        if (not reservations or any(r.state not in {NetworkReservationState.ACCEPTED, NetworkReservationState.COMMITTED}
                                    for r in reservations) or intent.earliest_start_s < now_s):
            raise ValueError("only an unused accepted/committed transfer can be replanned")
        trial = self.fork()
        trial.abort_plan(previous)
        for plan in trial.plan_transfer(intent):
            try:
                trial.reserve_plans([plan], now_s=now_s, commit=True)
            except ValueError:
                continue
            self._adopt_planning_state(trial)
            return plan
        return None

    def plan_transfer(self, intent: TransferIntent) -> list[TransferPlan]:
        contacts = self._available_contacts()
        plans = continuous_plans(intent, contacts)
        plans.extend(temporal_plans(intent, contacts, self.buffers))
        return sorted(plans, key=lambda p: (p.predicted_finish_s, len(p.hops), -p.bottleneck_bandwidth_bps, p.transfer_id))

    def _available_contacts(self) -> list[ContactWindow]:
        occupied = [r for r in self.reservations.values()
                    if r.state not in {NetworkReservationState.EXPIRED, NetworkReservationState.ABORTED}]
        by_id = {c.contact_id: c for c in self.contacts}
        available = []
        for contact in self.contacts:
            terminals = {(contact.source, contact.source_terminal), (contact.destination, contact.destination_terminal)}
            intervals = [(contact.start_s, contact.end_s)]
            remaining = contact.conservative_transfer_bytes
            for reservation in occupied:
                hop = reservation.hop
                other = by_id[hop.contact_id]
                if other.contact_id == contact.contact_id:
                    remaining -= hop.reserved_bytes
                if not terminals.intersection({(other.source, other.source_terminal), (other.destination, other.destination_terminal)}):
                    continue
                free = []
                for start, end in intervals:
                    if hop.end_s <= start or hop.start_s >= end:
                        free.append((start, end))
                    else:
                        if start < hop.start_s:
                            free.append((start, hop.start_s))
                        if hop.end_s < end:
                            free.append((hop.end_s, end))
                intervals = free
            if remaining > 0:
                available.extend(replace(contact, start_s=start, end_s=end,
                                         conservative_transfer_bytes=remaining) for start, end in intervals)
        return available

    def reserve_plan(self, plan: TransferPlan, *, now_s: float, lease_s: float = 30.0) -> list[NetworkReservation]:
        if not plan.hops or lease_s <= 0 or any(r.transfer_id == plan.transfer_id for r in self.reservations.values()):
            raise ValueError("invalid or duplicate transfer reservation")
        if abs(plan.predicted_finish_s - plan.hops[-1].end_s) > 1e-9 or len({h.reserved_bytes for h in plan.hops}) != 1 or any(
                left.destination != right.source or left.end_s > right.start_s
                for left, right in zip(plan.hops, plan.hops[1:])):
            raise ValueError("transfer hops are not a causal delivery path")
        contacts = self._available_contacts()
        remaining_bytes = {}
        for hop in plan.hops:
            matches = [c for c in contacts if c.contact_id == hop.contact_id and c.source == hop.source
                       and c.destination == hop.destination and c.start_s <= hop.start_s < hop.end_s <= c.end_s]
            if hop.start_s < now_s or not matches:
                raise ValueError("contact/terminal already reserved or outside window")
            contact = matches[0]
            if hop.bandwidth_bps != contact.bandwidth_bps:
                raise ValueError("reserved bandwidth does not match contact")
            minimum = contact.acquisition_s + hop.reserved_bytes * 8 / contact.bandwidth_bps + contact.latency_ms / 1000
            remaining_bytes.setdefault(contact.contact_id, contact.conservative_transfer_bytes)
            remaining_bytes[contact.contact_id] -= hop.reserved_bytes
            if hop.reserved_bytes <= 0 or hop.end_s - hop.start_s + 1e-9 < minimum or remaining_bytes[contact.contact_id] < 0:
                raise ValueError("insufficient contact capacity")
        allocations = {hop.destination: hop.reserved_bytes for hop in plan.hops[:-1]}
        if any(self.buffers.get(node, BufferState(0)).available_bytes < size for node, size in allocations.items()):
            raise ValueError("insufficient relay buffer")
        for node, size in allocations.items():
            self.buffers[node].reserved_bytes += size
        self._buffer_allocations[plan.transfer_id] = allocations
        created: list[NetworkReservation] = []
        for hop in plan.hops:
            reservation_id = f"NETRES-{self._next_reservation_id:04d}"
            self._next_reservation_id += 1
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
        reservations = [r for r in self.reservations.values() if r.transfer_id == plan.transfer_id]
        if not reservations or any(r.state not in {NetworkReservationState.ACCEPTED, NetworkReservationState.COMMITTED} for r in reservations):
            raise ValueError("transfer reservation is not accepted")
        for reservation in self.reservations.values():
            if reservation.transfer_id == plan.transfer_id:
                reservation.state = NetworkReservationState.COMMITTED

    def _release_buffer(self, transfer_id: str) -> None:
        for node, size in self._buffer_allocations.pop(transfer_id, {}).items():
            self.buffers[node].reserved_bytes -= size

    def complete_plan(self, plan: TransferPlan, *, now_s: float) -> None:
        reservations = [r for r in self.reservations.values() if r.transfer_id == plan.transfer_id]
        if now_s < plan.predicted_finish_s or not reservations or any(
                r.state not in {NetworkReservationState.COMMITTED, NetworkReservationState.COMPLETED} for r in reservations):
            raise ValueError("transfer is not ready to complete")
        for reservation in reservations:
            reservation.state = NetworkReservationState.COMPLETED
        self._release_buffer(plan.transfer_id)

    def abort_plan(self, plan: TransferPlan) -> None:
        for reservation in self.reservations.values():
            if reservation.transfer_id == plan.transfer_id and reservation.state != NetworkReservationState.COMPLETED:
                reservation.state = NetworkReservationState.ABORTED
        self._release_buffer(plan.transfer_id)

    def expire(self, now_s: float) -> list[NetworkReservation]:
        expired: list[NetworkReservation] = []
        for reservation in self.reservations.values():
            if reservation.state == NetworkReservationState.ACCEPTED and reservation.expires_at_s <= now_s:
                reservation.state = NetworkReservationState.EXPIRED
                expired.append(reservation)
        for transfer_id in {r.transfer_id for r in expired}:
            self._release_buffer(transfer_id)
        return expired
