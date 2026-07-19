//! Shared execution-plan types used by the compiler cache, runtime and rules.

use serde::Serialize;

/// Risk level estimated from the IR's effect taxonomy.
#[derive(Debug, Clone, Serialize, PartialEq, Eq, PartialOrd, Ord)]
#[serde(rename_all = "snake_case")]
pub enum RiskLevel {
    Pure,
    ReadOnly,
    Mutating,
    Destructive,
}

/// Static preflight analysis for a compiled VerseShell program.
#[derive(Debug, Clone, Serialize)]
pub struct ExecutionPlan {
    pub builtins_called: Vec<String>,
    pub capabilities_required: Vec<String>,
    pub effects: Vec<String>,
    pub risk_level: RiskLevel,
    pub side_effects: Vec<String>,
    pub node_count: usize,
}
