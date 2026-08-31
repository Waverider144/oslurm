from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class OccultingBody(str, Enum):
    EARTH = "Earth"
    MOON = "Moon"


class VisibilityRejectionReason(str, Enum):
    NONE = "NONE"
    EARTH_OCCULTATION = "EARTH_OCCULTATION"
    OTHER_BODY_OCCULTATION = "OTHER_BODY_OCCULTATION"
    SOURCE_FOV_VIOLATION = "SOURCE_FOV_VIOLATION"
    DESTINATION_FOV_VIOLATION = "DESTINATION_FOV_VIOLATION"
    SOURCE_POINTING_UNAVAILABLE = "SOURCE_POINTING_UNAVAILABLE"
    DESTINATION_POINTING_UNAVAILABLE = "DESTINATION_POINTING_UNAVAILABLE"
    INVALID_GEOMETRY = "INVALID_GEOMETRY"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class TerminalFov:
    terminal_id: str
    boresight_body: tuple[float, float, float] = (1.0, 0.0, 0.0)
    cone_half_angle_rad: float | None = None
    require_pointing: bool = False
    body_to_inertial: tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]] | None = None
    sun_exclusion_deg: float | None = None
    earth_limb_exclusion_deg: float | None = None
    moon_exclusion_deg: float | None = None


@dataclass(frozen=True)
class VisibilityQuery:
    source_id: str
    destination_id: str
    epoch_a1mjd: float = 0.0
    source_position_eci_m: tuple[float, float, float] | None = None
    destination_position_eci_m: tuple[float, float, float] | None = None
    require_source_fov: bool = False
    require_destination_fov: bool = False
    source_terminal: TerminalFov | None = None
    destination_terminal: TerminalFov | None = None
    occulting_bodies: tuple[OccultingBody, ...] = (OccultingBody.EARTH,)


@dataclass(frozen=True)
class VisibilityResult:
    geometrically_visible: bool
    earth_occulted: bool
    occulting_body: str | None
    source_fov_ok: bool
    destination_fov_ok: bool
    source_fov_margin_rad: float | None
    destination_fov_margin_rad: float | None
    limb_clearance_m: float | None
    reason: VisibilityRejectionReason
    confidence: float
    fidelity: str = "spherical"


@dataclass(frozen=True)
class BodyEllipsoid:
    name: str = "Earth"
    equatorial_radius_m: float = 6_378_137.0
    polar_radius_m: float = 6_356_752.314245
    safety_clearance_m: float = 10_000.0

    @property
    def effective_equatorial_radius_m(self) -> float:
        return self.equatorial_radius_m + self.safety_clearance_m

    @property
    def effective_polar_radius_m(self) -> float:
        return self.polar_radius_m + self.safety_clearance_m


@dataclass(frozen=True)
class VisibilityWindow:
    start_s: float
    end_s: float
    result: VisibilityResult


@dataclass(frozen=True)
class VisibilityWindowQuery:
    samples: tuple[tuple[float, VisibilityQuery], ...]
    tolerance_s: float = 0.25


@dataclass(frozen=True)
class PointingConstraintResult:
    feasible: bool
    required_rate_rad_s: float = 0.0
    required_accel_rad_s2: float = 0.0
    rate_margin: float | None = None
    accel_margin: float | None = None


@dataclass
class VisibilityProfilerMetrics:
    candidate_pairs: int = 0
    horizon_prefilter_rejected: int = 0
    exact_occultation_tests: int = 0
    earth_occultation_rejected: int = 0
    source_fov_rejected: int = 0
    destination_fov_rejected: int = 0
    range_rejected: int = 0
    terminal_rejected: int = 0
    links_created: int = 0
    visibility_cache_hits: int = 0
    visibility_cache_misses: int = 0

    def as_dict(self) -> dict[str, int]:
        return self.__dict__.copy()
