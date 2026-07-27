//! Typed Agent operations beyond exec.run / result.query.
//!
//! All specs are registered into [`crate::operation::OperationRegistry`].

mod common;
mod file;
mod meta;
mod repo;
mod runtime_ops;
mod test_ops;
mod trash;
mod tx_ops;

use crate::operation::OperationSpec;

/// Every 1.0 ACI operation except core exec/result (registered in operation.rs).
pub fn all_specs() -> Vec<OperationSpec> {
    let mut specs = Vec::new();
    specs.extend(file::specs());
    specs.extend(tx_ops::specs());
    specs.extend(meta::specs());
    specs.extend(runtime_ops::specs());
    specs.extend(repo::specs());
    specs.extend(test_ops::specs());
    specs
}
