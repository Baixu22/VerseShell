//! Stub for deleted mcp module.

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct McpConfig {
    pub host: String,
    pub port: u16,
    pub enable_cors: bool,
    pub safety_level: crate::os_tools::SafetyLevel,
    pub allow_admin: bool,
}

pub struct McpServer;

impl McpServer {
    pub fn new() -> Self {
        Self
    }
    pub fn with_config(_config: McpConfig) -> Self {
        Self
    }
    pub fn list_tools(&self) -> Vec<String> {
        Vec::new()
    }
    pub fn serve_stdio(&self) -> anyhow::Result<()> {
        Err(anyhow::anyhow!("MCP server not available"))
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct McpToolCall {
    pub tool: String,
    pub args: serde_json::Value,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct McpContent {
    pub text: String,
}

pub struct McpServerConfig {
    pub host: String,
    pub port: u16,
    pub enable_cors: bool,
    pub safety_level: crate::os_tools::SafetyLevel,
    pub allow_admin: bool,
}

pub mod server {
    use super::*;
    pub async fn start_mcp_server(_config: McpServerConfig) -> anyhow::Result<()> {
        Err(anyhow::anyhow!("MCP server not available"))
    }
}
