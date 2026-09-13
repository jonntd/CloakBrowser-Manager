use crate::models::{Account, AccountCreate, AccountStore, AccountUpdate, Tag};
use chrono::Utc;
use rand::Rng;
use std::fs;
use std::path::{Path, PathBuf};
use uuid::Uuid;

pub fn data_dir() -> PathBuf {
    dirs::home_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join(".cloak-accounts")
}

pub fn store_path() -> PathBuf {
    data_dir().join("accounts.json")
}

pub fn profiles_dir() -> PathBuf {
    data_dir().join("profiles")
}

/// Write a secrets-bearing file (server.json token, per-launch account JSON
/// with proxy credentials) owner-only. Unix enforces 0600 at creation; other
/// platforms keep default permissions.
pub fn write_private(path: &Path, contents: &str) -> std::io::Result<()> {
    #[cfg(unix)]
    {
        use std::io::Write;
        use std::os::unix::fs::OpenOptionsExt;
        let mut f = std::fs::OpenOptions::new()
            .write(true)
            .create(true)
            .truncate(true)
            .mode(0o600)
            .open(path)?;
        f.write_all(contents.as_bytes())
    }
    #[cfg(not(unix))]
    {
        std::fs::write(path, contents)
    }
}

/// Remove stale per-launch account JSON files under tmp/ (they carry proxy
/// credentials). Only files older than an hour are removed so a concurrently
/// launching app instance's in-flight launch is never disturbed.
pub fn clean_stale_tmp() {
    let tmp = data_dir().join("tmp");
    let Ok(entries) = fs::read_dir(&tmp) else {
        return;
    };
    let cutoff = std::time::SystemTime::now() - std::time::Duration::from_secs(3600);
    for entry in entries.flatten() {
        let path = entry.path();
        if path.extension().is_some_and(|ext| ext == "json") {
            let stale = entry
                .metadata()
                .and_then(|m| m.modified())
                .map(|t| t <= cutoff)
                .unwrap_or(false);
            if stale {
                let _ = fs::remove_file(path);
            }
        }
    }
}

fn ensure_dirs() -> Result<(), String> {
    fs::create_dir_all(data_dir()).map_err(|e| format!("创建数据目录失败: {e}"))?;
    fs::create_dir_all(profiles_dir()).map_err(|e| format!("创建 profiles 目录失败: {e}"))?;
    Ok(())
}

pub fn load() -> Result<AccountStore, String> {
    ensure_dirs()?;
    let path = store_path();
    if !path.exists() {
        let empty = AccountStore::default();
        save(&empty)?;
        return Ok(empty);
    }
    let text = fs::read_to_string(&path).map_err(|e| format!("读取账号文件失败: {e}"))?;
    if text.trim().is_empty() {
        return Ok(AccountStore::default());
    }
    serde_json::from_str(&text).map_err(|e| format!("解析账号文件失败: {e}"))
}

pub fn save(store: &AccountStore) -> Result<(), String> {
    ensure_dirs()?;
    let path = store_path();
    let tmp = path.with_extension("json.tmp");
    // Strip runtime status before persisting
    let mut clean = store.clone();
    for a in &mut clean.accounts {
        a.status = "stopped".into();
    }
    let text =
        serde_json::to_string_pretty(&clean).map_err(|e| format!("序列化账号失败: {e}"))?;
    fs::write(&tmp, text).map_err(|e| format!("写入临时文件失败: {e}"))?;
    fs::rename(&tmp, &path).map_err(|e| format!("保存账号文件失败: {e}"))?;
    Ok(())
}

fn now_iso() -> String {
    Utc::now().to_rfc3339()
}

fn random_seed() -> i64 {
    rand::thread_rng().gen_range(10_000..100_000)
}

pub fn create_account(payload: AccountCreate) -> Result<Account, String> {
    let mut store = load()?;
    let id = Uuid::new_v4().to_string();
    let seed = payload.fingerprint_seed.unwrap_or_else(random_seed);
    let user_data_dir = profiles_dir().join(&id);
    fs::create_dir_all(&user_data_dir).map_err(|e| format!("创建 user_data_dir 失败: {e}"))?;

    let now = now_iso();
    let account = Account {
        id: id.clone(),
        name: payload.name.trim().to_string(),
        site: empty_to_none(payload.site),
        notes: empty_to_none(payload.notes),
        tags: payload.tags.unwrap_or_default(),
        user_data_dir: user_data_dir.to_string_lossy().to_string(),
        fingerprint_seed: seed,
        proxy: empty_to_none(payload.proxy),
        timezone: empty_to_none(payload.timezone),
        locale: empty_to_none(payload.locale),
        platform: payload
            .platform
            .filter(|s| !s.is_empty())
            .unwrap_or_else(|| "windows".into()),
        user_agent: empty_to_none(payload.user_agent),
        screen_width: payload.screen_width.unwrap_or(1920),
        screen_height: payload.screen_height.unwrap_or(1080),
        gpu_vendor: empty_to_none(payload.gpu_vendor),
        gpu_renderer: empty_to_none(payload.gpu_renderer),
        hardware_concurrency: payload.hardware_concurrency,
        humanize: payload.humanize.unwrap_or(false),
        human_preset: payload
            .human_preset
            .filter(|s| !s.is_empty())
            .unwrap_or_else(|| "default".into()),
        geoip: payload.geoip.unwrap_or(false),
        color_scheme: empty_to_none(payload.color_scheme),
        launch_args: payload.launch_args.unwrap_or_default(),
        created_at: now.clone(),
        updated_at: now,
        status: "stopped".into(),
    };

    if account.name.is_empty() {
        return Err("账号名称不能为空".into());
    }

    store.accounts.insert(0, account.clone());
    save(&store)?;
    Ok(account)
}

