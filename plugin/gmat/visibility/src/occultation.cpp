#include "occultation.hpp"

#include <algorithm>
#include <cmath>

namespace oslurm::gmat_visibility {
namespace {

double dot(const std::array<double, 3>& a, const std::array<double, 3>& b) {
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}

double norm(const std::array<double, 3>& a) {
    return std::sqrt(dot(a, a));
}

std::array<double, 3> sub(const std::array<double, 3>& a, const std::array<double, 3>& b) {
    return {a[0] - b[0], a[1] - b[1], a[2] - b[2]};
}

double clamp(double value, double lo, double hi) {
    return std::max(lo, std::min(hi, value));
}

std::array<double, 3> unit(const std::array<double, 3>& a) {
    const double n = norm(a);
    if (n <= 0.0) return {0.0, 0.0, 0.0};
    return {a[0] / n, a[1] / n, a[2] / n};
}

double ellipsoid_value(const std::array<double, 3>& point, const EarthEllipsoidConfig& config) {
    const double a = config.equatorial_radius_m + config.safety_clearance_m;
    const double b = config.polar_radius_m + config.safety_clearance_m;
    return (point[0] * point[0] + point[1] * point[1]) / (a * a) + point[2] * point[2] / (b * b);
}

double ellipsoid_radial_clearance_m(const std::array<double, 3>& point, const EarthEllipsoidConfig& config) {
    const double n = norm(point);
    if (n <= 0.0) return -(config.polar_radius_m + config.safety_clearance_m);
    const auto u = unit(point);
    const double a = config.equatorial_radius_m + config.safety_clearance_m;
    const double b = config.polar_radius_m + config.safety_clearance_m;
    const double denom = (u[0] * u[0] + u[1] * u[1]) / (a * a) + (u[2] * u[2]) / (b * b);
    const double surface_radius = 1.0 / std::sqrt(denom);
    return n - surface_radius;
}

}  // namespace

double segment_limb_clearance_m(const std::array<double, 3>& source,
                                const std::array<double, 3>& destination,
                                double effective_radius_m) {
    const auto d = sub(destination, source);
    const double denom = dot(d, d);
    if (denom <= 0.0) return -effective_radius_m;
    const double t = clamp(-dot(source, d) / denom, 0.0, 1.0);
    const std::array<double, 3> closest{
        source[0] + t * d[0],
        source[1] + t * d[1],
        source[2] + t * d[2],
    };
    return norm(closest) - effective_radius_m;
}

bool horizon_prefilter_blocked(const std::array<double, 3>& source,
                               const std::array<double, 3>& destination,
                               double effective_radius_m) {
    const double n1 = norm(source);
    const double n2 = norm(destination);
    if (n1 <= effective_radius_m || n2 <= effective_radius_m) return false;
    const double alpha = std::acos(clamp(dot(source, destination) / (n1 * n2), -1.0, 1.0));
    const double theta1 = std::acos(clamp(effective_radius_m / n1, -1.0, 1.0));
    const double theta2 = std::acos(clamp(effective_radius_m / n2, -1.0, 1.0));
    return alpha > theta1 + theta2;
}

double ellipsoid_segment_limb_clearance_m(const std::array<double, 3>& source,
                                          const std::array<double, 3>& destination,
                                          const EarthEllipsoidConfig& config) {
    const auto d = sub(destination, source);
    const double denom = dot(d, d);
    if (denom <= 0.0) return -(config.polar_radius_m + config.safety_clearance_m);
    const double t = clamp(-dot(source, d) / denom, 0.0, 1.0);
    const std::array<double, 3> closest{
        source[0] + t * d[0],
        source[1] + t * d[1],
        source[2] + t * d[2],
    };
    return ellipsoid_radial_clearance_m(closest, config);
}

bool ellipsoid_segment_intersects(const std::array<double, 3>& source,
                                  const std::array<double, 3>& destination,
                                  const EarthEllipsoidConfig& config) {
    const double a = config.equatorial_radius_m + config.safety_clearance_m;
    const double b = config.polar_radius_m + config.safety_clearance_m;
    const auto d = sub(destination, source);
    const double qa = (d[0] * d[0] + d[1] * d[1]) / (a * a) + (d[2] * d[2]) / (b * b);
    const double qb = 2.0 * ((source[0] * d[0] + source[1] * d[1]) / (a * a) + (source[2] * d[2]) / (b * b));
    const double qc = ellipsoid_value(source, config) - 1.0;
    if (qa <= 0.0) return qc <= 0.0;
    const double discriminant = qb * qb - 4.0 * qa * qc;
    if (discriminant < 0.0) return false;
    const double root = std::sqrt(discriminant);
    const double t1 = (-qb - root) / (2.0 * qa);
    const double t2 = (-qb + root) / (2.0 * qa);
    return (0.0 <= t1 && t1 <= 1.0) || (0.0 <= t2 && t2 <= 1.0) || (t1 < 0.0 && t2 > 1.0);
}

std::array<double, 3> ellipsoid_surface_normal(const std::array<double, 3>& point,
                                               const EarthEllipsoidConfig& config) {
    const double a = config.equatorial_radius_m + config.safety_clearance_m;
    const double b = config.polar_radius_m + config.safety_clearance_m;
    return unit({point[0] / (a * a), point[1] / (a * a), point[2] / (b * b)});
}

}  // namespace oslurm::gmat_visibility
