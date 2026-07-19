use crate::launcher::Launcher;
use crate::models::{Account, AccountCreate, AccountUpdate, OpenResult};
use crate::store;
use tauri::State;

#[tauri::command]
pub fn create_account(
    payload: AccountCreate,
    launcher: State<'_, Launcher>,
) -> Result<Account, String> {
    let mut account = store::create_account(payload)?;
    account.status = launcher.status_of(&account.id);
    Ok(account)
}

#[tauri::command]
pub fn list_accounts(launcher: State<'_, Launcher>) -> Result<Vec<Account>, String> {
    launcher.reap();
    let mut accounts = store::list_accounts()?;
    for a in &mut accounts {
        a.status = launcher.status_of(&a.id);
    }
    Ok(accounts)
}

#[tauri::command]
pub fn get_account(id: String, launcher: State<'_, Launcher>) -> Result<Account, String> {
    launcher.reap();
    let mut account = store::get_account(&id)?;
    account.status = launcher.status_of(&account.id);
    Ok(account)
}

#[tauri::command]
pub fn update_account(
    id: String,
    payload: AccountUpdate,
    launcher: State<'_, Launcher>,
) -> Result<Account, String> {
    let mut account = store::update_account(&id, payload)?;
    account.status = launcher.status_of(&account.id);
    Ok(account)
}

#[tauri::command]
pub fn remove_account(id: String, launcher: State<'_, Launcher>) -> Result<(), String> {
    launcher.stop_if_running(&id);
    store::remove_account(&id)?;
    Ok(())
}

#[tauri::command]
pub fn open_account(
    id: String,
    url: Option<String>,
    launcher: State<'_, Launcher>,
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
pub fn stop_account(id: String, launcher: State<'_, Launcher>) -> Result<(), String> {
    launcher.stop(&id)
}

#[tauri::command]
pub fn account_status(id: String, launcher: State<'_, Launcher>) -> Result<String, String> {
    launcher.reap();
    Ok(launcher.status_of(&id))
}
