from __future__ import annotations

import math
from abc import ABC, abstractmethod

from .models import (
    BodyEllipsoid,
    OccultingBody,
    TerminalFov,
    VisibilityProfilerMetrics,
    VisibilityQuery,
    VisibilityRejectionReason,
    VisibilityResult,
    VisibilityWindow,
    VisibilityWindowQuery,
)


EARTH_MEAN_RADIUS_M = 6_371_000.0
WGS84_EARTH = BodyEllipsoid()


class VisibilityProvider(ABC):
    @abstractmethod
    def evaluate(self, query: VisibilityQuery) -> VisibilityResult:
        raise NotImplementedError

    @abstractmethod
    def windows(self, query: VisibilityWindowQuery) -> list[VisibilityWindow]:
        raise NotImplementedError


class AnalyticSphereVisibilityProvider(VisibilityProvider):
    def __init__(self, *, earth_radius_m: float = EARTH_MEAN_RADIUS_M, safety_clearance_m: float = 10_000.0, strict: bool = True) -> None:
        self.earth_radius_m = earth_radius_m
        self.safety_clearance_m = safety_clearance_m
        self.strict = strict
        self.metrics = VisibilityProfilerMetrics()

    @property
    def effective_radius_m(self) -> float:
        return self.earth_radius_m + self.safety_clearance_m

    def evaluate(self, query: VisibilityQuery) -> VisibilityResult:
        self.metrics.candidate_pairs += 1
        if OccultingBody.EARTH not in query.occulting_bodies:
            return _visible(None, 0.7, "spherical")
        if query.source_position_eci_m is None or query.destination_position_eci_m is None:
            return _reject(VisibilityRejectionReason.INVALID_GEOMETRY, None, confidence=0.0)
        r1 = tuple(float(v) for v in query.source_position_eci_m)
        r2 = tuple(float(v) for v in query.destination_position_eci_m)
        ground_result = self._ground_horizon_result(r1, r2)
        if ground_result is not None:
            if not ground_result[0]:
                self.metrics.earth_occultation_rejected += 1
                return _reject(VisibilityRejectionReason.EARTH_OCCULTATION, ground_result[1])
            clearance = ground_result[1]
            source_fov = self._evaluate_fov(query.source_terminal, r1, r2, query.require_source_fov, is_source=True)
            if not source_fov[0]:
                self.metrics.source_fov_rejected += 1
                return _reject(source_fov[2], clearance, source_margin=source_fov[1])
            destination_fov = self._evaluate_fov(query.destination_terminal, r2, r1, query.require_destination_fov, is_source=False)
            if not destination_fov[0]:
                self.metrics.destination_fov_rejected += 1
                return _reject(destination_fov[2], clearance, source_margin=source_fov[1], destination_margin=destination_fov[1])
            self.metrics.links_created += 1
            return VisibilityResult(True, False, None, True, True, source_fov[1], destination_fov[1], clearance, VisibilityRejectionReason.NONE, 0.9)
        if _norm(r1) <= self.effective_radius_m or _norm(r2) <= self.effective_radius_m:
            return _reject(VisibilityRejectionReason.INVALID_GEOMETRY, None, confidence=0.0)
        preblocked = self._horizon_prefilter(r1, r2)
        if preblocked:
            self.metrics.horizon_prefilter_rejected += 1
            clearance = segment_limb_clearance_m(r1, r2, self.effective_radius_m)
            self.metrics.earth_occultation_rejected += 1
            return _reject(VisibilityRejectionReason.EARTH_OCCULTATION, clearance)
        self.metrics.exact_occultation_tests += 1
        clearance = segment_limb_clearance_m(r1, r2, self.effective_radius_m)
        if clearance <= 0.0:
            self.metrics.earth_occultation_rejected += 1
            return _reject(VisibilityRejectionReason.EARTH_OCCULTATION, clearance)
        source_fov = self._evaluate_fov(query.source_terminal, r1, r2, query.require_source_fov, is_source=True)
        if not source_fov[0]:
            self.metrics.source_fov_rejected += 1
            return _reject(source_fov[2], clearance, source_margin=source_fov[1])
        destination_fov = self._evaluate_fov(query.destination_terminal, r2, r1, query.require_destination_fov, is_source=False)
        if not destination_fov[0]:
            self.metrics.destination_fov_rejected += 1
            return _reject(destination_fov[2], clearance, source_margin=source_fov[1], destination_margin=destination_fov[1])
        self.metrics.links_created += 1
        return VisibilityResult(
            geometrically_visible=True,
            earth_occulted=False,
            occulting_body=None,
            source_fov_ok=True,
            destination_fov_ok=True,
            source_fov_margin_rad=source_fov[1],
            destination_fov_margin_rad=destination_fov[1],
            limb_clearance_m=clearance,
            reason=VisibilityRejectionReason.NONE,
            confidence=0.95,
        )

    def windows(self, query: VisibilityWindowQuery) -> list[VisibilityWindow]:
        if not query.samples:
            return []
        windows: list[VisibilityWindow] = []
        current_result = self.evaluate(query.samples[0][1])
        current_start = query.samples[0][0]
        previous_time = query.samples[0][0]
        previous_result = current_result
        for time_s, sample_query in query.samples[1:]:
            result = self.evaluate(sample_query)
            if _state_key(result) != _state_key(previous_result):
                boundary = self._refine_transition(previous_time, time_s, query.samples, previous_result, result, query.tolerance_s)
                windows.append(VisibilityWindow(current_start, boundary, previous_result))
                current_start = boundary
                current_result = result
            previous_time = time_s
            previous_result = result
        windows.append(VisibilityWindow(current_start, previous_time, current_result))
        return [w for w in windows if w.end_s >= w.start_s]

    def _horizon_prefilter(self, r1: tuple[float, float, float], r2: tuple[float, float, float]) -> bool:
        n1 = _norm(r1)
        n2 = _norm(r2)
        alpha = math.acos(_clamp(_dot(r1, r2) / (n1 * n2), -1.0, 1.0))
        theta1 = math.acos(_clamp(self.effective_radius_m / n1, -1.0, 1.0))
        theta2 = math.acos(_clamp(self.effective_radius_m / n2, -1.0, 1.0))
        return alpha > theta1 + theta2

    def _evaluate_fov(self, terminal: TerminalFov | None, source_position: tuple[float, float, float], destination_position: tuple[float, float, float], required: bool, *, is_source: bool = True) -> tuple[bool, float | None, VisibilityRejectionReason]:
        reason = VisibilityRejectionReason.SOURCE_FOV_VIOLATION if is_source else VisibilityRejectionReason.DESTINATION_FOV_VIOLATION
        unavailable = VisibilityRejectionReason.SOURCE_POINTING_UNAVAILABLE if is_source else VisibilityRejectionReason.DESTINATION_POINTING_UNAVAILABLE
        if not required:
            return True, None, VisibilityRejectionReason.NONE
        if terminal is None:
            return False, None, unavailable
        if terminal.sun_exclusion_deg is not None or terminal.earth_limb_exclusion_deg is not None or terminal.moon_exclusion_deg is not None:
            return False, None, VisibilityRejectionReason.UNSUPPORTED
        if terminal.cone_half_angle_rad is None:
            return (not self.strict), None, unavailable
        if terminal.body_to_inertial is None:
            return False, None, unavailable
        boresight = _mat_vec(terminal.body_to_inertial, terminal.boresight_body)
        los = _unit(_sub(destination_position, source_position))
        if _norm(boresight) <= 0.0 or _norm(los) <= 0.0:
            return False, None, VisibilityRejectionReason.INVALID_GEOMETRY
        angle = math.acos(_clamp(_dot(_unit(boresight), los), -1.0, 1.0))
        margin = terminal.cone_half_angle_rad - angle
        return margin >= 0.0, margin, reason

    def _ground_horizon_result(self, r1: tuple[float, float, float], r2: tuple[float, float, float]) -> tuple[bool, float] | None:
        n1 = _norm(r1)
        n2 = _norm(r2)
        source_ground = n1 <= self.effective_radius_m and n2 > self.effective_radius_m
        destination_ground = n2 <= self.effective_radius_m and n1 > self.effective_radius_m
        if not source_ground and not destination_ground:
            return None
        ground = r1 if source_ground else r2
        spacecraft = r2 if source_ground else r1
        local_up = _unit(ground)
        look = _unit(_sub(spacecraft, ground))
        sin_elevation = _dot(local_up, look)
        slant_range = _norm(_sub(spacecraft, ground))
        clearance = sin_elevation * slant_range
        return sin_elevation > 0.0, clearance

    def _refine_transition(self, start: float, end: float, samples: tuple[tuple[float, VisibilityQuery], ...], left: VisibilityResult, right: VisibilityResult, tolerance_s: float) -> float:
        # Deterministic first version: sample interpolation is external; use bisection in time only.
        del samples, left, right
        while end - start > tolerance_s:
            midpoint = (start + end) / 2.0
            end = midpoint
        return end


