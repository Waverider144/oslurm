#include "gmat_comm/communication_payload.hpp"
#include "gmat_comm/profile.hpp"
#include "gmat_comm/routing.hpp"

#include <cassert>
#include <cmath>
#include <iostream>
#include <memory>

using namespace gmat_comm;

namespace {

CommunicationTerminal terminal(const std::string& id) {
    CommunicationTerminal value;
    value.terminal_id = id;
    value.profile_id = "generic-optical";
    value.kind = TerminalKind::Optical;
    value.max_power_w = 80.0;
    return value;
}

ContactWindow contact(const std::string& id,
                      const std::string& source,
                      const std::string& destination,
                      double start,
                      double end,
                      uint64_t bytes) {
    ContactWindow value;
    value.contact_id = id;
    value.source = source;
    value.destination = destination;
    value.start_s = start;
    value.end_s = end;
    value.minimum_bandwidth_bps = 10'000'000;
    value.conservative_transfer_bytes = bytes;
    value.latency_upper_bound_ms = 50.0;
    value.survival_probability = 0.99;
    value.confidence = 0.85;
    value.source_terminal = source + "-tx";
    value.destination_terminal = destination + "-rx";
    return value;
}

void test_payload_reservation_lifecycle() {
    CommunicationPayloadProfile profile;
    profile.profile_id = "RELAY01";
    profile.terminals.push_back(terminal("RELAY01-t0"));
    profile.buffer.capacity_bytes = 4096;

    auto provider = std::make_shared<AnalyticEnvelopeProvider>();
    auto model = std::make_shared<ProviderTerminalModel>(provider);
    CommunicationPayload payload(profile, model);

    CommunicationEnvironmentState env;
    env.simulation_time_s = 0.0;
    env.range_m = 1'000'000.0;
    env.line_of_sight = true;
    payload.step({{env}}, 1.0);
    assert(payload.state().terminals.front().state.acquisition_state == AcquisitionState::Active);

    TransferHop hop;
    hop.source = "SAT-A";
    hop.destination = "RELAY01";
    hop.source_terminal = "RELAY01-t0";
    LinkReservationRequest request;
    request.reservation_id = "RES-1";
    request.transfer_id = "XFER-1";
    request.hop = hop;
    request.bytes = 1024;
    request.now_s = 1.0;
    request.lease_s = 2.0;

    assert(payload.reserve(request));
    assert(payload.reserve(request));
    assert(payload.state().buffer.reserved_bytes == 1024);
    assert(!payload.reserve({"RES-2", "XFER-2", hop, 1024, 1, 1.0, 5.0}));
    payload.step({}, 3.0);
    assert(payload.state().reservations.front().state == ReservationState::Expired);
    assert(payload.state().buffer.reserved_bytes == 0);
}

void test_file_envelope_provider_interpolates_and_rejects() {
    FileEnvelopeProvider provider("measured/example_terminal/manifest.yaml");
    CommunicationQuery query;
    query.range_m = 1'500'000.0;
    auto bandwidth = provider.bandwidth(query);
    assert(bandwidth.nominal > 0.0);
    assert(!bandwidth.extrapolated);
    query.range_m = 99'000'000.0;
    auto rejected = provider.bandwidth(query);
    assert(rejected.extrapolated);
    assert(rejected.nominal == 0.0);
}

void test_continuous_and_temporal_routes_are_deterministic() {
    TransferIntent intent;
    intent.transfer_id = "XFER-42";
    intent.source = "SAT-A";
    intent.destination = "GROUND-1";
    intent.bytes = 256;
    intent.earliest_start_s = 0.0;
    intent.deadline_s = 120.0;

    std::vector<ContactWindow> contacts = {
        contact("C2", "SAT-A", "GROUND-1", 0.0, 80.0, 1024),
        contact("C1", "SAT-A", "GROUND-1", 0.0, 100.0, 1024),
        contact("R1", "SAT-A", "RELAY-1", 10.0, 60.0, 1024),
        contact("R2", "RELAY-1", "GROUND-1", 65.0, 110.0, 1024),
    };

    auto continuous = continuous_plans(intent, contacts, 4);
    assert(continuous.size() == 2);
    assert(continuous.front().hops.front().contact_id == "C1");

    BufferState buffer;
    buffer.capacity_bytes = 4096;
    auto temporal = temporal_plans(intent, contacts, buffer, 4);
    assert(temporal.size() == 1);
    assert(temporal.front().path_kind == TransportPathKind::TemporalStoreCarryForward);
    assert(temporal.front().hops.size() == 2);
}

}  // namespace

int main() {
    test_payload_reservation_lifecycle();
    test_file_envelope_provider_interpolates_and_rejects();
    test_continuous_and_temporal_routes_are_deterministic();
    std::cout << "gmat-comm core tests passed\n";
    return 0;
}
