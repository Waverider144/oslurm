#include "gmat_compute/file_envelope_provider.hpp"

#include <algorithm>
#include <cmath>
#include <fstream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <unordered_map>

namespace gmat_compute {

static std::string trim(std::string s) {
    auto not_space = [](unsigned char c) { return !std::isspace(c); };
    s.erase(s.begin(), std::find_if(s.begin(), s.end(), not_space));
    s.erase(std::find_if(s.rbegin(), s.rend(), not_space).base(), s.end());
    if (!s.empty() && (s.front() == '"' || s.front() == '\'')) s.erase(s.begin());
    if (!s.empty() && (s.back() == '"' || s.back() == '\'')) s.pop_back();
    return s;
}

static std::vector<std::string> split_csv(const std::string& line) {
    std::vector<std::string> out;
    std::stringstream ss(line);
    std::string cell;
    while (std::getline(ss, cell, ',')) out.push_back(trim(cell));
    return out;
}

static std::unordered_map<std::string, std::string> parse_manifest(const std::filesystem::path& path) {
    std::ifstream in(path);
    if (!in) throw std::runtime_error("cannot open manifest: " + path.string());
    std::unordered_map<std::string, std::string> values;
    std::vector<std::string> stack;
    std::string line;
    while (std::getline(in, line)) {
        if (line.empty() || trim(line).empty() || trim(line).front() == '#') continue;
        const size_t indent = line.find_first_not_of(' ');
        const std::string body = trim(line);
        const auto colon = body.find(':');
        if (colon == std::string::npos) continue;
        const std::string key = trim(body.substr(0, colon));
        const std::string value = trim(body.substr(colon + 1));
        const size_t level = indent / 2;
        if (stack.size() > level) stack.resize(level);
        if (value.empty()) {
            if (stack.size() == level) stack.push_back(key);
            else stack[level] = key;
        } else {
            std::string full;
            for (const auto& s : stack) {
                if (!full.empty()) full += ".";
                full += s;
            }
            if (!full.empty()) full += ".";
            full += key;
            values[full] = value;
        }
    }
    return values;
}

static double number(const std::unordered_map<std::string, std::string>& row, const std::string& key, double def = 0.0) {
    auto it = row.find(key);
    return it == row.end() || it->second.empty() ? def : std::stod(it->second);
}

static std::vector<std::unordered_map<std::string, std::string>> read_csv(const std::filesystem::path& path) {
    std::ifstream in(path);
    if (!in) throw std::runtime_error("cannot open csv: " + path.string());
    std::string line;
    if (!std::getline(in, line)) return {};
    const auto header = split_csv(line);
    std::vector<std::unordered_map<std::string, std::string>> rows;
    while (std::getline(in, line)) {
        if (trim(line).empty()) continue;
        const auto cells = split_csv(line);
        std::unordered_map<std::string, std::string> row;
        for (size_t i = 0; i < header.size() && i < cells.size(); ++i) row[header[i]] = cells[i];
        rows.push_back(std::move(row));
    }
    return rows;
}

FileEnvelopeProvider::FileEnvelopeProvider(const std::filesystem::path& manifest_path)
    : manifest_path_(manifest_path), base_dir_(manifest_path.parent_path()) {
    const auto m = parse_manifest(manifest_path);
    provenance_.source = m.count("provenance.source") ? m.at("provenance.source") : "unknown";
    provenance_.device_model = m.count("device.model") ? m.at("device.model") : "unknown";
    provenance_.revision = m.count("device.revision") ? m.at("device.revision") : "unknown";
    provenance_.campaign = m.count("provenance.test_campaign") ? m.at("provenance.test_campaign") : "unknown";
    provenance_.manifest_sha256 = m.count("provenance.manifest_sha256") ? m.at("provenance.manifest_sha256") : "";
    extrapolation_policy_ = m.count("extrapolation.policy") ? m.at("extrapolation.policy") : "reject";

    const auto pt_file = base_dir_ / (m.count("datasets.power_throughput.file") ? m.at("datasets.power_throughput.file") : "power_throughput.csv");
    for (const auto& row : read_csv(pt_file)) {
        power_rows_.push_back({number(row, "temperature_c"),
                               number(row, "power_cap_w"),
                               row.count("workload_class") ? row.at("workload_class") : "generic",
                               number(row, "throughput"),
                               number(row, "power_w"),
                               number(row, "lower", number(row, "throughput")),
                               number(row, "upper", number(row, "throughput"))});
    }
    const auto rad_file = base_dir_ / (m.count("datasets.temperature_derating.file") ? m.at("datasets.temperature_derating.file") :
                                      m.count("datasets.radiation_degradation.file") ? m.at("datasets.radiation_degradation.file") :
                                      "radiation_degradation.csv");
    if (std::filesystem::exists(rad_file)) {
        for (const auto& row : read_csv(rad_file)) {
            radiation_rows_.push_back({number(row, "cumulative_dose_rad"),
                                       number(row, "temperature_c"),
                                       number(row, "performance_factor", 1.0),
                                       number(row, "lower", 1.0),
                                       number(row, "upper", 1.0)});
        }
    }
    const auto fault_file = base_dir_ / (m.count("datasets.fault_rate.file") ? m.at("datasets.fault_rate.file") : "fault_rate.csv");
    if (std::filesystem::exists(fault_file)) {
        for (const auto& row : read_csv(fault_file)) {
            fault_rows_.push_back({number(row, "particle_flux"),
                                   number(row, "temperature_c"),
                                   number(row, "power_w"),
                                   number(row, "fault_rate_per_hour")});
        }
    }
}

EnvelopeValue FileEnvelopeProvider::interpolate_power_throughput(const HardwareQuery& query,
                                                                 bool want_power) const {
    const PowerThroughputRow* best = nullptr;
    double best_d = std::numeric_limits<double>::infinity();
    double min_temp = std::numeric_limits<double>::infinity(), max_temp = -min_temp;
    double min_power = std::numeric_limits<double>::infinity(), max_power = -min_power;
    for (const auto& r : power_rows_) {
        if (r.workload_class != query.workload_class) continue;
        min_temp = std::min(min_temp, r.temperature_c);
        max_temp = std::max(max_temp, r.temperature_c);
        min_power = std::min(min_power, r.power_cap_w);
        max_power = std::max(max_power, r.power_cap_w);
        const double d = std::hypot((r.temperature_c - query.temperature_c) / 20.0,
                                    (r.power_cap_w - query.power_cap_w) / 200.0);
        if (d < best_d) {
            best = &r;
            best_d = d;
        }
    }
    if (!best) throw std::runtime_error("no envelope rows for workload " + query.workload_class);
    const bool extrapolated = query.temperature_c < min_temp || query.temperature_c > max_temp ||
                              query.power_cap_w < min_power || query.power_cap_w > max_power;
    if (extrapolated && extrapolation_policy_ == "reject") {
        throw std::out_of_range("hardware query outside measured envelope");
    }
    const double nominal = want_power ? best->power_w : best->throughput;
    const double lower = want_power ? best->power_w * 0.98 : best->lower;
    const double upper = want_power ? best->power_w * 1.02 : best->upper;
    return {nominal, lower, upper, extrapolated ? 0.55 : 0.9, extrapolated};
}

EnvelopeValue FileEnvelopeProvider::throughput(const HardwareQuery& query) const {
    return interpolate_power_throughput(query, false);
}

EnvelopeValue FileEnvelopeProvider::power(const HardwareQuery& query) const {
    return interpolate_power_throughput(query, true);
}

EnvelopeValue FileEnvelopeProvider::failure_rate(const HardwareQuery& query) const {
    if (fault_rows_.empty()) return {0.0, 0.0, 0.0, 1.0, false};
    const FaultRow* best = nullptr;
    double best_d = std::numeric_limits<double>::infinity();
    for (const auto& r : fault_rows_) {
        const double d = std::hypot(r.temperature_c - query.temperature_c,
                                    (r.power_w - query.power_cap_w) / 10.0);
        if (d < best_d) { best = &r; best_d = d; }
    }
    return {best->fault_rate_per_hour, best->fault_rate_per_hour * 0.8,
            best->fault_rate_per_hour * 1.3, 0.72, best_d > 20.0};
}

EnvelopeValue FileEnvelopeProvider::memory_error_rate(const HardwareQuery&) const {
    return {0.0, 0.0, 0.0, 0.5, false};
}

EnvelopeValue FileEnvelopeProvider::degradation(const HardwareQuery& query) const {
    if (radiation_rows_.empty()) return {1.0, 1.0, 1.0, 1.0, false};
    const RadiationRow* best = nullptr;
    double best_d = std::numeric_limits<double>::infinity();
    double min_dose = std::numeric_limits<double>::infinity(), max_dose = -min_dose;
    for (const auto& r : radiation_rows_) {
        min_dose = std::min(min_dose, r.cumulative_dose_rad);
        max_dose = std::max(max_dose, r.cumulative_dose_rad);
        const double d = std::abs(r.cumulative_dose_rad - query.cumulative_dose_rad);
        if (d < best_d) { best = &r; best_d = d; }
    }
    const bool extrapolated = query.cumulative_dose_rad < min_dose || query.cumulative_dose_rad > max_dose;
    if (extrapolated && extrapolation_policy_ == "reject") {
        throw std::out_of_range("radiation query outside measured envelope");
    }
    return {best->performance_factor, best->lower, best->upper, extrapolated ? 0.55 : 0.9, extrapolated};
}

Provenance FileEnvelopeProvider::provenance() const {
    return provenance_;
}

}  // namespace gmat_compute