class AnalyticEllipsoidVisibilityProvider(AnalyticSphereVisibilityProvider):
    def __init__(self, *, body: BodyEllipsoid = WGS84_EARTH, strict: bool = True) -> None:
        self.body = body
        super().__init__(earth_radius_m=body.equatorial_radius_m, safety_clearance_m=body.safety_clearance_m, strict=strict)

    @property
    def effective_radius_m(self) -> float:
        return self.body.effective_equatorial_radius_m

    @property
    def effective_polar_radius_m(self) -> float:
        return self.body.effective_polar_radius_m

    def _horizon_prefilter(self, r1: tuple[float, float, float], r2: tuple[float, float, float]) -> bool:
        n1 = _norm(r1)
        n2 = _norm(r2)
        conservative_radius = min(self.body.effective_equatorial_radius_m, self.body.effective_polar_radius_m)
        alpha = math.acos(_clamp(_dot(r1, r2) / (n1 * n2), -1.0, 1.0))
        theta1 = math.acos(_clamp(conservative_radius / n1, -1.0, 1.0))
        theta2 = math.acos(_clamp(conservative_radius / n2, -1.0, 1.0))
        return alpha > theta1 + theta2

    def evaluate(self, query: VisibilityQuery) -> VisibilityResult:
        self.metrics.candidate_pairs += 1
        if OccultingBody.EARTH not in query.occulting_bodies:
            return _visible(None, 0.7, "ellipsoid:wgs84")
        if query.source_position_eci_m is None or query.destination_position_eci_m is None:
            return _reject(VisibilityRejectionReason.INVALID_GEOMETRY, None, confidence=0.0, fidelity="ellipsoid:wgs84")
        r1 = tuple(float(v) for v in query.source_position_eci_m)
        r2 = tuple(float(v) for v in query.destination_position_eci_m)
        ground_result = self._ground_horizon_result(r1, r2)
        if ground_result is not None:
            if not ground_result[0]:
                self.metrics.earth_occultation_rejected += 1
                return _reject(VisibilityRejectionReason.EARTH_OCCULTATION, ground_result[1], fidelity="ellipsoid:wgs84")
            return self._finish_with_fov(query, r1, r2, ground_result[1], confidence=0.92)
        if _ellipsoid_value(r1, self.body) <= 1.0 or _ellipsoid_value(r2, self.body) <= 1.0:
            return _reject(VisibilityRejectionReason.INVALID_GEOMETRY, None, confidence=0.0, fidelity="ellipsoid:wgs84")
        if self._horizon_prefilter(r1, r2):
            self.metrics.horizon_prefilter_rejected += 1
            clearance = ellipsoid_segment_clearance_m(r1, r2, self.body)
            self.metrics.earth_occultation_rejected += 1
            return _reject(VisibilityRejectionReason.EARTH_OCCULTATION, clearance, fidelity="ellipsoid:wgs84")
        self.metrics.exact_occultation_tests += 1
        clearance = ellipsoid_segment_clearance_m(r1, r2, self.body)
        if ellipsoid_segment_intersects(r1, r2, self.body):
            self.metrics.earth_occultation_rejected += 1
            return _reject(VisibilityRejectionReason.EARTH_OCCULTATION, clearance, fidelity="ellipsoid:wgs84")
        return self._finish_with_fov(query, r1, r2, clearance, confidence=0.97)

    def _ground_horizon_result(self, r1: tuple[float, float, float], r2: tuple[float, float, float]) -> tuple[bool, float] | None:
        source_ground = _ellipsoid_value(r1, self.body) <= 1.000001 and _ellipsoid_value(r2, self.body) > 1.0
        destination_ground = _ellipsoid_value(r2, self.body) <= 1.000001 and _ellipsoid_value(r1, self.body) > 1.0
        if not source_ground and not destination_ground:
            return None
        ground = r1 if source_ground else r2
        spacecraft = r2 if source_ground else r1
        local_up = _ellipsoid_normal(ground, self.body)
        look = _unit(_sub(spacecraft, ground))
        sin_elevation = _dot(local_up, look)
        slant_range = _norm(_sub(spacecraft, ground))
        clearance = sin_elevation * slant_range
        return sin_elevation > 0.0, clearance

    def _finish_with_fov(self, query: VisibilityQuery, r1: tuple[float, float, float], r2: tuple[float, float, float], clearance: float | None, *, confidence: float) -> VisibilityResult:
        source_fov = self._evaluate_fov(query.source_terminal, r1, r2, query.require_source_fov, is_source=True)
        if not source_fov[0]:
            self.metrics.source_fov_rejected += 1
            return _reject(source_fov[2], clearance, source_margin=source_fov[1], fidelity="ellipsoid:wgs84")
        destination_fov = self._evaluate_fov(query.destination_terminal, r2, r1, query.require_destination_fov, is_source=False)
        if not destination_fov[0]:
            self.metrics.destination_fov_rejected += 1
            return _reject(destination_fov[2], clearance, source_margin=source_fov[1], destination_margin=destination_fov[1], fidelity="ellipsoid:wgs84")
        self.metrics.links_created += 1
        return VisibilityResult(True, False, None, True, True, source_fov[1], destination_fov[1], clearance, VisibilityRejectionReason.NONE, confidence, "ellipsoid:wgs84")


