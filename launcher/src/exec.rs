use std::path::Path;

/// Replace the current process image with the Python concierge binary.
///
/// Strips `--self-update` from args (launcher-only flag). Uses `exec()` so
/// the Python process inherits the launcher's PID — no zombie, correct signal
/// forwarding.
///
/// This is the Unix (Linux + macOS) implementation.  Both platforms provide
/// POSIX `execv` via `std::os::unix::process::CommandExt::exec()`, so no
/// platform-specific branching is needed here beyond the `#[cfg(unix)]` guard.
///
/// Windows: see Phase 15 — `CreateProcess` + `WaitForSingleObject` +
/// `exit(child_exit_code)` to preserve correct exit codes without zombies.
#[cfg(unix)]
pub fn exec_python_concierge(concierge_bin: &Path) -> anyhow::Result<()> {
    use std::os::unix::process::CommandExt;

    let args: Vec<String> = std::env::args().skip(1).collect();
    let args: Vec<&String> = args.iter().filter(|a| *a != "--self-update").collect();
    let err = std::process::Command::new(concierge_bin).args(&args).exec();
    Err(anyhow::anyhow!("exec failed: {}", err))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn exec_nonexistent_binary_returns_error() {
        let path = Path::new("/nonexistent/binary/concierge-does-not-exist");
        let result = exec_python_concierge(path);
        assert!(result.is_err());
    }
}
