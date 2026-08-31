#include "gmat_comm/profile.hpp"

#include <algorithm>
#include <fstream>
#include <sstream>
#include <stdexcept>

namespace gmat_comm {
namespace {

std::vector<std::string> split(const std::string& line, char sep) {
    std::vector<std::string> out;
    std::stringstream ss(line);
    std::string item;
    while (std::getline(ss, item, sep)) out.push_back(item);
    return out;
}

void read_curve(const std::string& path, std::vector<std::pair<double, EnvelopeValue>>& rows) {
    std::ifstream in(path);
    if (!in) throw std::runtime_error("missing envelope csv: " + path);
    std::string line;
    std::getline(in, line);
    while (std::getline(in, line)) {
        if (line.empty()) continue;
        auto cols = split(line, ',');
        if (cols.size() < 5) throw std::runtime_error("invalid envelope csv row");
        EnvelopeValue value;
        value.nominal = std::stod(cols[1]);
        value.lower_bound = std::stod(cols[2]);
        value.upper_bound = std::stod(cols[3]);
        value.confidence = std::stod(cols[4]);
        rows.push_back({std::stod(cols[0]) * 1000.0, value});
    }
    std::sort(rows.begin(), rows.end(), [](const auto& a, const auto& b) { return a.first < b.first; });
}

}  // namespace

FileEnvelopeProvider::FileEnvelopeProvider(const std::string& manifest_path) {
    std::ifstream in(manifest_path);
    if (!in) throw std::runtime_error("missing communication envelope manifest: " + manifest_path);
    const auto slash = manifest_path.find_last_of("/\\");
    const std::string base = slash == std::string::npos ? "." : manifest_path.substr(0, slash);
    std::string line;
    while (std::getline(in, line)) {
        if (line.find("model:") != std::string::npos) provenance_.terminal_model = line.substr(line.find(":") + 1);
        if (line.find("revision:") != std::string::npos) provenance_.revision = line.substr(line.find(":") + 1);
        if (line.find("source:") != std::string::npos) provenance_.source = line.substr(line.find(":") + 1);
        if (line.find("campaign:") != std::string::npos) provenance_.campaign = line.substr(line.find(":") + 1);
        if (line.find("policy:") != std::string::npos) policy_ = line.substr(line.find(":") + 1);
        if (line.find("bandwidth.csv") != std::string::npos) read_curve(base + "/bandwidth.csv", bandwidth_);
        if (line.find("latency.csv") != std::string::npos) read_curve(base + "/latency.csv", latency_);
        if (line.find("packet_loss.csv") != std::string::npos) read_curve(base + "/packet_loss.csv", packet_loss_);
        if (line.find("acquisition.csv") != std::string::npos) read_curve(base + "/acquisition.csv", acquisition_);
        if (line.find("power.csv") != std::string::npos) read_curve(base + "/power.csv", power_);
    }
    if (bandwidth_.empty()) throw std::runtime_error("manifest did not reference bandwidth.csv");
}

EnvelopeValue FileEnvelopeProvider::interpolate(const std::vector<std::pair<double, EnvelopeValue>>& rows,
                                                double range_m) const {
    if (rows.empty()) return {0.0, 0.0, 0.0, 0.0, false};
    if (range_m <= rows.front().first) {
        auto value = rows.front().second;
        value.extrapolated = range_m < rows.front().first;
        if (value.extrapolated && policy_.find("reject") != std::string::npos) return {0.0, 0.0, 0.0, 0.0, true};
        return value;
    }
    if (range_m >= rows.back().first) {
        auto value = rows.back().second;
        value.extrapolated = range_m > rows.back().first;
        if (value.extrapolated && policy_.find("reject") != std::string::npos) return {0.0, 0.0, 0.0, 0.0, true};
        return value;
    }
    for (std::size_t i = 1; i < rows.size(); ++i) {
        if (range_m > rows[i].first) continue;
        const auto& a = rows[i - 1];
        const auto& b = rows[i];
        const double t = (range_m - a.first) / (b.first - a.first);
        return {
            a.second.nominal + (b.second.nominal - a.second.nominal) * t,
            a.second.lower_bound + (b.second.lower_bound - a.second.lower_bound) * t,
            a.second.upper_bound + (b.second.upper_bound - a.second.upper_bound) * t,
            std::min(a.second.confidence, b.second.confidence),
            false,
        };
    }
    return rows.back().second;
}

EnvelopeValue FileEnvelopeProvider::bandwidth(const CommunicationQuery& query) const { return interpolate(bandwidth_, query.range_m); }
EnvelopeValue FileEnvelopeProvider::latency(const CommunicationQuery& query) const { return interpolate(latency_, query.range_m); }
EnvelopeValue FileEnvelopeProvider::packet_loss(const CommunicationQuery& query) const { return interpolate(packet_loss_, query.range_m); }
EnvelopeValue FileEnvelopeProvider::bit_error_rate(const CommunicationQuery&) const { return {1e-9, 1e-10, 1e-8, 0.7, false}; }
EnvelopeValue FileEnvelopeProvider::acquisition_time_s(const CommunicationQuery& query) const { return interpolate(acquisition_, query.range_m); }
EnvelopeValue FileEnvelopeProvider::link_survival_probability(const CommunicationQuery& query) const {
    auto loss = packet_loss(query);
    return {1.0 - loss.nominal, 1.0 - loss.upper_bound, 1.0 - loss.lower_bound, loss.confidence, loss.extrapolated};
}
EnvelopeValue FileEnvelopeProvider::power_draw_w(const CommunicationQuery& query) const { return interpolate(power_, query.range_m); }
Provenance FileEnvelopeProvider::provenance() const { return provenance_; }

}  // namespace gmat_comm
