use crate::error::AppResult;
use crate::launcher::Launcher;
use crate::models::{
    Account, AccountCreate, AccountUpdate, ClearCacheResult, Endpoint, OpenResult,
};
use crate::service::AccountService;
use crate::store;
use std::sync::Arc;
use tauri::State;

/// Build the list of CDP endpoints for currently-running browsers.
pub(crate) fn build_endpoints(service: &AccountService, launcher: &Launcher) -> Vec<Endpoint> {
    service
        .list_accounts()
        .unwrap_or_default()
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

/// Write the discovery manifest so external tools can find running endpoints.
pub(crate) fn write_endpoints_manifest(eps: &[Endpoint]) {
    let path = store::data_dir().join("endpoints.json");
    if let Ok(json) = serde_json::to_string_pretty(eps) {
        let tmp = path.with_extension("json.tmp");
        if std::fs::write(&tmp, json).is_ok() {
            let _ = std::fs::rename(&tmp, &path);
        }
    }
}

fn with_status(mut account: Account, launcher: &Launcher) -> Account {
    account.status = launcher.status_of(&account.id);
    account
}

#[tauri::command]
pub fn create_account(
    payload: AccountCreate,
    accounts: State<'_, Arc<AccountService>>,
    launcher: State<'_, Arc<Launcher>>,
) -> AppResult<Account> {
    Ok(with_status(accounts.create_account(payload)?, &launcher))
}

#[tauri::command]
pub fn list_accounts(
    accounts: State<'_, Arc<AccountService>>,
    launcher: State<'_, Arc<Launcher>>,
) -> AppResult<Vec<Account>> {
    launcher.reap();
    let result = accounts
        .list_accounts()?
        .into_iter()
        .map(|a| with_status(a, &launcher))
        .collect();
    write_endpoints_manifest(&build_endpoints(&accounts, &launcher));
    Ok(result)
}

#[tauri::command]
pub fn list_endpoints(
    accounts: State<'_, Arc<AccountService>>,
    launcher: State<'_, Arc<Launcher>>,
) -> AppResult<Vec<Endpoint>> {
    launcher.reap();
    let eps = build_endpoints(&accounts, &launcher);
    write_endpoints_manifest(&eps);
    Ok(eps)
}

#[tauri::command]
pub fn get_account(
    id: String,
    accounts: State<'_, Arc<AccountService>>,
    launcher: State<'_, Arc<Launcher>>,
) -> AppResult<Account> {
    launcher.reap();
    Ok(with_status(accounts.get_account(&id)?, &launcher))
}

#[tauri::command]
pub fn update_account(
    id: String,
    payload: AccountUpdate,
    accounts: State<'_, Arc<AccountService>>,
    launcher: State<'_, Arc<Launcher>>,
) -> AppResult<Account> {
    Ok(with_status(
        accounts.update_account(&id, payload)?,
        &launcher,
    ))
}

#[tauri::command]
pub fn remove_account(
    id: String,
    accounts: State<'_, Arc<AccountService>>,
    launcher: State<'_, Arc<Launcher>>,
) -> AppResult<()> {
    launcher.stop_if_running(&id);
    accounts.remove_account(&id)?;
    write_endpoints_manifest(&build_endpoints(&accounts, &launcher));
    Ok(())
}

#[tauri::command]
pub fn open_account(
    id: String,
    url: Option<String>,
    accounts: State<'_, Arc<AccountService>>,
    launcher: State<'_, Arc<Launcher>>,
) -> AppResult<OpenResult> {
    launcher.reap();
    let account = accounts.get_account(&id)?;
    let pid = launcher
        .open(&account, url)
        .map_err(crate::error::AppError::Operation)?;
    write_endpoints_manifest(&build_endpoints(&accounts, &launcher));
    Ok(OpenResult {
        account_id: id,
        status: "running".into(),
        pid,
    })
}

#[tauri::command]
pub fn stop_account(
    id: String,
    accounts: State<'_, Arc<AccountService>>,
    launcher: State<'_, Arc<Launcher>>,
) -> AppResult<()> {
    launcher
        .stop(&id)
        .map_err(crate::error::AppError::Operation)?;
    write_endpoints_manifest(&build_endpoints(&accounts, &launcher));
    Ok(())
}

#[tauri::command]
pub fn stop_all(
    accounts: State<'_, Arc<AccountService>>,
    launcher: State<'_, Arc<Launcher>>,
) -> AppResult<usize> {
    let count = launcher.stop_all();
    write_endpoints_manifest(&build_endpoints(&accounts, &launcher));
    Ok(count)
}

#[tauri::command]
pub fn account_status(id: String, launcher: State<'_, Arc<Launcher>>) -> AppResult<String> {
    launcher.reap();
    Ok(launcher.status_of(&id))
}

#[tauri::command]
pub fn clear_all_cache(
    accounts: State<'_, Arc<AccountService>>,
    launcher: State<'_, Arc<Launcher>>,
) -> AppResult<ClearCacheResult> {
    launcher.reap();
    let mut cleared = 0;
    let mut skipped_running = 0;
    let mut freed_bytes = 0u64;
    for a in accounts.list_accounts()? {
        if launcher.status_of(&a.id) == "running" {
            skipped_running += 1;
            continue;
        }
        freed_bytes += accounts.clear_cache(&a.user_data_dir)?;
        cleared += 1;
    }
    Ok(ClearCacheResult {
        cleared,
        skipped_running,
        freed_bytes,
    })
}

#[tauri::command]
pub fn clear_account_data(
    id: String,
    accounts: State<'_, Arc<AccountService>>,
    launcher: State<'_, Arc<Launcher>>,
) -> AppResult<()> {
    if launcher.is_running(&id) {
        return Err(crate::error::AppError::AlreadyRunning);
    }
    accounts.clear_account_data(&id)
}
