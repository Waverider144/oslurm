#[derive(Debug, Clone, PartialEq, Eq)]
pub enum OccultingBody {
    Earth,
    Moon,
    Named(String),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum VisibilityRejectionReason {
    None,
    EarthOccultation,
    OtherBodyOccultation,
    SourceFovViolation,
    DestinationFovViolation,
    SourcePointingUnavailable,
    DestinationPointingUnavailable,
    InvalidGeometry,
    Unsupported,
    Unknown,
}

#[derive(Debug, Clone, PartialEq)]
pub struct VisibilityQuery {
    pub source_id: String,
    pub destination_id: String,
    pub epoch_a1mjd: f64,
    pub require_source_fov: bool,
    pub require_destination_fov: bool,
    pub source_terminal_id: Option<String>,
    pub destination_terminal_id: Option<String>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct VisibilityResult {
    pub geometrically_visible: bool,
    pub earth_occulted: bool,
    pub occulting_body: Option<String>,
    pub source_fov_ok: bool,
    pub destination_fov_ok: bool,
    pub source_fov_margin_rad: Option<f64>,
    pub destination_fov_margin_rad: Option<f64>,
    pub limb_clearance_m: Option<f64>,
    pub reason: VisibilityRejectionReason,
    pub confidence: f64,
}

#[derive(Debug, Clone, PartialEq)]
pub struct VisibilityWindow {
    pub start_s: f64,
    pub end_s: f64,
    pub result: VisibilityResult,
}

#[derive(Debug, Clone, PartialEq)]
pub struct VisibilityWindowQuery {
    pub source_id: String,
    pub destination_id: String,
    pub start_s: f64,
    pub end_s: f64,
    pub tolerance_s: f64,
}

pub trait VisibilityProvider {
    fn evaluate(&self, query: &VisibilityQuery) -> Result<VisibilityResult, String>;
    fn windows(&self, query: &VisibilityWindowQuery) -> Result<Vec<VisibilityWindow>, String>;
}

pub fn build_network_edge_guard(visibility: &VisibilityResult) -> Result<(), String> {
    if visibility.geometrically_visible {
        Ok(())
    } else {
        Err(format!("network edge rejected by visibility: {:?}", visibility.reason))
    }
}
