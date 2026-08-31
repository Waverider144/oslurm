#pragma once

#include "visibility_query.hpp"
#include "visibility_result.hpp"

#include <vector>

namespace oslurm::gmat_visibility {

struct VisibilityWindow {
    double start_s = 0.0;
    double end_s = 0.0;
    VisibilityResult result;
};

class VisibilityProvider {
public:
    virtual ~VisibilityProvider() = default;
    virtual VisibilityResult evaluate(const VisibilityQuery& query) const = 0;
    virtual std::vector<VisibilityWindow> windows(const VisibilityWindowQuery& query) const = 0;
};

}  // namespace oslurm::gmat_visibility
