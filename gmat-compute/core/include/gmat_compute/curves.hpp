#pragma once

#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <utility>
#include <vector>

namespace gmat_compute {

struct Bounds {
    double nominal = 0.0;
    double lower_bound = 0.0;
    double upper_bound = 0.0;
    double confidence = 1.0;
    bool extrapolated = false;
};

class ScalarField {
public:
    virtual ~ScalarField() = default;
    virtual double evaluate(const std::vector<double>& x) const = 0;
    virtual Bounds evaluate_bounds(const std::vector<double>& x) const = 0;
};

enum class ExtrapolationPolicy {
    Reject,
    Clamp,
    Linear
};

class PiecewiseLinear1D final : public ScalarField {
public:
    explicit PiecewiseLinear1D(std::vector<std::pair<double, Bounds>> points,
                               ExtrapolationPolicy policy = ExtrapolationPolicy::Reject);
    double evaluate(const std::vector<double>& x) const override;
    Bounds evaluate_bounds(const std::vector<double>& x) const override;

private:
    std::vector<std::pair<double, Bounds>> points_;
    ExtrapolationPolicy policy_;
};

class Bilinear2D final : public ScalarField {
public:
    struct Point {
        double x = 0.0;
        double y = 0.0;
        Bounds value;
    };

    explicit Bilinear2D(std::vector<Point> points,
                        ExtrapolationPolicy policy = ExtrapolationPolicy::Reject);
    double evaluate(const std::vector<double>& x) const override;
    Bounds evaluate_bounds(const std::vector<double>& x) const override;

private:
    std::vector<Point> points_;
    ExtrapolationPolicy policy_;
};

}  // namespace gmat_compute
