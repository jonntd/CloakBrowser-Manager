//! Local HTTP account-management API, embedded in the app so an MCP server (and
//! thus Claude) can manage accounts and drive browsers while the GUI runs. It
//! shares the one `Launcher` with the Tauri commands, so start/stop state and
//! CDP port allocation stay consistent across the GUI and the API.
//!
//! Bound to 127.0.0.1 only. Every request must carry the per-run bearer token
//! from `~/.cloak-accounts/server.json` (owner-only file) and a loopback Host
//! header — this keeps web-page CSRF and DNS-rebinding from reaching an API
//! that can launch browsers and delete profile data. Do not forward the port
//! off-host.

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
    // One random bearer token per app run. Requiring it (plus the Host check
    // below) is what stops a malicious web page from forging POSTs to this
    // API: it cannot read server.json, and cross-origin requests cannot set
    // custom headers without a CORS preflight we never answer.
    let token = uuid::Uuid::new_v4().to_string();
    write_server_info(DEFAULT_PORT, &token);
    eprintln!("[http] account API listening on http://{addr}");

    for mut req in server.incoming_requests() {
        let resp = match authorize(req.headers(), DEFAULT_PORT, &token) {
            Ok(()) => handle(&launcher, &mut req),
            Err((code, msg)) => err(code, msg),
        };
        let _ = req.respond(resp);
    }
}

/// Advertise the API address + auth token so the MCP server can auto-discover
/// both. Owner-only permissions (0600 on Unix) since the token gates the API.
fn write_server_info(port: u16, token: &str) {
    let path = store::data_dir().join("server.json");
    let body = serde_json::json!({
        "port": port,
        "base_url": format!("http://127.0.0.1:{port}"),
        "token": token,
    });
    let _ = std::fs::create_dir_all(store::data_dir());
    let _ = store::write_private(&path, &body.to_string());
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

fn header_value<'a>(headers: &'a [Header], name: &str) -> Option<&'a str> {
    headers
        .iter()
        .find(|h| h.field.as_str().as_str().eq_ignore_ascii_case(name))
        .map(|h| h.value.as_str())
}

/// Length-independent byte comparison so token checks don't leak timing.
fn ct_eq(a: &[u8], b: &[u8]) -> bool {
    if a.len() != b.len() {
        return false;
    }
    a.iter()
        .zip(b.iter())
        .fold(0u8, |diff, (x, y)| diff | (x ^ y))
        == 0
}

type AuthError = (u16, &'static str);

/// Gate every request on a loopback Host header and the per-run bearer token.
/// The Host check blocks DNS-rebinding browsers (whose Host would be the
/// attacker's domain); the token blocks same-origin CSRF from web pages.
fn authorize(headers: &[Header], port: u16, token: &str) -> Result<(), AuthError> {
    let host = header_value(headers, "Host").unwrap_or("");
    let allowed = [format!("127.0.0.1:{port}"), format!("localhost:{port}")];
    if !allowed.iter().any(|h| h == host) {
        return Err((403, "invalid host header"));
    }
    let presented = header_value(headers, "X-Auth-Token").unwrap_or("");
    if !ct_eq(presented.as_bytes(), token.as_bytes()) {
        return Err((401, "missing or invalid auth token (see server.json)"));
    }
    Ok(())
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
                match store::clear_cache(std::path::Path::new(&a.user_data_dir)) {
                    Ok(bytes) => {
                        freed += bytes;
                        cleared += 1;
                    }
                    Err(e) => return err(500, &e),
                }
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

#[cfg(test)]
mod tests {
    use super::*;

    fn hdr(name: &str, value: &str) -> Header {
        Header::from_bytes(name.as_bytes(), value.as_bytes()).unwrap()
    }

    #[test]
    fn authorize_accepts_loopback_host_and_matching_token() {
        let headers = [hdr("Host", "127.0.0.1:8797"), hdr("X-Auth-Token", "tok-1")];
        assert!(authorize(&headers, 8797, "tok-1").is_ok());
        let headers = [hdr("Host", "localhost:8797"), hdr("X-Auth-Token", "tok-1")];
        assert!(authorize(&headers, 8797, "tok-1").is_ok());
    }

    #[test]
    fn authorize_rejects_missing_or_wrong_token() {
        let headers = [hdr("Host", "127.0.0.1:8797")];
        assert_eq!(authorize(&headers, 8797, "tok-1").unwrap_err().0, 401);
        let headers = [
            hdr("Host", "127.0.0.1:8797"),
            hdr("X-Auth-Token", "wrong-token"),
        ];
        assert_eq!(authorize(&headers, 8797, "tok-1").unwrap_err().0, 401);
    }

    #[test]
    fn authorize_rejects_rebound_or_missing_host() {
        // DNS-rebinding (attacker's domain as Host), even with a valid token.
        let headers = [
            hdr("Host", "evil.example:8797"),
            hdr("X-Auth-Token", "tok-1"),
        ];
        assert_eq!(authorize(&headers, 8797, "tok-1").unwrap_err().0, 403);
        // No Host header at all (HTTP/1.0 style) — refuse.
        let headers = [hdr("X-Auth-Token", "tok-1")];
        assert_eq!(authorize(&headers, 8797, "tok-1").unwrap_err().0, 403);
    }

    #[test]
    fn ct_eq_matches_only_identical_inputs() {
        assert!(ct_eq(b"abc", b"abc"));
        assert!(!ct_eq(b"abc", b"abd"));
        assert!(!ct_eq(b"abc", b"ab"));
        assert!(ct_eq(b"", b""));
    }
}
