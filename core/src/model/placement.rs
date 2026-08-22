use super::{JobId, NodeId, TimestampMs};

#[derive(Debug, Clone, PartialEq)]
pub struct PlacementCandidate {
    pub job_id: JobId,
    pub nodes: Vec<NodeId>,
    pub start_ms: TimestampMs,
    pub predicted_finish_ms: TimestampMs,
    pub score: f64,
    pub predicted_energy_wh: f64,
    pub predicted_peak_temp_c: f64,
    pub survival_probability: f64,
    pub violated_soft_preferences: Vec<String>,
}

