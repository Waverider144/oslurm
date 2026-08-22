use crate::model::{job::OrbitalJobSpec, window::PredictedResourceWindow};

pub fn score(job: &OrbitalJobSpec, window: &PredictedResourceWindow) -> f64 {
    let energy_margin = window.energy.ending_soc - job.energy.min_soc;
    let thermal_margin = job.thermal.max_temp_c - window.thermal.predicted_peak_temp_c;
    0.35 * energy_margin + 0.02 * thermal_margin + 0.35 * window.reliability.survival_probability
}

