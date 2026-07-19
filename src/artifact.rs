//! Workspace-scoped, content-addressed result artifacts.

use anyhow::{anyhow, Context, Result};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

pub const DEFAULT_TTL: Duration = Duration::from_secs(24 * 60 * 60);
pub const DEFAULT_MAX_TOTAL_BYTES: u64 = 512 * 1024 * 1024;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ArtifactMetadata {
    pub handle: String,
    pub digest: String,
    pub bytes: u64,
    pub encoding: String,
    pub stream: String,
    pub origin: String,
    pub agent: String,
    pub workspace: String,
    pub created_at: u64,
    pub expires_at: u64,
}

#[derive(Debug, Clone)]
pub struct StoredArtifact {
    pub metadata: ArtifactMetadata,
    pub path: PathBuf,
}

#[derive(Debug, Clone)]
pub struct ArtifactStore {
    root: PathBuf,
    workspace: PathBuf,
    ttl: Duration,
    max_total_bytes: u64,
}

impl ArtifactStore {
    pub fn new(workspace: impl AsRef<Path>) -> Result<Self> {
        Self::with_limits(workspace, DEFAULT_TTL, DEFAULT_MAX_TOTAL_BYTES)
    }

    pub fn with_limits(
        workspace: impl AsRef<Path>,
        ttl: Duration,
        max_total_bytes: u64,
    ) -> Result<Self> {
        let workspace = workspace.as_ref().to_path_buf();
        fs::create_dir_all(&workspace)
            .with_context(|| format!("cannot create workspace {}", workspace.display()))?;
        let workspace = workspace.canonicalize().unwrap_or(workspace);
        let root = workspace.join(".ae").join("results");
        fs::create_dir_all(&root)
            .with_context(|| format!("cannot create artifact store {}", root.display()))?;
        let store = Self {
            root,
            workspace,
            ttl,
            max_total_bytes,
        };
        store.cleanup()?;
        Ok(store)
    }

    pub fn root(&self) -> &Path {
        &self.root
    }

    pub fn store(
        &self,
        bytes: &[u8],
        encoding: &str,
        stream: &str,
        origin: &str,
        agent: &str,
    ) -> Result<StoredArtifact> {
        let digest = hex::encode(Sha256::digest(bytes));
        let handle = format!("result://sha256/{digest}");
        let data_path = self.root.join(format!("{digest}.bin"));
        let meta_path = self.root.join(format!("{digest}.json"));

        if !data_path.exists() {
            let tmp = self
                .root
                .join(format!(".{digest}.{}.tmp", std::process::id()));
            fs::write(&tmp, bytes)?;
            match fs::rename(&tmp, &data_path) {
                Ok(()) => {}
                Err(e) if data_path.exists() => {
                    let _ = fs::remove_file(&tmp);
                    let _ = e;
                }
                Err(e) => return Err(e.into()),
            }
        }

        let now = now_secs();
        let metadata = ArtifactMetadata {
            handle,
            digest,
            bytes: bytes.len() as u64,
            encoding: encoding.to_string(),
            stream: stream.to_string(),
            origin: origin.to_string(),
            agent: agent.to_string(),
            workspace: display_path(&self.workspace),
            created_at: now,
            expires_at: now.saturating_add(self.ttl.as_secs()),
        };
        let encoded = serde_json::to_vec_pretty(&metadata)?;
        fs::write(meta_path, encoded)?;
        self.cleanup()?;

        Ok(StoredArtifact {
            metadata,
            path: data_path,
        })
    }

    pub fn load(&self, handle: &str) -> Result<(ArtifactMetadata, Vec<u8>)> {
        let digest = parse_handle(handle)?;
        let meta_path = self.root.join(format!("{digest}.json"));
        let data_path = self.root.join(format!("{digest}.bin"));
        if !meta_path.exists() || !data_path.exists() {
            return Err(anyhow!("E_RESULT_NOT_FOUND: artifact does not exist"));
        }
        let metadata: ArtifactMetadata = serde_json::from_slice(&fs::read(&meta_path)?)?;
        if metadata.workspace != display_path(&self.workspace) {
            return Err(anyhow!(
                "E_RESULT_WORKSPACE: artifact belongs to another workspace"
            ));
        }
        if metadata.expires_at <= now_secs() {
            let _ = fs::remove_file(meta_path);
            let _ = fs::remove_file(data_path);
            return Err(anyhow!("E_RESULT_EXPIRED: artifact has expired"));
        }
        Ok((metadata, fs::read(data_path)?))
    }

