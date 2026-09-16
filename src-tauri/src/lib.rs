mod commands;
mod error;
mod http_server;
mod launcher;
mod models;
mod service;
mod store;

use launcher::Launcher;
use service::AccountService;
use std::sync::Arc;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    // Best-effort sweep of credential-bearing leftovers from crashed sessions.
    store::clean_stale_tmp();

    let launcher = Arc::new(Launcher::new());
    let accounts = Arc::new(AccountService::new());
    let server_launcher = launcher.clone();
    let server_accounts = accounts.clone();
    std::thread::spawn(move || {
        http_server::serve(server_launcher, server_accounts);
    });

    tauri::Builder::default()
        .manage(launcher)
        .manage(accounts)
        .invoke_handler(tauri::generate_handler![
            commands::create_account,
            commands::list_accounts,
            commands::get_account,
            commands::update_account,
            commands::remove_account,
            commands::open_account,
            commands::stop_account,
            commands::stop_all,
            commands::account_status,
            commands::list_endpoints,
            commands::clear_account_data,
            commands::clear_all_cache,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
