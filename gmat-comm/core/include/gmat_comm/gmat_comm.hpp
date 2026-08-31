#pragma once

#include <array>
#include <cstdint>
#include <map>
#include <memory>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

namespace gmat_comm {

using NodeId = std::string;
using TerminalId = std::string;
using TransferId = std::string;
using ReservationId = std::string;
using ContactId = std::string;

struct EnvelopeValue {
    double nominal = 0.0;
    double lower_bound = 0.0;
    double upper_bound = 0.0;
    double confidence = 1.0;
    bool extrapolated = false;
};

struct CommunicationEnvironmentState {
    double simulation_time_s = 0.0;
    std::array<double, 3> source_position_eci_m{0.0, 0.0, 0.0};
    std::array<double, 3> source_velocity_eci_mps{0.0, 0.0, 0.0};
    std::array<double, 3> destination_position_eci_m{0.0, 0.0, 0.0};
    std::array<double, 3> destination_velocity_eci_mps{0.0, 0.0, 0.0};
    double range_m = 0.0;
    double relative_velocity_mps = 0.0;
    bool line_of_sight = false;
    double occultation_margin_m = 0.0;
    double source_sun_angle_rad = 0.0;
    double destination_sun_angle_rad = 0.0;
    double optional_atmospheric_path_length_m = 0.0;
    double radiation_dose_rate_rad_s = 0.0;
};

struct CommunicationQuery {
    double range_m = 0.0;
    double relative_velocity_mps = 0.0;
    double pointing_error_rad = 0.0;
    double incidence_angle_rad = 0.0;
    double temperature_c = 25.0;
    double terminal_power_cap_w = 0.0;
    double cumulative_dose_rad = 0.0;
    double dose_rate_rad_s = 0.0;
    double optional_atmospheric_loss_db = 0.0;
    std::string modulation = "adaptive";
    std::string coding = "adaptive";
    std::string traffic_class = "bulk";
};

struct Provenance {
    std::string source;
    std::string terminal_model;
    std::string revision;
    std::string campaign;
    std::string manifest_sha256;
};

class CommunicationEnvelopeProvider {
public:
    virtual ~CommunicationEnvelopeProvider() = default;
    virtual EnvelopeValue bandwidth(const CommunicationQuery& query) const = 0;
    virtual EnvelopeValue latency(const CommunicationQuery& query) const = 0;
    virtual EnvelopeValue packet_loss(const CommunicationQuery& query) const = 0;
    virtual EnvelopeValue bit_error_rate(const CommunicationQuery& query) const = 0;
    virtual EnvelopeValue acquisition_time_s(const CommunicationQuery& query) const = 0;
    virtual EnvelopeValue link_survival_probability(const CommunicationQuery& query) const = 0;
    virtual EnvelopeValue power_draw_w(const CommunicationQuery& query) const = 0;
    virtual Provenance provenance() const = 0;
};

enum class TerminalKind { Optical, RF, Hybrid, Custom };
enum class LinkKind { ComputeToCompute, ComputeToCommunication, CommunicationToCommunication, CommunicationToGround, ComputeToGround, Custom };
enum class AcquisitionState { Idle, Acquiring, Active, Lost };
enum class DeliverySemantics { BestEffort, DeadlineBound, Reliable, CustodyTransfer };
enum class TransferPriority { Low = 0, Normal = 1, High = 2, Critical = 3 };
enum class ReservationState { Proposed, Accepted, Committed, Active, Completed, Expired, Aborted };
enum class TransportPathKind { Continuous, TemporalStoreCarryForward };

struct TerminalOperatingState {
    bool available = true;
    std::optional<NodeId> current_peer;
    AcquisitionState acquisition_state = AcquisitionState::Idle;
    double power_usage_w = 0.0;
    double temperature_c = 25.0;
    bool reserved = false;
};

struct CommunicationTerminal {
    TerminalId terminal_id;
    TerminalKind kind = TerminalKind::Optical;
    std::string profile_id = "generic";
    double max_power_w = 50.0;
    TerminalOperatingState state;
};

struct LinkDemand {
    uint64_t bytes = 0;
    double deadline_s = 0.0;
    std::string traffic_class = "bulk";
};

struct LinkCapability {
    bool geometrically_possible = false;
    bool terminal_available = false;
    EnvelopeValue bandwidth_bps;
    EnvelopeValue one_way_latency_s;
    EnvelopeValue packet_loss;
    EnvelopeValue bit_error_rate;
    EnvelopeValue acquisition_time_s;
    EnvelopeValue survival_probability;
    EnvelopeValue power_draw_w;
    double valid_from_s = 0.0;
    double valid_until_s = 0.0;
};

class CommunicationTerminalModel {
public:
    virtual ~CommunicationTerminalModel() = default;
    virtual LinkCapability evaluate(const CommunicationEnvironmentState& env,
                                    const TerminalOperatingState& state,
                                    const LinkDemand& demand) const = 0;
};

class ProviderTerminalModel final : public CommunicationTerminalModel {
public:
    explicit ProviderTerminalModel(std::shared_ptr<CommunicationEnvelopeProvider> provider);
    LinkCapability evaluate(const CommunicationEnvironmentState& env,
                            const TerminalOperatingState& state,
                            const LinkDemand& demand) const override;
private:
    std::shared_ptr<CommunicationEnvelopeProvider> provider_;
};

struct BufferState {
    uint64_t capacity_bytes = 0;
    uint64_t used_bytes = 0;
    uint64_t reserved_bytes = 0;
};

struct TransferIntent {
    TransferId transfer_id;
    NodeId source;
    NodeId destination;
    uint64_t bytes = 0;
    double earliest_start_s = 0.0;
    std::optional<double> deadline_s;
    TransferPriority priority = TransferPriority::Normal;
    DeliverySemantics delivery = DeliverySemantics::BestEffort;
};

struct ContactWindow {
    ContactId contact_id;
    NodeId source;
    NodeId destination;
    double start_s = 0.0;
    double end_s = 0.0;
    LinkKind kind = LinkKind::CommunicationToCommunication;
    uint64_t minimum_bandwidth_bps = 0;
    uint64_t conservative_transfer_bytes = 0;
    double latency_upper_bound_ms = 0.0;
    double survival_probability = 1.0;
    double confidence = 1.0;
    TerminalId source_terminal;
    TerminalId destination_terminal;
    double acquisition_delay_s = 0.0;
};

struct TransferHop {
    NodeId source;
    NodeId destination;
    ContactId contact_id;
    double start_s = 0.0;
    double end_s = 0.0;
    uint64_t reserved_bytes = 0;
    TerminalId source_terminal;
    TerminalId destination_terminal;
};

struct TransferPlan {
    TransferId transfer_id;
    TransportPathKind path_kind = TransportPathKind::Continuous;
    std::vector<TransferHop> hops;
    double earliest_start_s = 0.0;
    double predicted_finish_s = 0.0;
    uint64_t transferable_bytes_lower_bound = 0;
    uint64_t bottleneck_bandwidth_bps = 0;
    double end_to_end_latency_ms = 0.0;
    double minimum_contact_margin_s = 0.0;
    double survival_probability = 1.0;
    double confidence = 1.0;
    double control_plane_cost = 0.0;
    std::optional<double> energy_cost_j;
};

struct NetworkReservation {
    ReservationId reservation_id;
    TransferId transfer_id;
    TransferHop hop;
    uint64_t bytes = 0;
    uint64_t bandwidth_bps = 0;
    double created_at_s = 0.0;
    double expires_at_s = 0.0;
    ReservationState state = ReservationState::Proposed;
};

struct CommunicationNodeState {
    NodeId node_id;
    double observed_at_s = 0.0;
    std::vector<CommunicationTerminal> terminals;
    BufferState buffer;
    std::vector<NetworkReservation> reservations;
    std::map<std::string, std::string> failure_domains;
};

struct CommunicationPayloadProfile {
    std::string profile_id = "generic_relay";
    std::vector<CommunicationTerminal> terminals;
    BufferState buffer;
};

struct LocalCommunicationEnvironment {
    std::vector<CommunicationEnvironmentState> links;
};

struct LinkReservationRequest {
    ReservationId reservation_id;
    TransferId transfer_id;
    TransferHop hop;
    uint64_t bytes = 0;
    uint64_t bandwidth_bps = 0;
    double now_s = 0.0;
    double lease_s = 5.0;
};

struct CommunicationForecastRequest {
    double start_s = 0.0;
    double horizon_s = 600.0;
};

struct CommunicationForecast {
    double valid_from_s = 0.0;
    double valid_until_s = 0.0;
    std::vector<ContactWindow> contacts;
};

class CommunicationPayload {
public:
    explicit CommunicationPayload(CommunicationPayloadProfile profile,
                                  std::shared_ptr<CommunicationTerminalModel> model);
    void step(const LocalCommunicationEnvironment& env, double dt_s);
    CommunicationNodeState state() const;
    const std::vector<CommunicationTerminal>& terminals() const;
    TransferId enqueue_transfer(const TransferIntent& intent);
    bool reserve(const LinkReservationRequest& request);
    bool commit(ReservationId reservation);
    bool release(ReservationId reservation);
    CommunicationForecast forecast(const CommunicationForecastRequest& request) const;
private:
    bool terminal_free(const TerminalId& terminal) const;
    CommunicationNodeState state_;
    std::shared_ptr<CommunicationTerminalModel> model_;
    std::vector<TransferIntent> transfers_;
};

class AnalyticEnvelopeProvider final : public CommunicationEnvelopeProvider {
public:
    EnvelopeValue bandwidth(const CommunicationQuery& query) const override;
    EnvelopeValue latency(const CommunicationQuery& query) const override;
    EnvelopeValue packet_loss(const CommunicationQuery& query) const override;
    EnvelopeValue bit_error_rate(const CommunicationQuery& query) const override;
    EnvelopeValue acquisition_time_s(const CommunicationQuery& query) const override;
    EnvelopeValue link_survival_probability(const CommunicationQuery& query) const override;
    EnvelopeValue power_draw_w(const CommunicationQuery& query) const override;
    Provenance provenance() const override;
};

class FileEnvelopeProvider final : public CommunicationEnvelopeProvider {
public:
    explicit FileEnvelopeProvider(const std::string& manifest_path);
    EnvelopeValue bandwidth(const CommunicationQuery& query) const override;
    EnvelopeValue latency(const CommunicationQuery& query) const override;
    EnvelopeValue packet_loss(const CommunicationQuery& query) const override;
    EnvelopeValue bit_error_rate(const CommunicationQuery& query) const override;
    EnvelopeValue acquisition_time_s(const CommunicationQuery& query) const override;
    EnvelopeValue link_survival_probability(const CommunicationQuery& query) const override;
    EnvelopeValue power_draw_w(const CommunicationQuery& query) const override;
    Provenance provenance() const override;
private:
    EnvelopeValue interpolate(const std::vector<std::pair<double, EnvelopeValue>>& rows,
                              double range_m) const;
    std::string policy_ = "reject";
    Provenance provenance_;
    std::vector<std::pair<double, EnvelopeValue>> bandwidth_;
    std::vector<std::pair<double, EnvelopeValue>> latency_;
    std::vector<std::pair<double, EnvelopeValue>> packet_loss_;
    std::vector<std::pair<double, EnvelopeValue>> acquisition_;
    std::vector<std::pair<double, EnvelopeValue>> power_;
};

std::vector<TransferPlan> continuous_plans(const TransferIntent& intent,
                                           const std::vector<ContactWindow>& contacts,
                                           std::size_t max_plans);
std::vector<TransferPlan> temporal_plans(const TransferIntent& intent,
                                         const std::vector<ContactWindow>& contacts,
                                         const BufferState& buffer,
                                         std::size_t max_plans);

}  // namespace gmat_comm
