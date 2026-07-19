mod commands;
mod launcher;
mod models;
mod store;

use launcher::Launcher;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(Launcher::new())
        .invoke_handler(tauri::generate_handler![
            commands::create_account,
            commands::list_accounts,
            commands::get_account,
            commands::update_account,
            commands::remove_account,
            commands::open_account,
            commands::stop_account,
            commands::account_status,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