def segment_limb_clearance_m(r1: tuple[float, float, float], r2: tuple[float, float, float], radius_m: float) -> float:
    d = _sub(r2, r1)
    denom = _dot(d, d)
    if denom <= 0.0:
        return -radius_m
    t = _clamp(-_dot(r1, d) / denom, 0.0, 1.0)
    closest = (r1[0] + t * d[0], r1[1] + t * d[1], r1[2] + t * d[2])
    return _norm(closest) - radius_m


def ellipsoid_segment_intersects(r1: tuple[float, float, float], r2: tuple[float, float, float], body: BodyEllipsoid) -> bool:
    a = body.effective_equatorial_radius_m
    b = body.effective_polar_radius_m
    d = _sub(r2, r1)
    aa = (d[0] * d[0] + d[1] * d[1]) / (a * a) + (d[2] * d[2]) / (b * b)
    bb = 2.0 * ((r1[0] * d[0] + r1[1] * d[1]) / (a * a) + (r1[2] * d[2]) / (b * b))
    cc = (r1[0] * r1[0] + r1[1] * r1[1]) / (a * a) + (r1[2] * r1[2]) / (b * b) - 1.0
    if aa <= 0.0:
        return cc <= 0.0
    discriminant = bb * bb - 4.0 * aa * cc
    if discriminant < 0.0:
        return False
    root = math.sqrt(discriminant)
    t1 = (-bb - root) / (2.0 * aa)
    t2 = (-bb + root) / (2.0 * aa)
    return (0.0 <= t1 <= 1.0) or (0.0 <= t2 <= 1.0) or (t1 < 0.0 and t2 > 1.0)


