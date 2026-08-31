#include "gmat_comm/communication_payload.hpp"
#include "gmat_comm/routing.hpp"

#include <iostream>

using namespace gmat_comm;

int main() {
    TransferIntent intent;
    intent.transfer_id = "DEMO-XFER";
    intent.source = "SAT001";
    intent.destination = "GROUND-SANYA";
    intent.bytes = 2'000'000;
    intent.earliest_start_s = 0.0;
    intent.deadline_s = 600.0;
    intent.delivery = DeliverySemantics::CustodyTransfer;

    ContactWindow uplink;
    uplink.contact_id = "SAT001-RELAY-A";
    uplink.source = "SAT001";
    uplink.destination = "RELAY-A";
    uplink.start_s = 15.0;
    uplink.end_s = 220.0;
    uplink.minimum_bandwidth_bps = 25'000'000;
    uplink.conservative_transfer_bytes = 12'000'000;
    uplink.source_terminal = "SAT001-opt";
    uplink.destination_terminal = "RELAY-A-opt";

    ContactWindow downlink;
    downlink.contact_id = "RELAY-A-GROUND-SANYA";
    downlink.source = "RELAY-A";
    downlink.destination = "GROUND-SANYA";
    downlink.start_s = 240.0;
    downlink.end_s = 480.0;
    downlink.minimum_bandwidth_bps = 50'000'000;
    downlink.conservative_transfer_bytes = 20'000'000;
    downlink.source_terminal = "RELAY-A-rf";
    downlink.destination_terminal = "GROUND-SANYA-rf";

    BufferState relay_buffer;
    relay_buffer.capacity_bytes = 64'000'000;
    auto plans = temporal_plans(intent, {uplink, downlink}, relay_buffer, 1);
    if (plans.empty()) {
        std::cerr << "no relay plan\n";
        return 1;
    }

    const auto& plan = plans.front();
    std::cout << "GMAT-COMM relay demo\n";
    std::cout << "transfer_id=" << plan.transfer_id << "\n";
    std::cout << "hops=" << plan.hops.size() << "\n";
    std::cout << "finish_s=" << plan.predicted_finish_s << "\n";
    std::cout << "bottleneck_bps=" << plan.bottleneck_bandwidth_bps << "\n";
    return 0;
}
