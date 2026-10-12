//! MCP server module.
//!
//! Exposes VerseShell to external LLM agents via the Model Context Protocol
//! over stdio. Supports dual input framing (JSON-line and Content-Length),
//! JSON-RPC 2.0, and the `initialize` / `tools/list` / `tools/call` methods.
//!
//! T1 implements the protocol layer and three legacy tools (`health`, `exec`,
//! `list_commands`) inline. T2 introduces a `ToolRegistry` and migrates these
//! handlers; T3 adds task-oriented ACI tools on top of the registry.

pub mod protocol;
pub mod registry;
pub mod server;
pub mod tools;

pub use server::serve_stdio;
pub use server::serve_stdio_with_runtime;
