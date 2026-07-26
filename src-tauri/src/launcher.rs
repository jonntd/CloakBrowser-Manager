use crate::models::Account;
use crate::store;
use std::collections::HashMap;
use std::fs;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;

/// Tracks running account browsers: account_id -> (pid, child handle).
pub struct Launcher {
    running: Mutex<HashMap<String, Child>>,
}

impl Launcher {
    pub fn new() -> Self {
        Self {
            running: Mutex::new(HashMap::new()),
        }
    }

    pub fn is_running(&self, id: &str) -> bool {
        let mut map = self.running.lock().unwrap();
        if let Some(child) = map.get_mut(id) {
            match child.try_wait() {
                Ok(Some(_)) => {
                    // Process exited
                    map.remove(id);
                    false
                }
                Ok(None) => true, // still running
                Err(_) => {
                    map.remove(id);
                    false
                }
            }
        } else {
            false
        }
    }

    pub fn status_of(&self, id: &str) -> String {
        if self.is_running(id) {
            "running".into()
        } else {
            "stopped".into()
        }
    }

    pub fn open(&self, account: &Account, url: Option<String>) -> Result<u32, String> {
        if self.is_running(&account.id) {
            return Err("该账号浏览器已在运行".into());
        }

        // Write a temp account JSON for the launcher script
        let tmp_dir = store::data_dir().join("tmp");
        fs::create_dir_all(&tmp_dir).map_err(|e| format!("创建临时目录失败: {e}"))?;
        let account_file = tmp_dir.join(format!("{}.json", account.id));
        let json = serde_json::to_string_pretty(account)
            .map_err(|e| format!("序列化账号失败: {e}"))?;
        fs::write(&account_file, json).map_err(|e| format!("写入临时账号文件失败: {e}"))?;

        let launcher = find_launcher_script()?;
        let python = find_python()?;

        // Redirect launcher output to a per-account log file. This lets us read
        // back the reason for an immediate failure (e.g. cloakbrowser missing)
        // and avoids the parent-never-drains-the-pipe deadlock on long sessions.
        let log_dir = store::data_dir().join("logs");
        fs::create_dir_all(&log_dir).map_err(|e| format!("创建日志目录失败: {e}"))?;
        let log_path = log_dir.join(format!("{}.log", account.id));
        let log_file = fs::File::create(&log_path).map_err(|e| format!("创建日志文件失败: {e}"))?;
        let log_err = log_file
            .try_clone()
            .map_err(|e| format!("复制日志文件句柄失败: {e}"))?;

        let mut cmd = Command::new(&python);
        cmd.arg(&launcher)
            .arg("--account-file")
            .arg(&account_file)
            .stdout(Stdio::from(log_file))
            .stderr(Stdio::from(log_err));

        if let Some(u) = url {
            cmd.arg("--url").arg(u);
        } else if let Some(site) = &account.site {
            if !site.is_empty() {
                cmd.arg("--url").arg(site);
            }
        }

        // Detach on Unix so the browser survives if the parent dies mid-launch
        #[cfg(unix)]
        {
            use std::os::unix::process::CommandExt;
            unsafe {
                cmd.pre_exec(|| {
                    // start new session
                    libc::setsid();
                    Ok(())
                });
            }
        }

        let mut child = cmd
            .spawn()
            .map_err(|e| format!("启动浏览器失败（请确认已安装 Python 与 cloakbrowser）: {e}"))?;

        let pid = child.id();

        // Grace period: catch launches that fail fast (missing cloakbrowser,
        // bad proxy, no free CDP port, …) and surface a friendly reason to the
        // UI instead of silently flipping back to "stopped".
        for _ in 0..15 {
            std::thread::sleep(std::time::Duration::from_millis(100));
            match child.try_wait() {
                Ok(Some(status)) => {
                    let log = fs::read_to_string(&log_path).unwrap_or_default();
                    return Err(friendly_launch_error(&log, status));
                }
                Ok(None) => {} // still alive — keep waiting out the grace window
                Err(_) => break,
            }
        }

        // Still running after the grace window → treat as a successful launch.
        self.running.lock().unwrap().insert(account.id.clone(), child);
        Ok(pid)
    }

    pub fn stop(&self, id: &str) -> Result<(), String> {
        let child = self.running.lock().unwrap().remove(id);
        match child {
            Some(mut child) => {
                terminate(&mut child);
                Ok(())
            }
            None => Err("该账号浏览器未在运行".into()),
        }
    }

    pub fn stop_if_running(&self, id: &str) {
        let _ = self.stop(id);
    }

    /// Stop every running account browser. Returns the number stopped.
    pub fn stop_all(&self) -> usize {
        // Drain out of the lock first so we don't hold it while waiting.
        let children: Vec<Child> = {
            let mut map = self.running.lock().unwrap();
            map.drain().map(|(_, c)| c).collect()
        };
        let count = children.len();
        eprintln!("[stop_all] terminating {count} browser process group(s)");

        #[cfg(unix)]
        {
            // Signal each whole process group once, sleep, then force-kill — so
            // every browser gets a graceful window in parallel instead of 300ms × N.
            for c in &children {
                signal_group(c, libc::SIGTERM);
            }
            std::thread::sleep(std::time::Duration::from_millis(300));
            for c in &children {
                signal_group(c, libc::SIGKILL);
            }
        }

        for mut c in children {
            #[cfg(not(unix))]
            {
                let _ = c.kill();
            }
            let _ = c.wait();
        }
        count
    }

