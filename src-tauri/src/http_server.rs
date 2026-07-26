//! Local HTTP account-management API, embedded in the app so an MCP server (and
//! thus Claude) can manage accounts and drive browsers while the GUI runs. It
//! shares the one `Launcher` with the Tauri commands, so start/stop state and
//! CDP port allocation stay consistent across the GUI and the API.
//!
//! Bound to 127.0.0.1 only. No auth — same trust model as the CDP endpoints it
//! exposes; do not forward the port off-host.

use crate::commands;
use crate::launcher::Launcher;
use crate::models::{AccountCreate, AccountUpdate};
use crate::store;
use std::io::Cursor;
use std::sync::Arc;
use tiny_http::{Header, Method, Request, Response, Server};

const DEFAULT_PORT: u16 = 8797;

type Resp = Response<Cursor<Vec<u8>>>;

pub fn serve(launcher: Arc<Launcher>) {
    let addr = format!("127.0.0.1:{DEFAULT_PORT}");
    let server = match Server::http(&addr) {
        Ok(s) => s,
        Err(e) => {
            eprintln!("[http] failed to bind {addr}: {e}");
            return;
        }
    };
    write_server_info(DEFAULT_PORT);
    eprintln!("[http] account API listening on http://{addr}");

    for mut req in server.incoming_requests() {
        let resp = handle(&launcher, &mut req);
        let _ = req.respond(resp);
    }
}

/// Advertise the API address so the MCP server can auto-discover it.
fn write_server_info(port: u16) {
    let path = store::data_dir().join("server.json");
    let body = format!("{{\n  \"port\": {port},\n  \"base_url\": \"http://127.0.0.1:{port}\"\n}}\n");
    let _ = std::fs::create_dir_all(store::data_dir());
    let _ = std::fs::write(path, body);
}

fn json(status: u16, body: String) -> Resp {
    let header =
        Header::from_bytes(&b"Content-Type"[..], &b"application/json; charset=utf-8"[..]).unwrap();
    Response::from_string(body)
        .with_status_code(status)
        .with_header(header)
}

fn ok<T: serde::Serialize>(value: &T) -> Resp {
    match serde_json::to_string(value) {
        Ok(s) => json(200, s),
        Err(e) => err(500, &format!("serialize failed: {e}")),
    }
}

fn err(status: u16, msg: &str) -> Resp {
    json(
        status,
        format!("{{\"error\":{}}}", serde_json::to_string(msg).unwrap()),
    )
}

/// Resolve an account key that may be either an id or a (unique) name.
fn resolve_id(key: &str) -> Option<String> {
    let accounts = store::list_accounts().ok()?;
    if accounts.iter().any(|a| a.id == key) {
        return Some(key.to_string());
    }
    accounts
        .iter()
        .find(|a| a.name == key)
        .map(|a| a.id.clone())
}

