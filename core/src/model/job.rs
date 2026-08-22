use std::collections::HashMap;

use super::{JobId, TimestampMs};

#[derive(Debug, Clone, PartialEq)]
pub struct ExecutionSpec {
    pub runtime_s: f64,
    pub checkpoint_supported: bool,
}

#[derive(Debug, Clone, PartialEq)]
pub struct ResourceRequirements {
    pub cpus: u32,
    pub ram_mb: u64,
    pub accelerators: HashMap<String, u32>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct TemporalConstraints {
    pub deadline_s: f64,
}

#[derive(Debug, Clone, PartialEq)]
pub struct DataRequirements {
    pub labels: Vec<String>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct NetworkRequirements {
    pub required_connectivity: Option<String>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct EnergyConstraints {
    pub min_soc: f64,
}

#[derive(Debug, Clone, PartialEq)]
pub struct ThermalConstraints {
    pub max_temp_c: f64,
}

#[derive(Debug, Clone, PartialEq)]
pub struct ResiliencePolicy {
    pub replicas: u32,
    pub anti_affinity_domain: Option<String>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct SchedulingPreferences {
    pub prefer_sunlight: bool,
}

#[derive(Debug, Clone, PartialEq)]
pub struct OrbitalJobSpec {
    pub job_id: JobId,
    pub submitted_at_ms: TimestampMs,
    pub execution: ExecutionSpec,
    pub requirements: ResourceRequirements,
    pub temporal: TemporalConstraints,
    pub data: DataRequirements,
    pub network: NetworkRequirements,
    pub energy: EnergyConstraints,
    pub thermal: ThermalConstraints,
    pub resilience: ResiliencePolicy,
    pub preferences: SchedulingPreferences,
    pub labels: HashMap<String, String>,
}