def ellipsoid_segment_clearance_m(r1: tuple[float, float, float], r2: tuple[float, float, float], body: BodyEllipsoid) -> float:
    d = _sub(r2, r1)
    denom = _dot(d, d)
    if denom <= 0.0:
        return -body.effective_equatorial_radius_m
    t = _clamp(-_dot(r1, d) / denom, 0.0, 1.0)
    closest = (r1[0] + t * d[0], r1[1] + t * d[1], r1[2] + t * d[2])
    return _ellipsoid_radial_clearance_m(closest, body)


def _ellipsoid_value(point: tuple[float, float, float], body: BodyEllipsoid) -> float:
    a = body.effective_equatorial_radius_m
    b = body.effective_polar_radius_m
    return (point[0] * point[0] + point[1] * point[1]) / (a * a) + point[2] * point[2] / (b * b)


def _ellipsoid_radial_clearance_m(point: tuple[float, float, float], body: BodyEllipsoid) -> float:
    n = _norm(point)
    if n <= 0.0:
        return -body.effective_polar_radius_m
    u = _unit(point)
    a = body.effective_equatorial_radius_m
    b = body.effective_polar_radius_m
    denom = (u[0] * u[0] + u[1] * u[1]) / (a * a) + (u[2] * u[2]) / (b * b)
    surface_radius = 1.0 / math.sqrt(denom)
    return n - surface_radius


