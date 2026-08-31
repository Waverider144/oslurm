#pragma once

#include "visibility_query.hpp"

namespace oslurm::gmat_visibility {

class GmatGeometryAdapter {
public:
    virtual ~GmatGeometryAdapter() = default;
    virtual VisibilityQuery make_query(const std::string& source_id,
                                       const std::string& destination_id,
                                       double epoch_a1mjd) const = 0;
};

}  // namespace oslurm::gmat_visibility
