#pragma once

#include <array>

namespace oslurm::gmat_visibility {

struct EarthOccultationConfig {
    double earth_mean_radius_m = 6371000.0;
    double safety_clearance_m = 10000.0;
};

struct EarthEllipsoidConfig {
    double equatorial_radius_m = 6378137.0;
    double polar_radius_m = 6356752.314245;
    double safety_clearance_m = 10000.0;
};

double segment_limb_clearance_m(const std::array<double, 3>& source,
                                const std::array<double, 3>& destination,
                                double effective_radius_m);

bool horizon_prefilter_blocked(const std::array<double, 3>& source,
                               const std::array<double, 3>& destination,
                               double effective_radius_m);

double ellipsoid_segment_limb_clearance_m(const std::array<double, 3>& source,
                                          const std::array<double, 3>& destination,
                                          const EarthEllipsoidConfig& config);

bool ellipsoid_segment_intersects(const std::array<double, 3>& source,
                                  const std::array<double, 3>& destination,
                                  const EarthEllipsoidConfig& config);

std::array<double, 3> ellipsoid_surface_normal(const std::array<double, 3>& point,
                                               const EarthEllipsoidConfig& config);

}  // namespace oslurm::gmat_visibility
