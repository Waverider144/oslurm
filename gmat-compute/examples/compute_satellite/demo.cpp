#include "gmat_compute/compute_payload.hpp"
#include "gmat_compute/file_envelope_provider.hpp"

#include <fstream>
#include <iostream>
#include <regex>
#include <sstream>

using namespace gmat_compute;

static std::string read_file(const std::string& path) {
    std::ifstream in(path);
    std::ostringstream ss;
    ss << in.rdbuf();
    return ss.str();
}

static double extract_number_after(const std::string& text, const std::string& key, size_t pos) {
    const auto k = text.find(key, pos);
    if (k == std::string::npos) return 0.0;
    const auto start = text.find_first_of("-0123456789", k + key.size());
    const auto end = text.find_first_not_of("-0123456789.eE+", start);
    return std::stod(text.substr(start, end - start));
}

static bool extract_bool_after(const std::string& text, const std::string& key, size_t pos) {
    const auto k = text.find(key, pos);
    if (k == std::string::npos) return true;
    const auto t = text.find("true", k);
    const auto f = text.find("false", k);
    return t != std::string::npos && (f == std::string::npos || t < f);
}

static OrbitalEnvironmentState env_from_json_sample(const std::string& json, const std::string& node, size_t occurrence) {
    size_t pos = 0;
    for (size_t i = 0; i <= occurrence; ++i) {
        pos = json.find("\"node_id\": \"" + node + "\"", pos);
        if (pos == std::string::npos) throw std::runtime_error("node sample not found");
        if (i < occurrence) ++pos;
    }
    OrbitalEnvironmentState env;
    env.simulation_time_s = static_cast<double>(occurrence) * 60.0;
    env.in_sunlight = extract_bool_after(json, "\"in_sunlight\"", pos);
    env.external_temperature_k = env.in_sunlight ? 255.0 : 220.0;
    env.radiation_dose_rate_rad_s = 0.000001;
    env.cumulative_radiation_dose_rad = occurrence * 10.0;
    env.position_eci_m = {
        extract_number_after(json, "\"position_eci_m\"", pos),
        extract_number_after(json, ",", json.find("\"position_eci_m\"", pos)),
        extract_number_after(json, ",", json.find(",", json.find("\"position_eci_m\"", pos)) + 1)
    };
    return env;
}

static HardwareProfile profile() {
    HardwareProfile h;
    h.id = "generic_gpu";
    h.accelerator_model = "envelope";
    h.base_throughput_units_per_s = 480.0;
    h.nominal_power_w = 500.0;
    h.max_power_w = 500.0;
    h.idle_power_w = 60.0;
    h.thermal_limit_c = 78.0;
    h.workload_efficiency["gpu_fp16"] = 1.0;
    return h;
}

int main(int argc, char** argv) {
    if (argc < 2) {
        std::cerr << "usage: gmat_compute_demo <gmat-events.json>\n";
        return 2;
    }
    auto provider = std::make_shared<FileEnvelopeProvider>("measured/example_gpu/manifest.yaml");
    auto hardware = profile();
    ComputePayload payload(
        hardware,
        std::make_unique<EnvelopeDrivenPowerModel>(hardware, provider),
        std::make_unique<FirstOrderRCThermalModel>(45.0, 5000.0, 0.35, hardware.thermal_limit_c),
        std::make_unique<EnvelopeDrivenReliabilityModel>(provider),
        std::make_unique<GenericAccelerator>(hardware, provider));

    ComputeTaskSpec task;
    task.id = "demo-inference-001";
    task.required_compute_units = 160000.0;
    task.required_memory_bytes = 2ull * 1024 * 1024 * 1024;
    task.required_storage_bytes = 4ull * 1024 * 1024 * 1024;
    task.input_bytes = 512ull * 1024 * 1024;
    task.output_bytes = 64ull * 1024 * 1024;
    task.checkpointable = true;
    task.checkpoint_size_bytes = 256ull * 1024 * 1024;
    task.deadline_s = 600.0;
    task.priority = 10;
    task.workload_class = "gpu_fp16";
    const auto handle = payload.submit(task);
    payload.start(handle);

    const auto json = read_file(argv[1]);
    auto env0 = env_from_json_sample(json, "sat002", 0);
    payload.step(env0, 120.0);
    const auto before = payload.state();
    auto env_eclipse = env_from_json_sample(json, "sat002", 4);
    payload.step(env_eclipse, 1.0);
    const auto after = payload.state();
    payload.step(env_eclipse, 900.0);
    const auto final = payload.state();

    const auto prov = provider->provenance();
    std::cout << "Hardware model:\n"
              << "  source=" << prov.source << "\n"
              << "  device=" << prov.device_model << "\n"
              << "  revision=" << prov.revision << "\n"
              << "  campaign=" << prov.campaign << "\n"
              << "  manifest_sha256=" << prov.manifest_sha256 << "\n";
    std::cout << "[t=120.0] sunlight=" << (env0.in_sunlight ? "true" : "false") << "\n"
              << "GPU power cap=" << before.power_cap_w << " W\n"
              << "throughput=" << before.throughput_units_per_s << " units/s\n"
              << "task remaining=" << before.tasks.front().remaining_compute_units << "\n";
    std::cout << "[t=240.0] ECLIPSE_ENTRY\n";
    std::cout << "[t=242.0] sunlight=" << (env_eclipse.in_sunlight ? "true" : "false") << "\n"
              << "available compute power=" << after.power_cap_w << " W\n"
              << "GPU power cap=" << after.granted_power_w << " W\n"
              << "throughput=" << after.throughput_units_per_s << " units/s\n"
              << "predicted finish shifted +"
              << ((after.tasks.front().remaining_compute_units / std::max(after.throughput_units_per_s, 1.0)) -
                  (before.tasks.front().remaining_compute_units / before.throughput_units_per_s))
              << "s\n";
    std::cout << "Thermal derating=" << (after.thermal.throttling ? "ACTIVE" : "INACTIVE") << "\n";
    std::cout << "Task completed=" << (final.tasks.front().status == TaskStatus::Completed ? "YES" : "NO") << "\n";
    std::cout << "Throughput reduced=" << (after.throughput_units_per_s < before.throughput_units_per_s ? "YES" : "NO") << "\n";
    return after.throughput_units_per_s < before.throughput_units_per_s &&
           final.tasks.front().status == TaskStatus::Completed ? 0 : 1;
}
