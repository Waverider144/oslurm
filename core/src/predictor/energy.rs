#[derive(Debug, Clone, Copy)]
pub struct PowerConfig {
    pub battery_capacity_wh: f64,
    pub reserve_soc: f64,
    pub solar_generation_w: f64,
    pub baseline_load_w: f64,
    pub communication_load_w: f64,
    pub compute_load_w: f64,
}

pub fn ending_soc(start_soc: f64, duration_s: f64, in_sunlight: bool, cfg: PowerConfig) -> f64 {
    let generation = if in_sunlight { cfg.solar_generation_w } else { 0.0 };
    let load = cfg.baseline_load_w + cfg.communication_load_w + cfg.compute_load_w;
    let delta_wh = (generation - load) * duration_s / 3600.0;
    ((start_soc * cfg.battery_capacity_wh + delta_wh) / cfg.battery_capacity_wh).clamp(0.0, 1.0)
}

