#pragma once

namespace gmat_compute {

class SimulationClock {
public:
    explicit SimulationClock(double initial_time_s = 0.0) : time_s_(initial_time_s) {}
    double now_s() const { return time_s_; }
    void advance_by(double dt_s) { time_s_ += dt_s; }
    void advance_to(double time_s) { time_s_ = time_s; }

private:
    double time_s_;
};

}  // namespace gmat_compute
