//! # VerseShell — Production-grade typed functional shell runtime for AI agents (v3 kernel)
//!
//! ## Core (always available)
//! - [`ast`] — Abstract syntax tree
//! - [`parser`] — Source text → AST
//! - [`value`] — Runtime value system
//! - [`types`] — Type lattice
//! - [`typecheck`] — Hindley-Milner type inference
//! - [`env`] — Environment and scope management
//! - [`ir`] — V2 IR layer (canonical, hashable, optimizable)
//! - [`capability`] — V2 capability-based security model
//!
//! ## Server (agent runtime)
//! - [`cache`] — Global AST/type/sys-snapshot cache
//! - [`runtime`] — Session pool + execution orchestration
//! - [`server`] — JSON-RPC stdio server for agents

pub mod ast;
pub mod env;
pub mod parser;
pub mod types;
pub mod value;
pub mod shell_features;
pub mod typecheck;
pub mod ir;
pub mod capability;

#[cfg(feature = "native")]
pub mod auth;
#[cfg(feature = "native")]
pub mod builtins;
#[cfg(feature = "native")]
pub mod cache;
#[cfg(feature = "native")]
pub mod config;
#[cfg(feature = "native")]
pub mod eval;
#[cfg(feature = "native")]
pub mod mcp;
#[cfg(feature = "native")]
pub mod modules;
#[cfg(feature = "native")]
pub mod os_tools;
#[cfg(feature = "native")]
pub mod packages;
#[cfg(feature = "native")]
pub mod repl;
#[cfg(feature = "native")]
pub mod runtime;
#[cfg(feature = "native")]
pub mod safety;
#[cfg(feature = "native")]
pub mod scheduler;
#[cfg(feature = "native")]
pub mod secure_config;
#[cfg(feature = "native")]
pub mod server;
#[cfg(feature = "native")]
pub mod syntax_kb;
#[cfg(feature = "native")]
pub mod tx;
#[cfg(feature = "native")]
pub mod transpile;