    pub fn metadata(&self, handle: &str) -> Result<ArtifactMetadata> {
        self.load(handle).map(|(metadata, _)| metadata)
    }

    pub fn cleanup(&self) -> Result<()> {
        let now = now_secs();
        let mut entries: Vec<(ArtifactMetadata, PathBuf, PathBuf)> = Vec::new();
        for entry in fs::read_dir(&self.root)? {
            let entry = entry?;
            let path = entry.path();
            if path.extension().and_then(|s| s.to_str()) != Some("json") {
                continue;
            }
            let metadata: ArtifactMetadata = match fs::read(&path)
                .ok()
                .and_then(|b| serde_json::from_slice(&b).ok())
            {
                Some(m) => m,
                None => {
                    let _ = fs::remove_file(path);
                    continue;
                }
            };
            let data_path = self.root.join(format!("{}.bin", metadata.digest));
            if metadata.expires_at <= now || !data_path.exists() {
                let _ = fs::remove_file(path);
                let _ = fs::remove_file(data_path);
                continue;
            }
            entries.push((metadata, path, data_path));
        }

        entries.sort_by_key(|(metadata, _, _)| metadata.created_at);
        let mut total: u64 = entries.iter().map(|(metadata, _, _)| metadata.bytes).sum();
        for (metadata, meta_path, data_path) in entries {
            if total <= self.max_total_bytes {
                break;
            }
            let _ = fs::remove_file(meta_path);
            let _ = fs::remove_file(data_path);
            total = total.saturating_sub(metadata.bytes);
        }
        Ok(())
    }
}

pub fn parse_handle(handle: &str) -> Result<&str> {
    let digest = handle
        .strip_prefix("result://sha256/")
        .ok_or_else(|| anyhow!("E_RESULT_HANDLE: invalid artifact handle"))?;
    if digest.len() != 64 || !digest.bytes().all(|b| b.is_ascii_hexdigit()) {
        return Err(anyhow!("E_RESULT_HANDLE: invalid artifact digest"));
    }
    Ok(digest)
}

fn now_secs() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}

pub fn display_path(path: &Path) -> String {
    let raw = path.to_string_lossy();
    if let Some(rest) = raw.strip_prefix(r"\\?\UNC\") {
        format!("//{}", rest.replace('\\', "/"))
    } else if let Some(rest) = raw.strip_prefix(r"\\?\") {
        rest.replace('\\', "/")
    } else {
        raw.replace('\\', "/")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn content_addressed_store_roundtrips_and_deduplicates() {
        let root =
            std::env::temp_dir().join(format!("verseshell-artifact-{}", uuid::Uuid::new_v4()));
        let store = ArtifactStore::new(&root).unwrap();
        let first = store
            .store(b"hello", "utf-8", "stdout", "test", "agent")
            .unwrap();
        let second = store
            .store(b"hello", "utf-8", "stdout", "test", "agent")
            .unwrap();
        assert_eq!(first.metadata.handle, second.metadata.handle);
        let (metadata, bytes) = store.load(&first.metadata.handle).unwrap();
        assert_eq!(metadata.bytes, 5);
        assert_eq!(bytes, b"hello");
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn rejects_invalid_handles() {
        assert!(parse_handle("file://x").is_err());
        assert!(parse_handle("result://sha256/nope").is_err());
    }

    #[test]
    fn expired_artifacts_are_removed() {
        let root =
            std::env::temp_dir().join(format!("verseshell-artifact-{}", uuid::Uuid::new_v4()));
        let store =
            ArtifactStore::with_limits(&root, Duration::ZERO, DEFAULT_MAX_TOTAL_BYTES).unwrap();
        let artifact = store
            .store(b"expired", "utf-8", "stdout", "test", "agent")
            .unwrap();
        assert!(store.load(&artifact.metadata.handle).is_err());
        let _ = fs::remove_dir_all(root);
    }
}
