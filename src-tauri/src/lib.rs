mod commands;
mod http_server;
mod launcher;
mod models;
mod store;

use launcher::Launcher;
use std::sync::Arc;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    // Single process manager shared by the GUI (Tauri commands) and the local
    // HTTP account API (which the MCP server / Claude talks to).
    let launcher = Arc::new(Launcher::new());
    let server_launcher = launcher.clone();
    std::thread::spawn(move || {
        http_server::serve(server_launcher);
    });

    tauri::Builder::default()
        .manage(launcher)
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
