use serde::Deserialize;
use semver::Version;

use crate::config::LauncherConfig;

/// Platform string used to select the correct musl binary asset.
const ARCH_STR: &str = if cfg!(target_arch = "x86_64") {
    "x86_64"
} else if cfg!(target_arch = "aarch64") {
    "aarch64"
} else {
    "unknown"
};

#[derive(Debug, Clone)]
pub struct ReleaseInfo {
    pub version:      String,  // "0.3.1" (tag stripped of "v")
    pub download_url: String,  // URL to the musl binary asset
}

#[derive(Deserialize)]
struct GitHubRelease {
    tag_name: String,
    assets:   Vec<GitHubAsset>,
}

#[derive(Deserialize)]
struct GitHubAsset {
    name:                 String,
    browser_download_url: String,
}

/// Check GitHub Releases API for the latest release.
///
/// Returns `None` on *any* failure — network errors are silently ignored so the launcher
/// never fails due to an unavailable update server.
pub fn check_latest_release(_config: &LauncherConfig) -> Option<ReleaseInfo> {
    check_latest_release_inner().ok().flatten()
}

fn check_latest_release_inner() -> anyhow::Result<Option<ReleaseInfo>> {
    let client = reqwest::blocking::Client::builder()
        .user_agent(format!("concierge-launcher/{}", env!("CARGO_PKG_VERSION")))
        .timeout(std::time::Duration::from_secs(5))
        .build()?;

    let response = client
        .get("https://api.github.com/repos/ausmarton/agentic-concierge/releases/latest")
        .send()?;

    if !response.status().is_success() {
        return Ok(None);
    }

    let release: GitHubRelease = response.json()?;
    let version = release.tag_name.trim_start_matches('v').to_string();

    let asset_name = format!("concierge-{}-unknown-linux-musl", ARCH_STR);
    let asset = release.assets.iter().find(|a| a.name == asset_name);

    Ok(asset.map(|a| ReleaseInfo {
        version,
        download_url: a.browser_download_url.clone(),
    }))
}

/// Download binary to a temp file, chmod +x, then atomically rename to `config.installed_bin`.
pub fn apply_update(config: &LauncherConfig, release: &ReleaseInfo) -> anyhow::Result<()> {
    let client = reqwest::blocking::Client::builder()
        .user_agent(format!("concierge-launcher/{}", env!("CARGO_PKG_VERSION")))
        .build()?;

    let response = client.get(&release.download_url).send()?.error_for_status()?;
    let bytes = response.bytes()?;

    let new_path = config.data_dir.join("concierge.new");
    std::fs::write(&new_path, &bytes)?;

    use std::os::unix::fs::PermissionsExt;
    let mut perms = std::fs::metadata(&new_path)?.permissions();
    perms.set_mode(0o755);
    std::fs::set_permissions(&new_path, perms)?;

    // Atomic rename on Linux (same filesystem).
    std::fs::rename(&new_path, &config.installed_bin)?;

    eprintln!("[concierge] updated to v{}", release.version);
    Ok(())
}

/// Return true if `release.version` is strictly greater than the current binary version.
pub fn is_newer(release: &ReleaseInfo) -> bool {
    let current = match Version::parse(env!("CARGO_PKG_VERSION")) {
        Ok(v) => v,
        Err(_) => return false,
    };
    let latest = match Version::parse(&release.version) {
        Ok(v) => v,
        Err(_) => return false,
    };
    latest > current
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn is_newer_greater() {
        let release = ReleaseInfo {
            version:      "999.0.0".to_string(),
            download_url: String::new(),
        };
        assert!(is_newer(&release));
    }

    #[test]
    fn is_newer_same_version() {
        let release = ReleaseInfo {
            version:      env!("CARGO_PKG_VERSION").to_string(),
            download_url: String::new(),
        };
        assert!(!is_newer(&release));
    }

    #[test]
    fn is_newer_older_version() {
        let release = ReleaseInfo {
            version:      "0.0.1".to_string(),
            download_url: String::new(),
        };
        assert!(!is_newer(&release));
    }

    #[test]
    fn arch_str_is_not_unknown() {
        assert_ne!(ARCH_STR, "unknown");
    }
}
