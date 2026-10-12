//! Stub for deleted os_tools module. Provides minimal type definitions
//! needed by builtins that can't be easily deleted.

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OSTool {
    pub name: String,
    pub description: String,
    pub category: ToolCategory,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum ToolCategory {
    FileOps,
    SystemInfo,
    Network,
    Process,
    Text,
    Data,
    Other,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum SafetyLevel {
    Safe,
    Caution,
    Dangerous,
    Critical,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum OperatingSystem {
    Windows,
    Linux,
    MacOs,
    Bsd,
    Ios,
    Android,
}

impl OperatingSystem {
    pub fn current() -> Self {
        match std::env::consts::OS {
            "windows" => Self::Windows,
            "linux" => Self::Linux,
            "macos" => Self::MacOs,
            _ => Self::Linux,
        }
    }
}

pub struct OSToolsDatabase;

impl OSToolsDatabase {
    pub fn new() -> Self {
        Self
    }
    pub fn all_tools(&self) -> Vec<&OSTool> {
        Vec::new()
    }
}

pub fn execute_tool_safe(_name: &str, _args: &[String]) -> Result<String, String> {
    Err("tool execution not available".into())
}
