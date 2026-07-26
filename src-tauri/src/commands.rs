use crate::launcher::Launcher;
use crate::models::{Account, AccountCreate, AccountUpdate, ClearCacheResult, Endpoint, OpenResult};
use crate::store;
use std::sync::Arc;
use tauri::State;

/// Build the list of CDP endpoints for currently-running browsers.
pub(crate) fn build_endpoints(launcher: &Launcher) -> Vec<Endpoint> {
    let accounts = store::list_accounts().unwrap_or_default();
    accounts
        .into_iter()
        .filter_map(|a| {
            if launcher.status_of(&a.id) != "running" {
                return None;
            }
            let port = launcher.cdp_port_of(&a.id)?;
            Some(Endpoint {
                id: a.id,
                name: a.name,
                cdp_port: port,
                cdp_url: format!("http://127.0.0.1:{port}"),
            })
        })
        .collect()
}

/// Write the discovery manifest so external tools (Claude / Playwright / …) can
/// auto-find every running browser's CDP endpoint without the app UI.
pub(crate) fn write_endpoints_manifest(eps: &[Endpoint]) {
    let path = store::data_dir().join("endpoints.json");
    if let Ok(json) = serde_json::to_string_pretty(eps) {
        let tmp = path.with_extension("json.tmp");
        if std::fs::write(&tmp, json).is_ok() {
            let _ = std::fs::rename(&tmp, &path);
        }
    }
}

#[tauri::command]
pub fn create_account(
    payload: AccountCreate,
    launcher: State<'_, Arc<Launcher>>,
) -> Result<Account, String> {
    let mut account = store::create_account(payload)?;
    account.status = launcher.status_of(&account.id);
    Ok(account)
}

#[tauri::command]
pub fn list_accounts(launcher: State<'_, Arc<Launcher>>) -> Result<Vec<Account>, String> {
    launcher.reap();
    let mut accounts = store::list_accounts()?;
    for a in &mut accounts {
        a.status = launcher.status_of(&a.id);
    }
    // Keep the CDP discovery manifest current on every poll (browsers may have
    // been closed by the user closing the window, which reap() just cleaned up).
    write_endpoints_manifest(&build_endpoints(&launcher));
    Ok(accounts)
}

/// Return CDP endpoints for all running browsers (and refresh the manifest file).
#[tauri::command]
pub fn list_endpoints(launcher: State<'_, Arc<Launcher>>) -> Result<Vec<Endpoint>, String> {
    launcher.reap();
    let eps = build_endpoints(&launcher);
    write_endpoints_manifest(&eps);
    Ok(eps)
}

#[tauri::command]
pub fn get_account(id: String, launcher: State<'_, Arc<Launcher>>) -> Result<Account, String> {
    launcher.reap();
    let mut account = store::get_account(&id)?;
    account.status = launcher.status_of(&account.id);
    Ok(account)
}

#[tauri::command]
pub fn update_account(
    id: String,
    payload: AccountUpdate,
    launcher: State<'_, Arc<Launcher>>,
) -> Result<Account, String> {
    let mut account = store::update_account(&id, payload)?;
    account.status = launcher.status_of(&account.id);
    Ok(account)
}

#[tauri::command]
pub fn remove_account(id: String, launcher: State<'_, Arc<Launcher>>) -> Result<(), String> {
    launcher.stop_if_running(&id);
    store::remove_account(&id)?;
    Ok(())
}

#[tauri::command]
pub fn open_account(
    id: String,
    url: Option<String>,
    launcher: State<'_, Arc<Launcher>>,
) -> Result<OpenResult, String> {
    launcher.reap();
    let account = store::get_account(&id)?;
    let pid = launcher.open(&account, url)?;
    Ok(OpenResult {
        account_id: id,
        status: "running".into(),
        pid,
    })
}

#[tauri::command]
pub fn stop_account(id: String, launcher: State<'_, Arc<Launcher>>) -> Result<(), String> {
    launcher.stop(&id)
}

#[tauri::command]
pub fn stop_all(launcher: State<'_, Arc<Launcher>>) -> Result<usize, String> {
    Ok(launcher.stop_all())
}

#[tauri::command]
pub fn account_status(id: String, launcher: State<'_, Arc<Launcher>>) -> Result<String, String> {
    launcher.reap();
    Ok(launcher.status_of(&id))
}

#[tauri::command]
pub fn clear_all_cache(launcher: State<'_, Arc<Launcher>>) -> Result<ClearCacheResult, String> {
    launcher.reap();
    let accounts = store::list_accounts()?;
    let mut cleared = 0;
    let mut skipped_running = 0;
    let mut freed_bytes = 0u64;
    for a in &accounts {
        // Skip running browsers — their cache is locked/in-use; it's purged on close.
        if launcher.status_of(&a.id) == "running" {
            skipped_running += 1;
            continue;
        }
        freed_bytes += store::clear_cache(std::path::Path::new(&a.user_data_dir));
        cleared += 1;
    }
    Ok(ClearCacheResult {
        cleared,
        skipped_running,
        freed_bytes,
    })
}

#[tauri::command]
pub fn clear_account_data(id: String) -> Result<(), String> {
    let account = store::get_account(&id)?;
    let dir = std::path::Path::new(&account.user_data_dir);
    if dir.exists() {
        std::fs::remove_dir_all(dir).map_err(|e| format!("清除浏览器数据失败: {e}"))?;
    }
    std::fs::create_dir_all(dir).map_err(|e| format!("重建数据目录失败: {e}"))?;
    Ok(())
}
