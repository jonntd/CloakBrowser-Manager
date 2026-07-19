use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Tag {
    pub tag: String,
    pub color: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Account {
    pub id: String,
    pub name: String,
    pub site: Option<String>,
    pub notes: Option<String>,
    pub tags: Vec<Tag>,
    pub user_data_dir: String,
    pub fingerprint_seed: i64,
    pub proxy: Option<String>,
    pub timezone: Option<String>,
    pub locale: Option<String>,
    pub platform: String,
    pub user_agent: Option<String>,
    pub screen_width: i64,
    pub screen_height: i64,
    pub gpu_vendor: Option<String>,
    pub gpu_renderer: Option<String>,
    pub hardware_concurrency: Option<i64>,
    pub humanize: bool,
    pub human_preset: String,
    pub geoip: bool,
    pub color_scheme: Option<String>,
    pub launch_args: Vec<String>,
    pub created_at: String,
    pub updated_at: String,
    /// Runtime-only field (not persisted). Injected by list/get commands.
    #[serde(default = "default_status")]
    pub status: String,
}

fn default_status() -> String {
    "stopped".into()
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct AccountCreate {
    pub name: String,
    pub site: Option<String>,
    pub notes: Option<String>,
    pub tags: Option<Vec<Tag>>,
    pub fingerprint_seed: Option<i64>,
    pub proxy: Option<String>,
    pub timezone: Option<String>,
    pub locale: Option<String>,
    pub platform: Option<String>,
    pub user_agent: Option<String>,
    pub screen_width: Option<i64>,
    pub screen_height: Option<i64>,
    pub gpu_vendor: Option<String>,
    pub gpu_renderer: Option<String>,
    pub hardware_concurrency: Option<i64>,
    pub humanize: Option<bool>,
    pub human_preset: Option<String>,
    pub geoip: Option<bool>,
    pub color_scheme: Option<String>,
    pub launch_args: Option<Vec<String>>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct AccountUpdate {
    pub name: Option<String>,
    pub site: Option<String>,
    pub notes: Option<String>,
    pub tags: Option<Vec<Tag>>,
    pub fingerprint_seed: Option<i64>,
    pub proxy: Option<String>,
    pub timezone: Option<String>,
    pub locale: Option<String>,
    pub platform: Option<String>,
    pub user_agent: Option<String>,
    pub screen_width: Option<i64>,
    pub screen_height: Option<i64>,
    pub gpu_vendor: Option<String>,
    pub gpu_renderer: Option<String>,
    pub hardware_concurrency: Option<i64>,
    pub humanize: Option<bool>,
    pub human_preset: Option<String>,
    pub geoip: Option<bool>,
    pub color_scheme: Option<String>,
    pub launch_args: Option<Vec<String>>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct AccountStore {
    pub accounts: Vec<Account>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OpenResult {
    pub account_id: String,
    pub status: String,
    pub pid: u32,
}
