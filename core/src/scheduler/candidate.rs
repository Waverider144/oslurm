use crate::model::{job::OrbitalJobSpec, placement::PlacementCandidate, window::PredictedResourceWindow};

use super::{feasible::feasible, score::score};

pub fn generate_candidates(job: &OrbitalJobSpec, windows: &[PredictedResourceWindow]) -> Vec<PlacementCandidate> {
    let mut out: Vec<_> = windows
        .iter()
        .filter(|w| feasible(job, w))
        .map(|w| PlacementCandidate {
            job_id: job.job_id.clone(),
            nodes: vec![w.node_id.clone()],
            start_ms: w.start_ms,
            predicted_finish_ms: w.start_ms + (job.execution.runtime_s * 1000.0) as i64,
            score: score(job, w),
            predicted_energy_wh: w.energy.safe_compute_energy_wh,
            predicted_peak_temp_c: w.thermal.predicted_peak_temp_c,
            survival_probability: w.reliability.survival_probability,
            violated_soft_preferences: Vec::new(),
        })
        .collect();
    out.sort_by(|a, b| b.score.partial_cmp(&a.score).unwrap());
    out
}

