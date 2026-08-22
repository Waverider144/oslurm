use std::collections::HashMap;

use super::{NodeId, TimestampMs};

#[derive(Debug, Clone, PartialEq)]
pub struct OrbitState {
    pub position_eci_m: [f64; 3],
    pub velocity_eci_mps: [f64; 3],
    pub in_sunlight: bool,
}

#[derive(Debug, Clone, PartialEq)]
pub struct ComputeState {
    pub cpus_total: u32,
    pub cpus_free: u32,
    pub ram_mb_total: u64,
    pub ram_mb_free: u64,
    pub accelerators: HashMap<String, u32>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct EnergyState {
    pub battery_capacity_wh: f64,
    pub soc: f64,
    pub reserve_soc: f64,
}

#[derive(Debug, Clone, PartialEq)]
pub struct ThermalState {
    pub temperature_c: f64,
    pub soft_limit_c: f64,
    pub hard_limit_c: f64,
}

#[derive(Debug, Clone, PartialEq)]
pub struct LinkState {
    pub target: NodeId,
    pub bandwidth_bps: u64,
    pub latency_ms: f64,
}

#[derive(Debug, Clone, PartialEq)]
pub struct StorageState {
    pub free_mb: u64,
    pub data_labels: Vec<String>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct HealthState {
    pub schedulable: bool,
    pub reason: Option<String>,
}

pub type FailureDomains = HashMap<String, String>;

#[derive(Debug, Clone, PartialEq)]
pub struct SchedulerNodeState {
    pub drained: bool,
    pub reservations: Vec<String>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct OrbitalNodeState {
    pub node_id: NodeId,
    pub observed_at_ms: TimestampMs,
    pub orbit: OrbitState,
    pub compute: ComputeState,
    pub energy: EnergyState,
    pub thermal: ThermalState,
    pub links: Vec<LinkState>,
    pub storage: StorageState,
    pub health: HealthState,
    pub failure_domains: FailureDomains,
    pub scheduler: SchedulerNodeState,
    pub labels: HashMap<String, String>,
}

