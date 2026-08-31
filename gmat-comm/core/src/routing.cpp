#include "gmat_comm/routing.hpp"

#include <algorithm>
#include <limits>
#include <queue>
#include <set>
#include <unordered_map>

namespace gmat_comm {
namespace {

TransferPlan plan_from_contacts(const TransferIntent& intent,
                                const std::vector<ContactWindow>& path,
                                TransportPathKind kind) {
    TransferPlan plan;
    plan.transfer_id = intent.transfer_id;
    plan.path_kind = kind;
    plan.earliest_start_s = path.front().start_s;
    plan.predicted_finish_s = path.back().start_s;
    plan.transferable_bytes_lower_bound = intent.bytes;
    plan.bottleneck_bandwidth_bps = std::numeric_limits<uint64_t>::max();
    plan.minimum_contact_margin_s = std::numeric_limits<double>::max();
    plan.survival_probability = 1.0;
    plan.confidence = 1.0;
    for (const auto& contact : path) {
        TransferHop hop;
        hop.source = contact.source;
        hop.destination = contact.destination;
        hop.contact_id = contact.contact_id;
        hop.start_s = std::max(contact.start_s + contact.acquisition_delay_s, intent.earliest_start_s);
        const double seconds = static_cast<double>(intent.bytes) * 8.0 / std::max<uint64_t>(1, contact.minimum_bandwidth_bps);
        hop.end_s = hop.start_s + seconds;
        hop.reserved_bytes = intent.bytes;
        hop.source_terminal = contact.source_terminal;
        hop.destination_terminal = contact.destination_terminal;
        plan.predicted_finish_s = std::max(plan.predicted_finish_s, hop.end_s);
        plan.end_to_end_latency_ms += contact.latency_upper_bound_ms;
        plan.bottleneck_bandwidth_bps = std::min(plan.bottleneck_bandwidth_bps, contact.minimum_bandwidth_bps);
        plan.minimum_contact_margin_s = std::min(plan.minimum_contact_margin_s, contact.end_s - hop.end_s);
        plan.survival_probability *= contact.survival_probability;
        plan.confidence = std::min(plan.confidence, contact.confidence);
        plan.control_plane_cost += 1.0;
        plan.hops.push_back(hop);
    }
    return plan;
}

bool deliverable(const TransferIntent& intent, const TransferPlan& plan) {
    return plan.minimum_contact_margin_s >= 0.0 && (!intent.deadline_s || plan.predicted_finish_s <= *intent.deadline_s);
}

}  // namespace

std::vector<TransferPlan> continuous_plans(const TransferIntent& intent,
                                           const std::vector<ContactWindow>& contacts,
                                           std::size_t max_plans) {
    std::vector<TransferPlan> plans;
    for (const auto& contact : contacts) {
        if (contact.source != intent.source || contact.destination != intent.destination) continue;
        if (contact.end_s < intent.earliest_start_s || contact.conservative_transfer_bytes < intent.bytes) continue;
        auto plan = plan_from_contacts(intent, {contact}, TransportPathKind::Continuous);
        if (deliverable(intent, plan)) plans.push_back(plan);
    }
    std::sort(plans.begin(), plans.end(), [](const auto& a, const auto& b) {
        if (a.minimum_contact_margin_s != b.minimum_contact_margin_s) return a.minimum_contact_margin_s > b.minimum_contact_margin_s;
        if (a.predicted_finish_s != b.predicted_finish_s) return a.predicted_finish_s < b.predicted_finish_s;
        return a.hops.front().contact_id < b.hops.front().contact_id;
    });
    if (plans.size() > max_plans) plans.resize(max_plans);
    return plans;
}

std::vector<TransferPlan> temporal_plans(const TransferIntent& intent,
                                         const std::vector<ContactWindow>& contacts,
                                         const BufferState& buffer,
                                         std::size_t max_plans) {
    if (buffer.capacity_bytes < buffer.used_bytes + buffer.reserved_bytes + intent.bytes) return {};
    std::vector<TransferPlan> plans;
    for (const auto& first : contacts) {
        if (first.source != intent.source || first.conservative_transfer_bytes < intent.bytes) continue;
        for (const auto& second : contacts) {
            if (first.destination != second.source || second.destination != intent.destination) continue;
            if (second.start_s < first.start_s || second.conservative_transfer_bytes < intent.bytes) continue;
            auto plan = plan_from_contacts(intent, {first, second}, TransportPathKind::TemporalStoreCarryForward);
            if (deliverable(intent, plan)) plans.push_back(plan);
        }
    }
    std::sort(plans.begin(), plans.end(), [](const auto& a, const auto& b) {
        if (a.minimum_contact_margin_s != b.minimum_contact_margin_s) return a.minimum_contact_margin_s > b.minimum_contact_margin_s;
        if (a.predicted_finish_s != b.predicted_finish_s) return a.predicted_finish_s < b.predicted_finish_s;
        if (a.hops.size() != b.hops.size()) return a.hops.size() < b.hops.size();
        return a.hops.front().contact_id < b.hops.front().contact_id;
    });
    if (plans.size() > max_plans) plans.resize(max_plans);
    return plans;
}

}  // namespace gmat_comm
