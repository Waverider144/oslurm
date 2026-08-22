use crate::model::{NodeId, TimestampMs};

#[derive(Debug, Clone, PartialEq)]
pub struct PredictedEdge {
    pub source: NodeId,
    pub target: NodeId,
    pub valid_from_ms: TimestampMs,
    pub valid_until_ms: TimestampMs,
    pub min_bandwidth_bps: u64,
    pub worst_latency_ms: f64,
    pub confidence: f32,
}