pub fn list_accounts() -> Result<Vec<Account>, String> {
    Ok(load()?.accounts)
}

pub fn get_account(id: &str) -> Result<Account, String> {
    let store = load()?;
    store
        .accounts
        .into_iter()
        .find(|a| a.id == id)
        .ok_or_else(|| format!("账号不存在: {id}"))
}

pub fn update_account(id: &str, payload: AccountUpdate) -> Result<Account, String> {
    let mut store = load()?;
    let idx = store
        .accounts
        .iter()
        .position(|a| a.id == id)
        .ok_or_else(|| format!("账号不存在: {id}"))?;

    let a = &mut store.accounts[idx];
    if let Some(v) = payload.name {
        if v.trim().is_empty() {
            return Err("账号名称不能为空".into());
        }
        a.name = v.trim().to_string();
    }
    if let Some(v) = payload.site {
        a.site = empty_to_none(Some(v));
    }
    if let Some(v) = payload.notes {
        a.notes = empty_to_none(Some(v));
    }
    if let Some(v) = payload.tags {
        a.tags = v;
    }
    if let Some(v) = payload.fingerprint_seed {
        a.fingerprint_seed = v;
    }
    if let Some(v) = payload.proxy {
        a.proxy = empty_to_none(Some(v));
    }
    if let Some(v) = payload.timezone {
        a.timezone = empty_to_none(Some(v));
    }
    if let Some(v) = payload.locale {
        a.locale = empty_to_none(Some(v));
    }
    if let Some(v) = payload.platform {
        a.platform = v;
    }
    if let Some(v) = payload.user_agent {
        a.user_agent = empty_to_none(Some(v));
    }
    if let Some(v) = payload.screen_width {
        a.screen_width = v;
    }
    if let Some(v) = payload.screen_height {
        a.screen_height = v;
    }
    if let Some(v) = payload.gpu_vendor {
        a.gpu_vendor = empty_to_none(Some(v));
    }
    if let Some(v) = payload.gpu_renderer {
        a.gpu_renderer = empty_to_none(Some(v));
    }
    if let Some(v) = payload.hardware_concurrency {
        a.hardware_concurrency = Some(v);
    }
    if let Some(v) = payload.humanize {
        a.humanize = v;
    }
    if let Some(v) = payload.human_preset {
        a.human_preset = v;
    }
    if let Some(v) = payload.geoip {
        a.geoip = v;
    }
    if let Some(v) = payload.color_scheme {
        a.color_scheme = empty_to_none(Some(v));
    }
    if let Some(v) = payload.launch_args {
        a.launch_args = v;
    }
    a.updated_at = now_iso();

    let result = a.clone();
    save(&store)?;
    Ok(result)
}

/// Refuse destructive filesystem operations on any path outside the
/// app-managed profiles dir. `user_data_dir` is read back from accounts.json,
/// so a hand-edited store could otherwise point remove/clear operations at
/// arbitrary directories.
pub fn ensure_profile_contained(user_data_dir: &str) -> Result<(), String> {
    let dir = Path::new(user_data_dir);
    if dir.starts_with(profiles_dir()) {
        Ok(())
    } else {
        Err(format!(
            "user_data_dir 不在应用 profiles 目录内，已拒绝删除/清理操作: {user_data_dir}"
        ))
    }
}

pub fn remove_account(id: &str) -> Result<Account, String> {
    let mut store = load()?;
    let idx = store
        .accounts
        .iter()
        .position(|a| a.id == id)
        .ok_or_else(|| format!("账号不存在: {id}"))?;
    let account = store.accounts[idx].clone();
    ensure_profile_contained(&account.user_data_dir)?;
    store.accounts.remove(idx);
    save(&store)?;

    let dir = Path::new(&account.user_data_dir);
    if dir.exists() {
        let _ = fs::remove_dir_all(dir);
    }
    Ok(account)
}

/// Cache subdirectories (relative to a profile's user_data_dir) safe to delete
/// while keeping cookies/login. Keep in sync with cloak_launcher.py CACHE_SUBPATHS.
const CACHE_SUBPATHS: &[&str] = &[
    "Default/Cache",
    "Default/Code Cache",
    "Default/GPUCache",
    "Default/DawnCache",
    "Default/DawnGraphiteCache",
    "Default/DawnWebGPUCache",
    "Default/GrShaderCache",
    "Default/Service Worker/CacheStorage",
    "Default/Service Worker/ScriptCache",
    "GPUCache",
    "ShaderCache",
    "GrShaderCache",
    "component_crx_cache",
];

