//! Lightweight in-process RBAC used by the safety policy layer.

use serde::Deserialize;
use std::collections::{HashMap, HashSet};
use std::sync::RwLock;

/// Named role with additive effect/builtin permissions.
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

/// RBAC principal.
#[derive(Debug, Clone)]
pub struct User {
    pub id: String,
}

impl User {
    pub fn new(id: &str) -> Self {
        Self { id: id.to_string() }
    }
}

#[derive(Debug)]
pub struct RbacManager {
    roles: RwLock<HashMap<String, Role>>,
    users: RwLock<HashMap<String, User>>,
    assignments: RwLock<HashMap<String, HashSet<String>>>,
    direct_permissions: RwLock<HashMap<String, HashSet<String>>>,
}

impl RbacManager {
    pub fn new() -> Self {
        Self {
            roles: RwLock::new(HashMap::new()),
            users: RwLock::new(HashMap::new()),
            assignments: RwLock::new(HashMap::new()),
            direct_permissions: RwLock::new(HashMap::new()),
        }
    }

    pub fn from_config_str(text: &str) -> Result<(Self, Option<String>), String> {
        let config: RbacConfig = toml::from_str(text).map_err(|e| e.to_string())?;
        let manager = Self::new();
        for (name, role) in config.roles {
            manager.add_role(Role {
                name,
                permissions: role.permissions,
            });
        }
        for (id, user) in config.users {
            manager.add_user(User::new(&id))?;
            for role in user.roles {
                manager.assign_role(&id, &role)?;
            }
            for permission in user.permissions {
                manager.grant_permission(&id, &permission)?;
            }
        }
        Ok((manager, config.principal))
    }

    pub fn add_role(&self, role: Role) {
        self.roles.write().unwrap().insert(role.name.clone(), role);
    }
    pub fn add_user(&self, user: User) -> Result<(), String> {
        self.users
            .write()
            .map_err(|_| "users lock poisoned".to_string())?
            .insert(user.id.clone(), user);
        Ok(())
    }
    pub fn assign_role(&self, user_id: &str, role: &str) -> Result<(), String> {
        if !self
            .users
            .read()
            .map_err(|_| "users lock poisoned".to_string())?
            .contains_key(user_id)
        {
            return Err(format!("unknown user: {user_id}"));
        }
        if !self
            .roles
            .read()
            .map_err(|_| "roles lock poisoned".to_string())?
            .contains_key(role)
        {
            return Err(format!("unknown role: {role}"));
        }
        self.assignments
            .write()
            .map_err(|_| "assignments lock poisoned".to_string())?
            .entry(user_id.to_string())
            .or_default()
            .insert(role.to_string());
        Ok(())
    }

    pub fn grant_permission(&self, user_id: &str, permission: &str) -> Result<(), String> {
        if !self
            .users
            .read()
            .map_err(|_| "users lock poisoned".to_string())?
            .contains_key(user_id)
        {
            return Err(format!("unknown user: {user_id}"));
        }
        self.direct_permissions
            .write()
            .map_err(|_| "permissions lock poisoned".to_string())?
            .entry(user_id.to_string())
            .or_default()
            .insert(permission.to_string());
        Ok(())
    }

    pub fn check_permission(&self, user: &str, permission: &str) -> bool {
        let matches = |granted: &str| {
            granted == permission
                || granted == "*:*"
                || (granted == "effect:*" && permission.starts_with("effect:"))
                || (granted == "builtin:*" && permission.starts_with("builtin:"))
        };
        if self
            .direct_permissions
            .read()
            .ok()
            .and_then(|permissions| permissions.get(user).cloned())
            .map(|permissions| permissions.iter().any(|permission| matches(permission)))
            .unwrap_or(false)
        {
            return true;
        }
        let role_names = self
            .assignments
            .read()
            .ok()
            .and_then(|assignments| assignments.get(user).cloned())
            .unwrap_or_default();
        let roles = match self.roles.read() {
            Ok(roles) => roles,
            Err(_) => return false,
        };
        role_names
            .iter()
            .filter_map(|name| roles.get(name))
            .flat_map(|role| role.permissions.iter())
            .any(|permission| matches(permission))
    }
}

#[derive(Debug, Default, Deserialize)]
struct RbacConfig {
    #[serde(default)]
    principal: Option<String>,
    #[serde(default)]
    roles: HashMap<String, RoleConfig>,
    #[serde(default)]
    users: HashMap<String, UserConfig>,
}

#[derive(Debug, Default, Deserialize)]
struct RoleConfig {
    #[serde(default)]
    permissions: Vec<String>,
}

#[derive(Debug, Default, Deserialize)]
struct UserConfig {
    #[serde(default)]
    roles: Vec<String>,
    #[serde(default)]
    permissions: Vec<String>,
}
