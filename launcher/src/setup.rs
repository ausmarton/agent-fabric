use std::path::{Path, PathBuf};
use thiserror::Error;

use crate::config::LauncherConfig;

#[derive(Debug, Error)]
pub enum SetupError {
    #[error("no suitable Python >= 3.10 found in PATH and uv installation failed")]
    NoPython,
    #[error("failed to create virtual environment: {0}")]
    VenvCreation(String),
    #[error("failed to install package (exit code {code}): {stderr}")]
    PackageInstall { code: i32, stderr: String },
    #[error("uv binary is not executable after download")]
    UvNotExecutable,
}

/// Ensure managed venv exists with agentic-concierge installed.
/// Returns path to the venv's concierge binary.
///
/// Fast path: if `venv_dir/bin/concierge` already exists, return immediately.
/// First-time path: detect system Python >= 3.10 or download uv, create venv, pip install.
pub fn ensure_environment(config: &LauncherConfig) -> anyhow::Result<PathBuf> {
    let concierge_bin = config.venv_dir.join("bin").join("concierge");
    if concierge_bin.exists() {
        return Ok(concierge_bin);
    }

    // First-time setup
    std::fs::create_dir_all(&config.data_dir)?;

    let python = try_system_python();

    if python.is_none() {
        ensure_uv(config).map_err(|e| {
            eprintln!("[concierge] could not install uv: {}", e);
            SetupError::NoPython
        })?;
    }

    // Create venv
    match &python {
        Some(py_path) => {
            let status = std::process::Command::new(py_path)
                .args(["-m", "venv"])
                .arg(&config.venv_dir)
                .status()
                .map_err(|e| SetupError::VenvCreation(e.to_string()))?;
            if !status.success() {
                return Err(SetupError::VenvCreation("venv creation failed".to_string()).into());
            }
        }
        None => {
            // Use uv
            let status = std::process::Command::new(&config.uv_path)
                .args(["venv", "--python", "3.12"])
                .arg(&config.venv_dir)
                .status()
                .map_err(|e| SetupError::VenvCreation(e.to_string()))?;
            if !status.success() {
                return Err(
                    SetupError::VenvCreation("uv venv creation failed".to_string()).into()
                );
            }
        }
    }

    // pip install
    let pip = config.venv_dir.join("bin").join("pip");
    let package_spec = match &config.pypi_extra {
        Some(extra) => format!("{}[{}]", config.package_name, extra),
        None => config.package_name.clone(),
    };
    let output = std::process::Command::new(&pip)
        .args(["install", "--upgrade", &package_spec])
        .output()
        .map_err(|e| SetupError::PackageInstall {
            code: -1,
            stderr: e.to_string(),
        })?;
    if !output.status.success() {
        let code = output.status.code().unwrap_or(-1);
        let stderr = String::from_utf8_lossy(&output.stderr).to_string();
        return Err(SetupError::PackageInstall { code, stderr }.into());
    }

    // Write version file
    std::fs::write(&config.version_file, env!("CARGO_PKG_VERSION"))?;

    Ok(concierge_bin)
}

/// Upgrade the installed package to a specific version (called after self-update).
pub fn upgrade_package(config: &LauncherConfig, version: &str) -> anyhow::Result<()> {
    let pip = config.venv_dir.join("bin").join("pip");
    let package_spec = format!("{}=={}", config.package_name, version);
    let output = std::process::Command::new(&pip)
        .args(["install", "--upgrade", &package_spec])
        .output()
        .map_err(|e| SetupError::PackageInstall {
            code: -1,
            stderr: e.to_string(),
        })?;
    if !output.status.success() {
        let code = output.status.code().unwrap_or(-1);
        let stderr = String::from_utf8_lossy(&output.stderr).to_string();
        return Err(SetupError::PackageInstall { code, stderr }.into());
    }
    std::fs::write(&config.version_file, version)?;
    Ok(())
}

/// Read installed package version from version_file; None if file absent.
///
/// Not yet called from main — kept as public API for future status/health display.
#[allow(dead_code)]
pub fn installed_version(config: &LauncherConfig) -> anyhow::Result<Option<String>> {
    if !config.version_file.exists() {
        return Ok(None);
    }
    let version = std::fs::read_to_string(&config.version_file)?;
    Ok(Some(version.trim().to_string()))
}

// ── Internal helpers ──────────────────────────────────────────────────────────

/// Try ["python3", "python"] in PATH. Return Some(path) if >= 3.10, else None.
fn try_system_python() -> Option<PathBuf> {
    for name in &["python3", "python"] {
        if let Ok(output) = std::process::Command::new(name).arg("--version").output() {
            if output.status.success() {
                let stdout = String::from_utf8_lossy(&output.stdout);
                let stderr = String::from_utf8_lossy(&output.stderr);
                let version_str = if stdout.contains("Python") { &*stdout } else { &*stderr };
                if let Some(version) = parse_python_version(version_str) {
                    if version >= (3, 10) {
                        if let Ok(path) = which_bin(name) {
                            return Some(path);
                        }
                    }
                }
            }
        }
    }
    None
}

