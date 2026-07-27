//! Workspace trash for agent-mode file.remove recovery.

use crate::safety;
use serde::{Deserialize, Serialize};
use serde_json::json;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

#[derive(Debug, Serialize, Deserialize)]
struct TrashMeta {
    original: String,
    is_dir: bool,
    created_at: u64,
}

fn trash_root() -> PathBuf {
    safety::workspace_root().join(".ae").join("trash")
}

fn now_secs() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

/// Move `path` into workspace trash. Returns restore token `trash://{id}`.
pub fn move_to_trash(path: &Path) -> Result<String, String> {
    let root = trash_root();
    fs::create_dir_all(&root).map_err(|e| format!("cannot create trash: {e}"))?;
    let id = format!("{}-{}", now_secs(), &uuid::Uuid::new_v4().to_string()[..8]);
    let entry = root.join(&id);
    fs::create_dir_all(&entry).map_err(|e| format!("cannot create trash entry: {e}"))?;
    let payload = entry.join("payload");
    let is_dir = path.is_dir();
    if is_dir {
        copy_tree(path, &payload).map_err(|e| format!("trash copy tree: {e}"))?;
        fs::remove_dir_all(path).map_err(|e| format!("trash remove dir: {e}"))?;
    } else {
        fs::rename(path, &payload)
            .or_else(|_| {
                fs::copy(path, &payload)?;
                fs::remove_file(path)?;
                Ok(())
            })
            .map_err(|e: std::io::Error| format!("trash move file: {e}"))?;
    }
    let meta = TrashMeta {
        original: path.to_string_lossy().to_string(),
        is_dir,
        created_at: now_secs(),
    };
    let meta_path = entry.join("meta.json");
    fs::write(
        &meta_path,
        serde_json::to_string_pretty(&meta).unwrap_or_else(|_| "{}".into()),
    )
    .map_err(|e| format!("trash meta: {e}"))?;
    Ok(format!("trash://{id}"))
}

/// Restore a trash token. Returns restored absolute path.
pub fn restore(token: &str) -> Result<PathBuf, String> {
    let id = token
        .strip_prefix("trash://")
        .ok_or_else(|| "restore_token must start with trash://".to_string())?;
    if id.is_empty() || id.contains('/') || id.contains('\\') || id.contains("..") {
        return Err("invalid restore_token".into());
    }
    let entry = trash_root().join(id);
    let meta_path = entry.join("meta.json");
    let meta_bytes = fs::read(&meta_path).map_err(|e| format!("trash not found: {e}"))?;
    let meta: TrashMeta =
        serde_json::from_slice(&meta_bytes).map_err(|e| format!("corrupt trash meta: {e}"))?;
    let original = PathBuf::from(&meta.original);
    if let Some(parent) = original.parent() {
        fs::create_dir_all(parent).map_err(|e| format!("restore parent: {e}"))?;
    }
    if original.exists() {
        return Err(format!(
            "restore target already exists: {}",
            original.display()
        ));
    }
    let payload = entry.join("payload");
    if meta.is_dir {
        copy_tree(&payload, &original).map_err(|e| format!("restore tree: {e}"))?;
    } else {
        fs::rename(&payload, &original)
            .or_else(|_| {
                fs::copy(&payload, &original)?;
                fs::remove_file(&payload)?;
                Ok(())
            })
            .map_err(|e: std::io::Error| format!("restore file: {e}"))?;
    }
    let _ = fs::remove_dir_all(&entry);
    let _ = safety::audit(
        "tx.restore",
        crate::safety::Effect::WriteLocal,
        "restored",
        &meta.original,
        json!({"restore_token": token}),
    );
    Ok(original)
}

fn copy_tree(src: &Path, dst: &Path) -> std::io::Result<()> {
    fs::create_dir_all(dst)?;
    for entry in fs::read_dir(src)? {
        let entry = entry?;
        let ft = entry.file_type()?;
        let from = entry.path();
        let to = dst.join(entry.file_name());
        if ft.is_dir() {
            copy_tree(&from, &to)?;
        } else if ft.is_file() {
            fs::copy(&from, &to)?;
        }
    }
    Ok(())
}
