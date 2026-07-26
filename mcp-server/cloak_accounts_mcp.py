#!/usr/bin/env python3
"""MCP server for CloakAccounts.

Lets Claude manage CloakAccounts accounts and drive their browsers. It forwards
to the local HTTP API embedded in the CloakAccounts desktop app, discovered via
``~/.cloak-accounts/server.json``.

The CloakAccounts app must be running (it hosts the API + owns the browsers).

Run:  python cloak_accounts_mcp.py     (stdio transport)
Deps: pip install mcp
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("cloak-accounts")

SERVER_INFO = Path.home() / ".cloak-accounts" / "server.json"
DEFAULT_BASE = "http://127.0.0.1:8797"


def _base_url() -> str:
    try:
        return json.loads(SERVER_INFO.read_text())["base_url"]
    except Exception:
        return DEFAULT_BASE


def _req(method: str, path: str, body: dict | None = None) -> Any:
    url = _base_url() + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            text = r.read().decode()
            return json.loads(text) if text.strip() else {}
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode()}") from None
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"Cannot reach the CloakAccounts app ({e.reason}). Is it running?"
        ) from None


def _resolve_id(account: str) -> str:
    """Resolve an account given by name or id to its id (URL-safe uuid)."""
    for a in _req("GET", "/accounts"):
        if a["id"] == account or a["name"] == account:
            return a["id"]
    raise RuntimeError(f"No account named or with id '{account}'")


@mcp.tool()
def list_accounts() -> list:
    """List all CloakAccounts accounts with their status (running/stopped),
    platform, proxy and fingerprint seed."""
    return _req("GET", "/accounts")


@mcp.tool()
def start_account(account: str, url: str | None = None) -> dict:
    """Launch the browser for an account (by name or id). Optionally open `url`.
    Returns the CDP endpoint (cdp_url) you can then control via Chrome DevTools
    Protocol (Playwright connect_over_cdp / chrome-cdp)."""
    acc_id = _resolve_id(account)
    return _req("POST", f"/accounts/{acc_id}/start", {"url": url} if url else {})


@mcp.tool()
def stop_account(account: str) -> dict:
    """Stop the browser for an account (by name or id). Closes gracefully,
    flushing cookies and purging caches."""
    return _req("POST", f"/accounts/{_resolve_id(account)}/stop")


@mcp.tool()
def stop_all() -> dict:
    """Stop every running account browser."""
    return _req("POST", "/stop-all")


@mcp.tool()
def list_endpoints() -> list:
    """List CDP endpoints (id, name, cdp_port, cdp_url) for all running account
    browsers. Use a cdp_url to drive that account's browser over CDP."""
    return _req("GET", "/endpoints")


@mcp.tool()
def create_account(
    name: str,
    site: str | None = None,
    proxy: str | None = None,
    platform: str = "windows",
) -> dict:
    """Create a new account. `platform` is windows | macos | linux."""
    body: dict[str, Any] = {"name": name, "platform": platform}
    if site:
        body["site"] = site
    if proxy:
        body["proxy"] = proxy
    return _req("POST", "/accounts", body)


@mcp.tool()
def clear_all_cache() -> dict:
    """Clear browser cache for all stopped accounts (keeps cookies / login)."""
    return _req("POST", "/clear-cache")


if __name__ == "__main__":
    mcp.run()
