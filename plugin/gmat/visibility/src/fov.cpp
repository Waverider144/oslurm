#include "fov.hpp"

#include <algorithm>
#include <array>
#include <cmath>

namespace oslurm::gmat_visibility {
namespace {

using Vec3 = std::array<double, 3>;

double dot(const Vec3& a, const Vec3& b) {
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}

double norm(const Vec3& a) {
    return std::sqrt(dot(a, a));
}

Vec3 sub(const Vec3& a, const Vec3& b) {
    return {a[0] - b[0], a[1] - b[1], a[2] - b[2]};
}

Vec3 unit(const Vec3& a) {
    const double n = norm(a);
    if (n <= 0.0) return {0.0, 0.0, 0.0};
    return {a[0] / n, a[1] / n, a[2] / n};
}

double clamp(double value, double lo, double hi) {
    return std::max(lo, std::min(hi, value));
}

Vec3 mat_vec(const std::array<std::array<double, 3>, 3>& m, const Vec3& v) {
    return {
        m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
        m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
        m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2],
    };
}

VisibilityFovResult evaluate_terminal(const TerminalGeometry* terminal,
                                      bool required,
                                      const Vec3& source_position,
                                      const Vec3& destination_position,
                                      VisibilityRejectionReason violation,
                                      VisibilityRejectionReason unavailable) {
    if (!required) return {true, std::nullopt, VisibilityRejectionReason::None};
    if (!terminal || !terminal->cone || !terminal->body_to_inertial) {
        return {false, std::nullopt, unavailable};
    }
    if (terminal->sun_exclusion_deg || terminal->earth_limb_exclusion_deg || terminal->moon_exclusion_deg) {
        return {false, std::nullopt, VisibilityRejectionReason::Unsupported};
    }
    const Vec3 boresight = unit(mat_vec(*terminal->body_to_inertial, terminal->cone->boresight_body));
    const Vec3 los = unit(sub(destination_position, source_position));
    if (norm(boresight) <= 0.0 || norm(los) <= 0.0) {
        return {false, std::nullopt, VisibilityRejectionReason::InvalidGeometry};
    }
    const double angle = std::acos(clamp(dot(boresight, los), -1.0, 1.0));
    const double margin = terminal->cone->half_angle_rad - angle;
    return {margin >= 0.0, margin, margin >= 0.0 ? VisibilityRejectionReason::None : violation};
}

}  // namespace

VisibilityFovResult GmatFieldOfViewProvider::evaluate_source(const VisibilityQuery& query) const {
    return evaluate_terminal(query.source_terminal ? &*query.source_terminal : nullptr,
                             query.require_source_fov,
                             query.source_position_eci_m,
                             query.destination_position_eci_m,
                             VisibilityRejectionReason::SourceFovViolation,
                             VisibilityRejectionReason::SourcePointingUnavailable);
}

VisibilityFovResult GmatFieldOfViewProvider::evaluate_destination(const VisibilityQuery& query) const {
    return evaluate_terminal(query.destination_terminal ? &*query.destination_terminal : nullptr,
                             query.require_destination_fov,
                             query.destination_position_eci_m,
                             query.source_position_eci_m,
                             VisibilityRejectionReason::DestinationFovViolation,
                             VisibilityRejectionReason::DestinationPointingUnavailable);
}

}  // namespace oslurm::gmat_visibility
