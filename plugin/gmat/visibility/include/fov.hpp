#pragma once

#include "visibility_query.hpp"
#include "visibility_result.hpp"

namespace oslurm::gmat_visibility {

struct VisibilityFovResult {
    bool ok = false;
    std::optional<double> margin_rad;
    VisibilityRejectionReason reason = VisibilityRejectionReason::Unknown;
};

class GmatFieldOfViewProvider {
public:
    VisibilityFovResult evaluate_source(const VisibilityQuery& query) const;
    VisibilityFovResult evaluate_destination(const VisibilityQuery& query) const;
};

struct PointingConstraintResult {
    bool feasible = false;
    double required_rate_rad_s = 0.0;
    double required_accel_rad_s2 = 0.0;
    std::optional<double> rate_margin;
    std::optional<double> accel_margin;
};

}  // namespace oslurm::gmat_visibility
