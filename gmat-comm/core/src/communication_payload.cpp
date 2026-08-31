#include "gmat_comm/communication_payload.hpp"

#include <algorithm>
#include <cmath>
#include <utility>

namespace gmat_comm {

ProviderTerminalModel::ProviderTerminalModel(std::shared_ptr<CommunicationEnvelopeProvider> provider)
    : provider_(std::move(provider)) {}

LinkCapability ProviderTerminalModel::evaluate(const CommunicationEnvironmentState& env,
                                               const TerminalOperatingState& state,
                                               const LinkDemand& demand) const {
    CommunicationQuery query;
    query.range_m = env.range_m;
    query.relative_velocity_mps = env.relative_velocity_mps;
    query.temperature_c = state.temperature_c;
    query.terminal_power_cap_w = state.power_usage_w > 0.0 ? state.power_usage_w : 50.0;
    query.dose_rate_rad_s = env.radiation_dose_rate_rad_s;
    query.traffic_class = demand.traffic_class;
    LinkCapability capability;
    capability.geometrically_possible = env.line_of_sight;
    capability.terminal_available = state.available && !state.reserved;
    capability.bandwidth_bps = provider_->bandwidth(query);
    capability.one_way_latency_s = provider_->latency(query);
    capability.packet_loss = provider_->packet_loss(query);
    capability.bit_error_rate = provider_->bit_error_rate(query);
    capability.acquisition_time_s = provider_->acquisition_time_s(query);
    capability.survival_probability = provider_->link_survival_probability(query);
    capability.power_draw_w = provider_->power_draw_w(query);
    capability.valid_from_s = env.simulation_time_s + capability.acquisition_time_s.upper_bound;
    capability.valid_until_s = env.simulation_time_s + 60.0;
    return capability;
}

CommunicationPayload::CommunicationPayload(CommunicationPayloadProfile profile,
                                           std::shared_ptr<CommunicationTerminalModel> model)
    : model_(std::move(model)) {
    state_.node_id = profile.profile_id;
    state_.terminals = std::move(profile.terminals);
    state_.buffer = profile.buffer;
}

void CommunicationPayload::step(const LocalCommunicationEnvironment& env, double dt_s) {
    state_.observed_at_s += dt_s;
    for (auto& reservation : state_.reservations) {
        if (reservation.state == ReservationState::Accepted &&
            reservation.expires_at_s <= state_.observed_at_s) {
            reservation.state = ReservationState::Expired;
            if (state_.buffer.reserved_bytes >= reservation.bytes) {
                state_.buffer.reserved_bytes -= reservation.bytes;
            }
            for (auto& terminal : state_.terminals) {
                if (terminal.terminal_id == reservation.hop.source_terminal) terminal.state.reserved = false;
            }
        }
    }
    for (const auto& link : env.links) {
        LinkDemand demand;
        demand.bytes = 1;
        for (auto& terminal : state_.terminals) {
            auto cap = model_->evaluate(link, terminal.state, demand);
            if (cap.geometrically_possible && cap.terminal_available) {
                terminal.state.acquisition_state = AcquisitionState::Active;
                terminal.state.power_usage_w = cap.power_draw_w.nominal;
                break;
            }
        }
    }
}

CommunicationNodeState CommunicationPayload::state() const { return state_; }

const std::vector<CommunicationTerminal>& CommunicationPayload::terminals() const {
    return state_.terminals;
}

TransferId CommunicationPayload::enqueue_transfer(const TransferIntent& intent) {
    transfers_.push_back(intent);
    return intent.transfer_id;
}

bool CommunicationPayload::reserve(const LinkReservationRequest& request) {
    auto duplicate = std::find_if(state_.reservations.begin(), state_.reservations.end(), [&](const auto& item) {
        return item.reservation_id == request.reservation_id;
    });
    if (duplicate != state_.reservations.end()) return duplicate->state == ReservationState::Accepted;
    if (!terminal_free(request.hop.source_terminal)) return false;
    if (state_.buffer.capacity_bytes < state_.buffer.used_bytes + state_.buffer.reserved_bytes + request.bytes) return false;
    NetworkReservation reservation;
    reservation.reservation_id = request.reservation_id;
    reservation.transfer_id = request.transfer_id;
    reservation.hop = request.hop;
    reservation.bytes = request.bytes;
    reservation.bandwidth_bps = request.bandwidth_bps;
    reservation.created_at_s = request.now_s;
    reservation.expires_at_s = request.now_s + request.lease_s;
    reservation.state = ReservationState::Accepted;
    state_.buffer.reserved_bytes += request.bytes;
    for (auto& terminal : state_.terminals) {
        if (terminal.terminal_id == request.hop.source_terminal) terminal.state.reserved = true;
    }
    state_.reservations.push_back(reservation);
    return true;
}

bool CommunicationPayload::commit(ReservationId reservation_id) {
    for (auto& reservation : state_.reservations) {
        if (reservation.reservation_id == reservation_id && reservation.state == ReservationState::Accepted) {
            reservation.state = ReservationState::Committed;
            return true;
        }
    }
    return false;
}

bool CommunicationPayload::release(ReservationId reservation_id) {
    for (auto& reservation : state_.reservations) {
        if (reservation.reservation_id != reservation_id) continue;
        if (state_.buffer.reserved_bytes >= reservation.bytes) state_.buffer.reserved_bytes -= reservation.bytes;
        for (auto& terminal : state_.terminals) {
            if (terminal.terminal_id == reservation.hop.source_terminal) terminal.state.reserved = false;
        }
        reservation.state = ReservationState::Aborted;
        return true;
    }
    return false;
}

CommunicationForecast CommunicationPayload::forecast(const CommunicationForecastRequest& request) const {
    CommunicationForecast forecast;
    forecast.valid_from_s = request.start_s;
    forecast.valid_until_s = request.start_s + request.horizon_s;
    return forecast;
}

bool CommunicationPayload::terminal_free(const TerminalId& terminal_id) const {
    auto terminal = std::find_if(state_.terminals.begin(), state_.terminals.end(), [&](const auto& item) {
        return item.terminal_id == terminal_id;
    });
    return terminal != state_.terminals.end() && terminal->state.available && !terminal->state.reserved;
}

EnvelopeValue AnalyticEnvelopeProvider::bandwidth(const CommunicationQuery& query) const {
    const double range_km = std::max(1.0, query.range_m / 1000.0);
    const double nominal = std::max(1.0e6, 2.0e9 / (1.0 + range_km / 2000.0));
    return {nominal, nominal * 0.82, nominal * 1.08, 0.8, false};
}

EnvelopeValue AnalyticEnvelopeProvider::latency(const CommunicationQuery& query) const {
    const double c = 299792458.0;
    const double nominal = query.range_m / c;
    return {nominal, nominal, nominal * 1.1, 0.95, false};
}

EnvelopeValue AnalyticEnvelopeProvider::packet_loss(const CommunicationQuery& query) const {
    const double loss = std::min(0.2, 0.001 + query.range_m / 1.0e10);
    return {loss, loss * 0.5, loss * 1.5, 0.75, false};
}

EnvelopeValue AnalyticEnvelopeProvider::bit_error_rate(const CommunicationQuery&) const {
    return {1e-9, 1e-10, 1e-8, 0.7, false};
}

EnvelopeValue AnalyticEnvelopeProvider::acquisition_time_s(const CommunicationQuery&) const {
    return {2.0, 1.0, 4.0, 0.8, false};
}

EnvelopeValue AnalyticEnvelopeProvider::link_survival_probability(const CommunicationQuery& query) const {
    const double survival = std::max(0.5, 0.999 - query.range_m / 1.0e10);
    return {survival, survival - 0.02, 1.0, 0.8, false};
}

EnvelopeValue AnalyticEnvelopeProvider::power_draw_w(const CommunicationQuery&) const {
    return {45.0, 38.0, 52.0, 0.8, false};
}

Provenance AnalyticEnvelopeProvider::provenance() const {
    return {"analytic_reference", "generic_terminal", "v1", "baseline", ""};
}

}  // namespace gmat_comm
