//! ae-mcp: VerseShell MCP Server binary
//!
//! Implements the Model Context Protocol over stdio, exposing verseshell as
//! MCP tools for Codex, Claude Code, and other MCP clients.
//!
//! Runs on a dedicated tokio runtime (independent of `src/server.rs`, which
//! serves the legacy JSON-RPC protocol used by the `ae --server` mode).

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // Initialize tracing if RUST_LOG is set; otherwise stay silent on stderr
    // so stdio MCP framing on stdout is not polluted.
    let _ = tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("warn")),
        )
        .with_writer(std::io::stderr)
        .try_init();

    // MCP is an agent-facing production surface: an absent AETHER_CAPS is an
    // explicit empty allow-list, not unrestricted compatibility behavior.
    verseshell::capability::init_caps(None);

    verseshell::mcp::serve_stdio().await
}
