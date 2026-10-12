//! Stub for deleted packages module.

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PackageManifest {
    pub package: PackageInfo,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PackageInfo {
    pub name: String,
    pub version: String,
    pub authors: Vec<String>,
}

#[derive(Debug, Clone)]
pub struct RegistryClient;

impl RegistryClient {
    pub fn default() -> Self {
        Self
    }
    pub fn package_to_value(_pkg: &PackageManifest) -> crate::value::Value {
        crate::value::Value::Null
    }
}

pub struct ImportResolver;

impl ImportResolver {
    pub fn new(_cwd: std::path::PathBuf) -> Self {
        Self
    }
    pub fn process_import<F>(
        &mut self,
        _items: Vec<crate::ast::ImportItem>,
        _source: String,
        _alias: Option<String>,
        _env: &mut crate::env::Env,
        _eval_fn: F,
    ) -> anyhow::Result<()>
    where
        F: Fn(&[crate::ast::Stmt], &mut crate::env::Env) -> anyhow::Result<crate::value::Value>,
    {
        Err(anyhow::anyhow!("import not supported"))
    }
    pub fn load_module<F>(
        &mut self,
        _source: String,
        _eval_fn: F,
    ) -> anyhow::Result<crate::env::Env>
    where
        F: Fn(&[crate::ast::Stmt], &mut crate::env::Env) -> anyhow::Result<crate::value::Value>,
    {
        Err(anyhow::anyhow!("module loading not supported"))
    }
}
