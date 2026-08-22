use crate::model::{job::OrbitalJobSpec, window::PredictedResourceWindow};

pub fn feasible(job: &OrbitalJobSpec, window: &PredictedResourceWindow) -> bool {
    let runtime_ms = (job.execution.runtime_s * 1000.0) as i64;
    window.end_ms - window.start_ms >= runtime_ms
        && window.start_ms + runtime_ms <= job.submitted_at_ms + (job.temporal.deadline_s * 1000.0) as i64
        && window.compute.cpus_free >= job.requirements.cpus
        && window.compute.ram_mb_free >= job.requirements.ram_mb
        && window.energy.ending_soc >= job.energy.min_soc
        && window.thermal.predicted_peak_temp_c <= job.thermal.max_temp_c
}

