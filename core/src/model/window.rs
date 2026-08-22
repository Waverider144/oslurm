use super::{NodeId, TimestampMs};

#[derive(Debug, Clone, PartialEq)]
pub struct PredictedComputeEnvelope {
    pub cpus_free: u32,
    pub ram_mb_free: u64,
}

#[derive(Debug, Clone, PartialEq)]
pub struct PredictedEnergyEnvelope {
    pub minimum_soc: f64,
    pub ending_soc: f64,
    pub safe_compute_energy_wh: f64,
}

#[derive(Debug, Clone, PartialEq)]
pub struct PredictedThermalEnvelope {
    pub minimum_headroom_c: f64,
    pub predicted_peak_temp_c: f64,
    pub safe_additional_compute_power_w: f64,
}

#[derive(Debug, Clone, PartialEq)]
pub struct PredictedConnectivityEnvelope {
    pub connected: bool,
    pub component: String,
}

#[derive(Debug, Clone, PartialEq)]
pub struct PredictedReliabilityEnvelope {
    pub survival_probability: f64,
}

#[derive(Debug, Clone, PartialEq)]
pub enum WindowTerminationCause {
    EclipseEntry,
    EclipseExit,
    IslAcquire,
    IslLoss,
    GroundAcquire,
    GroundLoss,
    EnergyReserveCrossing,
    ThermalLimitCrossing,
    ComputeReservationChange,
    Horizon,
}

#[derive(Debug, Clone, PartialEq)]
pub struct PredictedResourceWindow {
    pub window_id: String,
    pub node_id: NodeId,
    pub start_ms: TimestampMs,
    pub end_ms: TimestampMs,
    pub predicted_at_ms: TimestampMs,
    pub confidence: f32,
    pub compute: PredictedComputeEnvelope,
    pub energy: PredictedEnergyEnvelope,
    pub thermal: PredictedThermalEnvelope,
    pub connectivity: PredictedConnectivityEnvelope,
    pub reliability: PredictedReliabilityEnvelope,
    pub termination_causes: Vec<WindowTerminationCause>,
}

