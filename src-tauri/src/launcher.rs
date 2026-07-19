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

        let mut cmd = Command::new(&python);
        cmd.arg(&launcher)
            .arg("--account-file")
            .arg(&account_file)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());

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

        let child = cmd
            .spawn()
            .map_err(|e| format!("启动浏览器失败（请确认已安装 Python 与 cloakbrowser）: {e}"))?;

        let pid = child.id();
        self.running.lock().unwrap().insert(account.id.clone(), child);
        Ok(pid)
    }

    pub fn stop(&self, id: &str) -> Result<(), String> {
        let mut map = self.running.lock().unwrap();
        if let Some(mut child) = map.remove(id) {
            // Try graceful kill
            let _ = child.kill();
            let _ = child.wait();
            Ok(())
        } else {
            Err("该账号浏览器未在运行".into())
        }
    }

    pub fn stop_if_running(&self, id: &str) {
        let _ = self.stop(id);
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