fn dir_size(path: &Path) -> u64 {
    let mut total = 0;
    if let Ok(entries) = fs::read_dir(path) {
        for e in entries.flatten() {
            match e.file_type() {
                Ok(ft) if ft.is_dir() => total += dir_size(&e.path()),
                Ok(ft) if ft.is_file() => {
                    if let Ok(md) = e.metadata() {
                        total += md.len();
                    }
                }
                _ => {}
            }
        }
    }
    total
}

/// Delete cache subdirs under `user_data_dir` (keeps cookies). Returns bytes freed.
/// Refuses paths outside the app-managed profiles dir (defense against a
/// hand-edited accounts.json pointing at arbitrary directories).
pub fn clear_cache(user_data_dir: &Path) -> Result<u64, String> {
    ensure_profile_contained(&user_data_dir.to_string_lossy())?;
    let mut freed = 0;
    for rel in CACHE_SUBPATHS {
        let p = user_data_dir.join(rel);
        if p.exists() {
            freed += dir_size(&p);
            let _ = fs::remove_dir_all(&p);
        }
    }
    Ok(freed)
}

fn empty_to_none(v: Option<String>) -> Option<String> {
    v.and_then(|s| {
        let t = s.trim().to_string();
        if t.is_empty() {
            None
        } else {
            Some(t)
        }
    })
}

// silence unused import warning for Tag in some builds
#[allow(dead_code)]
fn _tag_typecheck() -> Tag {
    Tag {
        tag: String::new(),
        color: None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::models::AccountCreate;
    use std::sync::Mutex;

    // Serialize tests that touch the real home-dir store path.
    // We redirect by temporarily setting HOME.
    static LOCK: Mutex<()> = Mutex::new(());

    fn with_temp_home<F: FnOnce()>(f: F) {
        let _guard = LOCK.lock().unwrap();
        let tmp = std::env::temp_dir().join(format!("cloak-test-{}", Uuid::new_v4()));
        fs::create_dir_all(&tmp).unwrap();
        let old_home = std::env::var("HOME").ok();
        // dirs::home_dir reads HOME on Unix
        std::env::set_var("HOME", &tmp);
        f();
        if let Some(h) = old_home {
            std::env::set_var("HOME", h);
        } else {
            std::env::remove_var("HOME");
        }
        let _ = fs::remove_dir_all(&tmp);
    }

    #[test]
    fn create_and_list_account() {
        with_temp_home(|| {
            let a = create_account(AccountCreate {
                name: "账号A".into(),
                site: Some("example.com".into()),
                ..Default::default()
            })
            .unwrap();
            assert_eq!(a.name, "账号A");
            assert!(a.fingerprint_seed >= 10_000);
            assert!(Path::new(&a.user_data_dir).exists());
            let list = list_accounts().unwrap();
            assert_eq!(list.len(), 1);
            assert_eq!(list[0].id, a.id);
        });
    }

    #[test]
    fn each_account_has_unique_dir() {
        with_temp_home(|| {
            let a = create_account(AccountCreate {
                name: "A".into(),
                ..Default::default()
            })
            .unwrap();
            let b = create_account(AccountCreate {
                name: "B".into(),
                ..Default::default()
            })
            .unwrap();
            assert_ne!(a.user_data_dir, b.user_data_dir);
            assert_ne!(a.id, b.id);
        });
    }

    #[test]
    fn remove_deletes_dir() {
        with_temp_home(|| {
            let a = create_account(AccountCreate {
                name: "ToDelete".into(),
                ..Default::default()
            })
            .unwrap();
            let dir = a.user_data_dir.clone();
            assert!(Path::new(&dir).exists());
            remove_account(&a.id).unwrap();
            assert!(!Path::new(&dir).exists());
            assert!(list_accounts().unwrap().is_empty());
        });
    }

    #[test]
    fn remove_rejects_user_data_dir_outside_profiles() {
        with_temp_home(|| {
            let outside = std::env::temp_dir().join(format!("cloak-outside-{}", Uuid::new_v4()));
            fs::create_dir_all(&outside).unwrap();
            let a = create_account(AccountCreate {
                name: "X".into(),
                ..Default::default()
            })
            .unwrap();
            // Tamper the stored dir the way a hand-edited accounts.json would.
            let mut store = load().unwrap();
            store.accounts[0].user_data_dir = outside.to_string_lossy().to_string();
            save(&store).unwrap();

            assert!(remove_account(&a.id).is_err());
            assert!(outside.exists(), "拒绝后目标目录必须原样保留");
            let _ = fs::remove_dir_all(&outside);
        });
    }

    #[test]
    fn clear_cache_rejects_user_data_dir_outside_profiles() {
        with_temp_home(|| {
            let outside = std::env::temp_dir().join(format!("cloak-outside-{}", Uuid::new_v4()));
            fs::create_dir_all(&outside).unwrap();
            assert!(clear_cache(&outside).is_err());
            assert!(outside.exists());
            let _ = fs::remove_dir_all(&outside);
        });
    }
}
