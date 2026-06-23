//! Minimal stub for RBAC types referenced by safety.rs.
//! Full RBAC is removed; these stubs keep the safety module compiling unchanged.

use std::collections::HashMap;

/// Stub role (RBAC has been pruned — authorization goes through policy + approval only).
#[derive(Debug, Clone)]
pub struct Role {
    pub name: String,
    pub permissions: Vec<String>,
}

impl Role {
    pub fn new(name: &str) -> Self {
        Self {
            name: name.to_string(),
            permissions: Vec::new(),
        }
    }
    pub fn with_permission(mut self, perm: &str) -> Self {
        self.permissions.push(perm.to_string());
        self
    }
}

/// Stub user.
#[derive(Debug, Clone)]
pub struct User {
    pub id: String,
}

impl User {
    pub fn new(id: &str) -> Self {
        Self {
            id: id.to_string(),
        }
    }
}

/// Stub RBAC manager — always returns no-grant (defer to policy).
#[derive(Debug)]
pub struct RbacManager {
    #[allow(dead_code)]
    roles: HashMap<String, Role>,
    #[allow(dead_code)]
    users: HashMap<String, User>,
}

impl RbacManager {
    pub fn new() -> Self {
        Self {
            roles: HashMap::new(),
            users: HashMap::new(),
        }
    }

    pub fn from_config_str(_text: &str) -> Result<(Self, Option<String>), String> {
        // RBAC config loading is a no-op in the pruned build.
        // Return an empty manager so safety.rs's init_rbac_from_env() doesn't error.
        Ok((Self::new(), None))
    }

    pub fn add_role(&self, _role: Role) {}
    pub fn add_user(&self, _user: User) -> Result<(), String> {
        Ok(())
    }
    pub fn assign_role(&self, _user_id: &str, _role: &str) -> Result<(), String> {
        Ok(())
    }
    pub fn check_permission(&self, _user: &str, _permission: &str) -> bool {
        false // Never grants — defer to policy always
    }
}