def _ellipsoid_normal(point: tuple[float, float, float], body: BodyEllipsoid) -> tuple[float, float, float]:
    a = body.effective_equatorial_radius_m
    b = body.effective_polar_radius_m
    return _unit((point[0] / (a * a), point[1] / (a * a), point[2] / (b * b)))


def _reject(reason: VisibilityRejectionReason, clearance: float | None, *, confidence: float = 0.95, source_margin: float | None = None, destination_margin: float | None = None, fidelity: str = "spherical") -> VisibilityResult:
    return VisibilityResult(
        geometrically_visible=False,
        earth_occulted=reason == VisibilityRejectionReason.EARTH_OCCULTATION,
        occulting_body="Earth" if reason == VisibilityRejectionReason.EARTH_OCCULTATION else None,
        source_fov_ok=reason != VisibilityRejectionReason.SOURCE_FOV_VIOLATION,
        destination_fov_ok=reason != VisibilityRejectionReason.DESTINATION_FOV_VIOLATION,
        source_fov_margin_rad=source_margin,
        destination_fov_margin_rad=destination_margin,
        limb_clearance_m=clearance,
        reason=reason,
        confidence=confidence,
        fidelity=fidelity,
    )


def _visible(clearance: float | None, confidence: float, fidelity: str) -> VisibilityResult:
    return VisibilityResult(True, False, None, True, True, None, None, clearance, VisibilityRejectionReason.NONE, confidence, fidelity)


def _state_key(result: VisibilityResult) -> tuple[bool, VisibilityRejectionReason]:
    return result.geometrically_visible, result.reason


def _dot(a, b) -> float:
    return sum(float(x) * float(y) for x, y in zip(a, b))


def _sub(a, b) -> tuple[float, float, float]:
    return tuple(float(x) - float(y) for x, y in zip(a, b))


def _norm(a) -> float:
    return math.sqrt(_dot(a, a))


def _unit(a) -> tuple[float, float, float]:
    n = _norm(a)
    return (0.0, 0.0, 0.0) if n <= 0.0 else tuple(float(x) / n for x in a)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _mat_vec(m, v) -> tuple[float, float, float]:
    return (
        m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
        m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
        m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2],
    )
