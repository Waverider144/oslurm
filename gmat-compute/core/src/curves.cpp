#include "gmat_compute/curves.hpp"

namespace gmat_compute {

static Bounds lerp_bounds(const Bounds& a, const Bounds& b, double t, bool extrapolated) {
    return {
        a.nominal + (b.nominal - a.nominal) * t,
        a.lower_bound + (b.lower_bound - a.lower_bound) * t,
        a.upper_bound + (b.upper_bound - a.upper_bound) * t,
        a.confidence + (b.confidence - a.confidence) * t,
        extrapolated
    };
}

PiecewiseLinear1D::PiecewiseLinear1D(std::vector<std::pair<double, Bounds>> points,
                                     ExtrapolationPolicy policy)
    : points_(std::move(points)), policy_(policy) {
    std::sort(points_.begin(), points_.end(), [](const auto& a, const auto& b) {
        return a.first < b.first;
    });
    if (points_.empty()) {
        throw std::invalid_argument("PiecewiseLinear1D requires points");
    }
}

double PiecewiseLinear1D::evaluate(const std::vector<double>& x) const {
    return evaluate_bounds(x).nominal;
}

Bounds PiecewiseLinear1D::evaluate_bounds(const std::vector<double>& x) const {
    if (x.empty()) throw std::invalid_argument("PiecewiseLinear1D requires one coordinate");
    double q = x[0];
    if (points_.size() == 1) {
        Bounds out = points_[0].second;
        out.extrapolated = q != points_[0].first;
        return out;
    }
    if (q < points_.front().first || q > points_.back().first) {
        if (policy_ == ExtrapolationPolicy::Reject) {
            throw std::out_of_range("1D query outside interpolation domain");
        }
        if (policy_ == ExtrapolationPolicy::Clamp) {
            Bounds out = q < points_.front().first ? points_.front().second : points_.back().second;
            out.extrapolated = true;
            return out;
        }
    }
    for (size_t i = 1; i < points_.size(); ++i) {
        if (q <= points_[i].first) {
            double x0 = points_[i - 1].first;
            double x1 = points_[i].first;
            double t = (q - x0) / (x1 - x0);
            return lerp_bounds(points_[i - 1].second, points_[i].second, t,
                               q < points_.front().first || q > points_.back().first);
        }
    }
    Bounds out = points_.back().second;
    out.extrapolated = false;
    return out;
}

Bilinear2D::Bilinear2D(std::vector<Point> points, ExtrapolationPolicy policy)
    : points_(std::move(points)), policy_(policy) {
    if (points_.empty()) {
        throw std::invalid_argument("Bilinear2D requires points");
    }
}

double Bilinear2D::evaluate(const std::vector<double>& x) const {
    return evaluate_bounds(x).nominal;
}

Bounds Bilinear2D::evaluate_bounds(const std::vector<double>& x) const {
    if (x.size() < 2) throw std::invalid_argument("Bilinear2D requires two coordinates");
    const double qx = x[0];
    const double qy = x[1];
    const Point* best = nullptr;
    double best_dist = 0.0;
    for (const auto& p : points_) {
        double d = std::hypot(p.x - qx, p.y - qy);
        if (!best || d < best_dist) {
            best = &p;
            best_dist = d;
        }
    }
    Bounds out = best->value;
    double min_x = points_[0].x, max_x = points_[0].x, min_y = points_[0].y, max_y = points_[0].y;
    for (const auto& p : points_) {
        min_x = std::min(min_x, p.x); max_x = std::max(max_x, p.x);
        min_y = std::min(min_y, p.y); max_y = std::max(max_y, p.y);
    }
    out.extrapolated = qx < min_x || qx > max_x || qy < min_y || qy > max_y;
    if (out.extrapolated && policy_ == ExtrapolationPolicy::Reject) {
        throw std::out_of_range("2D query outside interpolation domain");
    }
    return out;
}

}  // namespace gmat_compute