fn handle(launcher: &Launcher, req: &mut Request) -> Resp {
    let method = req.method().clone();
    let url = req.url().to_string();
    let path = url.split('?').next().unwrap_or("").to_string();
    let segs: Vec<String> = path
        .trim_matches('/')
        .split('/')
        .filter(|s| !s.is_empty())
        .map(percent_decode)
        .collect();

    let mut body = String::new();
    let _ = req.as_reader().read_to_string(&mut body);

    let seg_refs: Vec<&str> = segs.iter().map(|s| s.as_str()).collect();
    match (&method, seg_refs.as_slice()) {
        (Method::Get, []) => json(
            200,
            "{\"service\":\"cloak-accounts\",\"ok\":true}".to_string(),
        ),

        (Method::Get, ["accounts"]) => {
            launcher.reap();
            match store::list_accounts() {
                Ok(mut accounts) => {
                    for a in &mut accounts {
                        a.status = launcher.status_of(&a.id);
                    }
                    ok(&accounts)
                }
                Err(e) => err(500, &e),
            }
        }

        (Method::Post, ["accounts"]) => match serde_json::from_str::<AccountCreate>(&body) {
            Ok(payload) => match store::create_account(payload) {
                Ok(a) => ok(&a),
                Err(e) => err(400, &e),
            },
            Err(e) => err(400, &format!("invalid body: {e}")),
        },

        (Method::Get, ["accounts", key]) => match resolve_id(key) {
            Some(id) => match store::get_account(&id) {
                Ok(mut a) => {
                    a.status = launcher.status_of(&a.id);
                    ok(&a)
                }
                Err(e) => err(404, &e),
            },
            None => err(404, "account not found"),
        },

        (Method::Patch, ["accounts", key]) => match resolve_id(key) {
            Some(id) => match serde_json::from_str::<AccountUpdate>(&body) {
                Ok(payload) => match store::update_account(&id, payload) {
                    Ok(a) => ok(&a),
                    Err(e) => err(400, &e),
                },
                Err(e) => err(400, &format!("invalid body: {e}")),
            },
            None => err(404, "account not found"),
        },

        (Method::Delete, ["accounts", key]) => match resolve_id(key) {
            Some(id) => {
                launcher.stop_if_running(&id);
                match store::remove_account(&id) {
                    Ok(_) => json(200, "{\"ok\":true}".to_string()),
                    Err(e) => err(400, &e),
                }
            }
            None => err(404, "account not found"),
        },

        (Method::Post, ["accounts", key, "start"]) => match resolve_id(key) {
            Some(id) => {
                launcher.reap();
                let url_opt = parse_url_field(&body);
                match store::get_account(&id) {
                    Ok(account) => match launcher.open(&account, url_opt) {
                        Ok(pid) => {
                            let port = launcher.cdp_port_of(&id);
                            let cdp_url = port.map(|p| format!("http://127.0.0.1:{p}"));
                            commands::write_endpoints_manifest(&commands::build_endpoints(launcher));
                            json(
                                200,
                                format!(
                                    "{{\"account_id\":{},\"status\":\"running\",\"pid\":{},\"cdp_port\":{},\"cdp_url\":{}}}",
                                    serde_json::to_string(&id).unwrap(),
                                    pid,
                                    port.map(|p| p.to_string()).unwrap_or_else(|| "null".into()),
                                    cdp_url
                                        .map(|u| serde_json::to_string(&u).unwrap())
                                        .unwrap_or_else(|| "null".into()),
                                ),
                            )
                        }
                        Err(e) => err(400, &e),
                    },
                    Err(e) => err(404, &e),
                }
            }
            None => err(404, "account not found"),
        },

        (Method::Post, ["accounts", key, "stop"]) => match resolve_id(key) {
            Some(id) => match launcher.stop(&id) {
                Ok(_) => {
                    commands::write_endpoints_manifest(&commands::build_endpoints(launcher));
                    json(200, "{\"ok\":true}".to_string())
                }
                Err(e) => err(400, &e),
            },
            None => err(404, "account not found"),
        },

        (Method::Post, ["stop-all"]) => {
            let n = launcher.stop_all();
            commands::write_endpoints_manifest(&commands::build_endpoints(launcher));
            json(200, format!("{{\"stopped\":{n}}}"))
        }

        (Method::Get, ["endpoints"]) => {
            launcher.reap();
            let eps = commands::build_endpoints(launcher);
            commands::write_endpoints_manifest(&eps);
            ok(&eps)
        }

        (Method::Post, ["clear-cache"]) => {
            launcher.reap();
            let accounts = store::list_accounts().unwrap_or_default();
            let mut cleared = 0usize;
            let mut skipped = 0usize;
            let mut freed = 0u64;
            for a in &accounts {
                if launcher.status_of(&a.id) == "running" {
                    skipped += 1;
                    continue;
                }
                freed += store::clear_cache(std::path::Path::new(&a.user_data_dir));
                cleared += 1;
            }
            json(
                200,
                format!(
                    "{{\"cleared\":{cleared},\"skipped_running\":{skipped},\"freed_bytes\":{freed}}}"
                ),
            )
        }

        _ => err(404, "not found"),
    }
}

/// Decode `%XX` escapes in a path segment so non-ASCII account names (e.g. 中文)
/// sent by curl/urllib match the stored name.
fn percent_decode(s: &str) -> String {
    let b = s.as_bytes();
    let hex = |c: u8| -> Option<u8> {
        match c {
            b'0'..=b'9' => Some(c - b'0'),
            b'a'..=b'f' => Some(c - b'a' + 10),
            b'A'..=b'F' => Some(c - b'A' + 10),
            _ => None,
        }
    };
    let mut out = Vec::with_capacity(b.len());
    let mut i = 0;
    while i < b.len() {
        if b[i] == b'%' && i + 2 < b.len() {
            if let (Some(h), Some(l)) = (hex(b[i + 1]), hex(b[i + 2])) {
                out.push(h * 16 + l);
                i += 3;
                continue;
            }
        }
        out.push(b[i]);
        i += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}

/// Pull an optional `{"url": "..."}` field out of a request body.
fn parse_url_field(body: &str) -> Option<String> {
    if body.trim().is_empty() {
        return None;
    }
    let v: serde_json::Value = serde_json::from_str(body).ok()?;
    v.get("url")
        .and_then(|u| u.as_str())
        .filter(|s| !s.is_empty())
        .map(|s| s.to_string())
}