fn parse_python_version(s: &str) -> Option<(u32, u32)> {
    let s = s.trim().strip_prefix("Python ")?.trim();
    let mut parts = s.splitn(3, '.');
    let major: u32 = parts.next()?.parse().ok()?;
    let minor: u32 = parts.next()?.parse().ok()?;
    Some((major, minor))
}

fn which_bin(name: &str) -> anyhow::Result<PathBuf> {
    let output = std::process::Command::new("which").arg(name).output()?;
    if output.status.success() {
        let path = String::from_utf8(output.stdout)?.trim().to_string();
        Ok(PathBuf::from(path))
    } else {
        anyhow::bail!("which {} failed", name)
    }
}

/// Ensure uv binary exists at config.uv_path. Downloads from GitHub if absent.
fn ensure_uv(config: &LauncherConfig) -> anyhow::Result<()> {
    if config.uv_path.exists() {
        return Ok(());
    }

    let arch = std::env::consts::ARCH;
    let url = format!(
        "https://github.com/astral-sh/uv/releases/latest/download/uv-{}-unknown-linux-musl.tar.gz",
        arch
    );

    let client = reqwest::blocking::Client::builder()
        .user_agent(format!("concierge-launcher/{}", env!("CARGO_PKG_VERSION")))
        .build()?;

    let response = client.get(&url).send()?.error_for_status()?;
    let bytes = response.bytes()?;

    // Write tarball to a temp location inside data_dir, then extract with system tar.
    let extract_dir = config.data_dir.join(".uv-extract");
    std::fs::create_dir_all(&extract_dir)?;
    let tarball = extract_dir.join("uv.tar.gz");
    std::fs::write(&tarball, &bytes)?;

    let status = std::process::Command::new("tar")
        .args(["xzf"])
        .arg(&tarball)
        .arg("-C")
        .arg(&extract_dir)
        .status()?;

    if !status.success() {
        let _ = std::fs::remove_dir_all(&extract_dir);
        anyhow::bail!("tar extraction of uv archive failed");
    }

    let uv_bin = find_file(&extract_dir, "uv")?;
    std::fs::copy(&uv_bin, &config.uv_path)?;
    let _ = std::fs::remove_dir_all(&extract_dir);

    use std::os::unix::fs::PermissionsExt;
    let mut perms = std::fs::metadata(&config.uv_path)?.permissions();
    perms.set_mode(0o755);
    std::fs::set_permissions(&config.uv_path, perms)?;

    if !config.uv_path.exists() {
        return Err(SetupError::UvNotExecutable.into());
    }

    Ok(())
}

/// Recursively find the first file named `name` under `dir`.
fn find_file(dir: &Path, name: &str) -> anyhow::Result<PathBuf> {
    for entry in std::fs::read_dir(dir)? {
        let entry = entry?;
        let path = entry.path();
        if path.is_dir() {
            if let Ok(found) = find_file(&path, name) {
                return Ok(found);
            }
        } else if path.file_name().and_then(|n| n.to_str()) == Some(name) {
            return Ok(path);
        }
    }
    anyhow::bail!("file '{}' not found in {}", name, dir.display())
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    fn make_config(data_dir: &Path) -> LauncherConfig {
        LauncherConfig {
            data_dir:     data_dir.to_path_buf(),
            venv_dir:     data_dir.join("venv"),
            uv_path:      data_dir.join("uv"),
            version_file: data_dir.join("installed_version"),
            bin_dir:      data_dir.join("bin"),
            installed_bin: data_dir.join("bin").join("concierge"),
            skip_update:  false,
            package_name: "agentic-concierge".to_string(),
            pypi_extra:   None,
        }
    }

    #[test]
    fn installed_version_returns_none_when_no_file() {
        let dir = tempdir().unwrap();
        let config = make_config(dir.path());
        let v = installed_version(&config).unwrap();
        assert!(v.is_none());
    }

    #[test]
    fn installed_version_reads_file_contents() {
        let dir = tempdir().unwrap();
        let config = make_config(dir.path());
        std::fs::write(&config.version_file, "0.2.0\n").unwrap();
        let v = installed_version(&config).unwrap();
        assert_eq!(v, Some("0.2.0".to_string()));
    }

    #[test]
    fn ensure_environment_fast_path_returns_existing_binary() {
        let dir = tempdir().unwrap();
        let config = make_config(dir.path());
        std::fs::create_dir_all(config.venv_dir.join("bin")).unwrap();
        let bin = config.venv_dir.join("bin").join("concierge");
        std::fs::write(&bin, "#!/bin/sh\necho fake").unwrap();
        let result = ensure_environment(&config).unwrap();
        assert_eq!(result, bin);
    }
}
