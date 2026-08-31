#pragma once

#include <optional>
#include <string>

namespace oslurm::gmat_visibility {

enum class VisibilityRejectionReason {
    None,
    EarthOccultation,
    OtherBodyOccultation,
    SourceFovViolation,
    DestinationFovViolation,
    SourcePointingUnavailable,
    DestinationPointingUnavailable,
    InvalidGeometry,
    Unsupported,
    Unknown,
};

struct VisibilityResult {
    bool geometrically_visible = false;
    bool earth_occulted = false;
    std::optional<std::string> occulting_body;
    bool source_fov_ok = false;
    bool destination_fov_ok = false;
    std::optional<double> source_fov_margin_rad;
    std::optional<double> destination_fov_margin_rad;
    std::optional<double> limb_clearance_m;
    VisibilityRejectionReason reason = VisibilityRejectionReason::Unknown;
    double confidence = 0.0;
    std::string fidelity = "spherical";
};

}  // namespace oslurm::gmat_visibility
