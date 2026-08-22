#[derive(Debug, Clone, Copy)]
pub struct ThermalConfig {
    pub soft_limit_c: f64,
    pub thermal_capacitance_j_per_c: f64,
    pub thermal_resistance_c_per_w: f64,
    pub equilibrium_temp_sunlight_c: f64,
    pub equilibrium_temp_eclipse_c: f64,
    pub compute_power_w: f64,
}

pub fn ending_temperature(start_c: f64, duration_s: f64, in_sunlight: bool, cfg: ThermalConfig) -> f64 {
    let env = if in_sunlight { cfg.equilibrium_temp_sunlight_c } else { cfg.equilibrium_temp_eclipse_c };
    let equilibrium = env + cfg.compute_power_w * cfg.thermal_resistance_c_per_w;
    let tau = cfg.thermal_capacitance_j_per_c * cfg.thermal_resistance_c_per_w;
    equilibrium + (start_c - equilibrium) * (-duration_s / tau).exp()
}

