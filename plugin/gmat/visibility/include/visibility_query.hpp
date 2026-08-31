#pragma once

#include <array>
#include <optional>
#include <string>
#include <vector>

namespace oslurm::gmat_visibility {

struct ConeFieldOfRegard {
    std::array<double, 3> boresight_body{1.0, 0.0, 0.0};
    double half_angle_rad = 0.0;
    bool require_pointing = false;
};

struct TerminalGeometry {
    std::string terminal_id;
    std::optional<ConeFieldOfRegard> cone;
    std::optional<std::array<std::array<double, 3>, 3>> body_to_inertial;
    std::optional<double> sun_exclusion_deg;
    std::optional<double> earth_limb_exclusion_deg;
    std::optional<double> moon_exclusion_deg;
};

struct VisibilityQuery {
    std::string source_id;
    std::string destination_id;
    double epoch_a1mjd = 0.0;
    std::array<double, 3> source_position_eci_m{0.0, 0.0, 0.0};
    std::array<double, 3> destination_position_eci_m{0.0, 0.0, 0.0};
    bool require_source_fov = false;
    bool require_destination_fov = false;
    std::optional<TerminalGeometry> source_terminal;
    std::optional<TerminalGeometry> destination_terminal;
    std::vector<std::string> occulting_bodies{"Earth"};
};

struct VisibilityWindowQuery {
    std::vector<std::pair<double, VisibilityQuery>> samples;
    double tolerance_s = 0.25;
};

}  // namespace oslurm::gmat_visibility