    /// Reap exited processes so status is accurate.
    pub fn reap(&self) {
        let mut map = self.running.lock().unwrap();
        let finished: Vec<String> = map
            .iter_mut()
            .filter_map(|(id, child)| match child.try_wait() {
                Ok(Some(_)) | Err(_) => Some(id.clone()),
                Ok(None) => None,
            })
            .collect();
        for id in finished {
            map.remove(&id);
        }
    }
}

impl Default for Launcher {
    fn default() -> Self {
        Self::new()
    }
}

/// Turn a failed launcher's log tail into a user-facing Chinese message.
fn friendly_launch_error(log: &str, status: std::process::ExitStatus) -> String {
    if log.contains("cloakbrowser is not installed") {
        return "未安装 cloakbrowser。请在运行本 App 的 Python 环境中执行：\npip install 'cloakbrowser[geoip]'"
            .into();
    }
    if log.contains("No free CDP ports") {
        return "没有可用的调试端口（CDP）。请先停止部分浏览器后重试。".into();
    }
    if log.contains("Invalid proxy") || log.contains("Proxy URL missing") {
        return "代理配置无效。请检查该账号的代理地址（格式：host:port:user:pass 或 http://user:pass@host:port）。".into();
    }

    // Fallback: the last few non-empty log lines + exit code.
    let tail = log
        .lines()
        .rev()
        .filter(|l| !l.trim().is_empty())
        .take(3)
        .collect::<Vec<_>>()
        .into_iter()
        .rev()
        .collect::<Vec<_>>()
        .join("\n");
    let code = status
        .code()
        .map(|c| c.to_string())
        .unwrap_or_else(|| "signal".into());
    if tail.is_empty() {
        format!("浏览器启动失败（退出码 {code}）。请确认已安装 Python 3 与 cloakbrowser。")
    } else {
        format!("浏览器启动失败（退出码 {code}）：\n{tail}")
    }
}

/// Send `sig` to the launcher's entire process group.
///
/// The launcher is spawned under `setsid()`, so it is the leader of a fresh
/// process group whose id equals its pid; the browser it spawns lives in that
/// same group. Signalling `-pid` therefore reaches the launcher *and* the
/// browser — killing only the launcher's pid would orphan the browser window.
#[cfg(unix)]
fn signal_group(child: &Child, sig: libc::c_int) {
    let pid = child.id() as libc::pid_t;
    unsafe {
        libc::kill(-pid, sig);
    }
}

/// Gracefully then forcefully terminate a single launcher + its browser.
fn terminate(child: &mut Child) {
    #[cfg(unix)]
    {
        signal_group(child, libc::SIGTERM);
        std::thread::sleep(std::time::Duration::from_millis(300));
        signal_group(child, libc::SIGKILL);
    }
    #[cfg(not(unix))]
    {
        let _ = child.kill();
    }
    let _ = child.wait();
}

fn find_python() -> Result<PathBuf, String> {
    // Prefer python3, then python
    for name in ["python3", "python"] {
        if let Ok(output) = Command::new("which").arg(name).output() {
            if output.status.success() {
                let path = String::from_utf8_lossy(&output.stdout).trim().to_string();
                if !path.is_empty() {
                    return Ok(PathBuf::from(path));
                }
            }
        }
        // Fallback: try running directly
        if Command::new(name).arg("--version").output().is_ok() {
            return Ok(PathBuf::from(name));
        }
    }
    Err("未找到 Python。请安装 Python 3 并确保 `python3` 在 PATH 中。".into())
}

fn find_launcher_script() -> Result<PathBuf, String> {
    // 1. resource path (bundled app)
    if let Ok(resource) = std::env::current_exe() {
        let candidates = [
            resource
                .parent()
                .map(|p| p.join("resources").join("cloak_launcher.py")),
            resource
                .parent()
                .map(|p| p.join("binaries").join("cloak_launcher.py")),
            resource
                .parent()
                .and_then(|p| p.parent())
                .map(|p| p.join("Resources").join("cloak_launcher.py")),
        ];
        for c in candidates.into_iter().flatten() {
            if c.exists() {
                return Ok(c);
            }
        }
    }

    // 2. Dev path: relative to CARGO_MANIFEST_DIR
    let dev = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("binaries/cloak_launcher.py");
    if dev.exists() {
        return Ok(dev);
    }

    // 3. CWD relative
    let cwd = PathBuf::from("src-tauri/binaries/cloak_launcher.py");
    if cwd.exists() {
        return Ok(cwd);
    }

    Err(format!(
        "找不到 cloak_launcher.py（期望位置: {}）",
        dev.display()
    ))
}
