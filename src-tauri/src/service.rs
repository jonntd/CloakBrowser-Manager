//! Account service: the single owner of the in-memory account store plus all
//! mutations. Both the Tauri commands and the local HTTP API call into this
//! one instance, so concurrent create/update calls can no longer overwrite
//! each other (the old load-mutate-save-per-call flow raced across threads).
//!
//! Memory is the source of truth; every mutation is persisted with the same
//! tmp+rename atomic write as before.

use crate::error::{AppError, AppResult};
use crate::models::{Account, AccountCreate, AccountStore, AccountUpdate};
use crate::store;
use std::sync::Mutex;

pub struct AccountService {
    store: Mutex<AccountStore>,
}

impl AccountService {
    /// Load the persisted store once at startup. A malformed existing file is
    /// fatal rather than silently replacing potentially recoverable data.
    pub fn new() -> Self {
        let store = store::load().unwrap_or_else(|e| {
            panic!("无法加载账号存储，拒绝以空数据覆盖原文件: {e}");
        });
        Self {
            store: Mutex::new(store),
        }
    }

    pub fn create_account(&self, payload: AccountCreate) -> AppResult<Account> {
        let mut store = self.store.lock().unwrap();
        let account = store::create_account_in(&mut store, payload)?;
        store::save(&store)?;
        Ok(account)
    }

    pub fn list_accounts(&self) -> AppResult<Vec<Account>> {
        Ok(self.store.lock().unwrap().accounts.clone())
    }

    pub fn get_account(&self, id: &str) -> AppResult<Account> {
        self.store
            .lock()
            .unwrap()
            .accounts
            .iter()
            .find(|a| a.id == id)
            .cloned()
            .ok_or_else(|| AppError::NotFound(format!("账号不存在: {id}")))
    }

    pub fn update_account(&self, id: &str, payload: AccountUpdate) -> AppResult<Account> {
        let mut store = self.store.lock().unwrap();
        let account = store::update_account_in(&mut store, id, payload)?;
        store::save(&store)?;
        Ok(account)
    }

    /// Remove an account and delete its profile dir. Fails (leaving the store
    /// untouched) when the dir points outside the app-managed profiles dir.
    pub fn remove_account(&self, id: &str) -> AppResult<Account> {
        let account = {
            let mut store = self.store.lock().unwrap();
            let idx = store
                .accounts
                .iter()
                .position(|a| a.id == id)
                .ok_or_else(|| AppError::NotFound(format!("账号不存在: {id}")))?;
            store::ensure_profile_contained(&store.accounts[idx].user_data_dir)?;
            let account = store.accounts.remove(idx);
            store::save(&store)?;
            account
        };
        let dir = std::path::Path::new(&account.user_data_dir);
        if dir.exists() {
            let _ = std::fs::remove_dir_all(dir);
        }
        Ok(account)
    }

    /// Resolve a key that may be either an id or a (unique) name.
    pub fn resolve_id(&self, key: &str) -> Option<String> {
        let store = self.store.lock().unwrap();
        if store.accounts.iter().any(|a| a.id == key) {
            return Some(key.to_string());
        }
        store
            .accounts
            .iter()
            .find(|a| a.name == key)
            .map(|a| a.id.clone())
    }

    /// Delete cache subdirs under a stopped account's profile (keeps cookies).
    pub fn clear_cache(&self, user_data_dir: &str) -> AppResult<u64> {
        store::clear_cache(std::path::Path::new(user_data_dir))
    }

    /// Wipe and recreate a stopped account's profile dir.
    pub fn clear_account_data(&self, id: &str) -> AppResult<()> {
        let account = self.get_account(id)?;
        store::ensure_profile_contained(&account.user_data_dir)?;
        let dir = std::path::Path::new(&account.user_data_dir);
        if dir.exists() {
            std::fs::remove_dir_all(dir)
                .map_err(|e| AppError::Operation(format!("清除浏览器数据失败: {e}")))?;
        }
        std::fs::create_dir_all(dir)
            .map_err(|e| AppError::Operation(format!("重建数据目录失败: {e}")))?;
        Ok(())
    }
}

impl Default for AccountService {
    fn default() -> Self {
        Self::new()
    }
}
