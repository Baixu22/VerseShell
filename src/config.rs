//! Minimal configuration for aeshell.
//!
//! Configuration file locations (in order of precedence):
//! 1. `$AE_CONFIG` environment variable (if set)
//! 2. `$XDG_CONFIG_HOME/ae/config.toml`
//! 3. `~/.aerc` (legacy fallback)

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs;
use std::path::PathBuf;
use std::sync::OnceLock;

static CONFIG: OnceLock<ShellConfig> = OnceLock::new();

pub fn get_config() -> &'static ShellConfig {
    CONFIG.get_or_init(|| ShellConfig::load().unwrap_or_default())
}

pub fn reload_config() -> Result<ShellConfig> {
    ShellConfig::load()
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
#[derive(Default)]
pub struct ShellConfig {
    pub shell: ShellSettings,
    pub history: HistoryConfig,
    pub aliases: HashMap<String, String>,
    pub env: HashMap<String, String>,
    #[serde(default)]
    pub colors: ColorConfig,
    #[serde(default)]
    pub prompt: PromptConfig,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct ShellSettings {
    pub show_banner: bool,
    pub default_directory: String,
    pub auto_cd: bool,
    pub show_tips: bool,
    pub vi_mode: bool,
    pub glob_expansion: bool,
    pub command_correction: bool,
    pub bell_style: String,
}

impl Default for ShellSettings {
    fn default() -> Self {
        Self {
            show_banner: true,
            default_directory: String::new(),
            auto_cd: true,
            show_tips: true,
            vi_mode: false,
            glob_expansion: true,
            command_correction: true,
            bell_style: "audible".to_string(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct ColorConfig {
    pub enabled: bool,
    pub theme: String,
    pub force: bool,
    pub true_color: bool,
}

impl Default for ColorConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            theme: "default".to_string(),
            force: false,
            true_color: false,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct PromptConfig {
    pub format: String,
    pub show_git: bool,
    pub show_time: bool,
    pub time_threshold_ms: i64,
}

impl Default for PromptConfig {
    fn default() -> Self {
        Self {
            format: "{path} $ ".to_string(),
            show_git: true,
            show_time: false,
            time_threshold_ms: 2000,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct HistoryConfig {
    pub max_entries: usize,
    pub save_on_exit: bool,
    pub enabled: bool,
    pub max_size: usize,
    pub ignore_duplicates: bool,
    pub ignore_space: bool,
    pub share: bool,
    pub timestamps: bool,
}

impl Default for HistoryConfig {
    fn default() -> Self {
        Self {
            max_entries: 10000,
            save_on_exit: true,
            enabled: true,
            max_size: 10000,
            ignore_duplicates: true,
            ignore_space: false,
            share: false,
            timestamps: true,
        }
    }
}

impl ShellConfig {
    pub fn load() -> Result<Self> {
        let path = Self::config_path()?;
        if path.exists() {
            let content = fs::read_to_string(&path)
                .with_context(|| format!("failed to read config at {}", path.display()))?;
            let config: ShellConfig = toml::from_str(&content)
                .with_context(|| format!("failed to parse config at {}", path.display()))?;
            Ok(config)
        } else {
            Ok(Self::default())
        }
    }

    pub fn save(&self) -> Result<()> {
        let path = Self::config_path()?;
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).ok();
        }
        let content = toml::to_string_pretty(self).context("failed to serialize config")?;
        fs::write(&path, content)
            .with_context(|| format!("failed to write config to {}", path.display()))?;
        Ok(())
    }

    pub fn config_file() -> PathBuf {
        Self::config_path().unwrap_or_else(|_| PathBuf::from(".aerc"))
    }

    pub fn config_dir() -> PathBuf {
        Self::config_file()
            .parent()
            .map(|p| p.to_path_buf())
            .unwrap_or_else(|| PathBuf::from("."))
    }

    pub fn data_dir() -> PathBuf {
        dirs::data_dir()
            .map(|d| d.join("ae"))
            .unwrap_or_else(|| PathBuf::from(".ae/data"))
    }

    pub fn cache_dir() -> PathBuf {
        dirs::cache_dir()
            .map(|d| d.join("ae"))
            .unwrap_or_else(|| PathBuf::from(".ae/cache"))
    }

    pub fn history_file() -> PathBuf {
        Self::data_dir().join("history")
    }

    pub fn plugins_dir() -> PathBuf {
        Self::data_dir().join("plugins")
    }

    pub fn init_script() -> PathBuf {
        Self::config_dir().join("init.ae")
    }

    pub fn init_dirs() -> Result<()> {
        let dirs = [
            Self::config_dir(),
            Self::data_dir(),
            Self::cache_dir(),
            Self::plugins_dir(),
        ];
        for d in &dirs {
            fs::create_dir_all(d).ok();
        }
        Ok(())
    }

    pub fn generate_default_config() -> String {
        let config = Self::default();
        toml::to_string_pretty(&config).unwrap_or_default()
    }

    fn config_path() -> Result<PathBuf> {
        if let Ok(p) = std::env::var("AE_CONFIG") {
            return Ok(PathBuf::from(p));
        }
        if let Some(dir) = dirs::config_dir() {
            return Ok(dir.join("ae").join("config.toml"));
        }
        if let Some(home) = dirs::home_dir() {
            return Ok(home.join(".aerc"));
        }
        Ok(PathBuf::from(".aerc"))
    }
}
