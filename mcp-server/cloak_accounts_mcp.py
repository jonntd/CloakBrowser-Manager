#!/usr/bin/env python3
"""MCP bridge for the local CloakAccounts account and browser service.

The desktop app owns account data and browser processes. This server provides a
small, safe orchestration layer: it resolves accounts, waits for CDP readiness,
and optionally reads the currently visible page through Playwright over CDP.
It never exposes the raw proxy, profile path, or launch arguments to the model.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("cloak-accounts")

SERVER_INFO = Path.home() / ".cloak-accounts" / "server.json"
DEFAULT_BASE = "http://127.0.0.1:8797"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
ACCOUNT_ID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$")
MAX_PAGE_TEXT = 12_000


class CloakAccountsError(RuntimeError):
    """An actionable error suitable for an MCP tool response."""


def _server_info() -> dict[str, Any]:
    try:
        value = json.loads(SERVER_INFO.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CloakAccountsError(
            f"无法读取 CloakAccounts 服务配置 {SERVER_INFO}：{exc}。请先启动桌面应用。"
        ) from None
    if not isinstance(value, dict):
        raise CloakAccountsError("CloakAccounts server.json 格式无效。请重启桌面应用。")
    return value


def _base_url() -> str:
    value = _server_info().get("base_url") or DEFAULT_BASE
    if not isinstance(value, str):
        raise CloakAccountsError("server.json 的 base_url 必须是字符串。")
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme != "http" or parsed.hostname not in LOOPBACK_HOSTS:
        raise CloakAccountsError("出于安全原因，CloakAccounts API 只允许使用本机 HTTP 地址。")
    if parsed.username or parsed.password or parsed.query or parsed.fragment or not parsed.netloc:
        raise CloakAccountsError("server.json 的 base_url 包含不允许的凭据或参数。")
    return value.rstrip("/")


def _token() -> str:
    value = _server_info().get("token")
    if not isinstance(value, str) or not value:
        raise CloakAccountsError("server.json 缺少 API token。请重启桌面应用。")
    return value


def _req(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    url = _base_url() + (path if path.startswith("/") else f"/{path}")
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("X-Auth-Token", _token())
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:2000]
        if exc.code == 401:
            raise CloakAccountsError(
                "CloakAccounts 拒绝了请求（401）。请确认桌面应用仍在运行，并重新读取当前 server.json。"
            ) from None
        raise CloakAccountsError(f"CloakAccounts API 返回 HTTP {exc.code}: {detail}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise CloakAccountsError(f"无法连接 CloakAccounts 本地服务：{exc}") from None
    if not raw:
        return {}
    try:
        return json.loads(raw.decode())
    except (UnicodeError, json.JSONDecodeError):
        raise CloakAccountsError("CloakAccounts API 返回了无效 JSON。") from None


def _safe_account(account: dict[str, Any]) -> dict[str, Any]:
    """Return only fields that are useful for orchestration and safe to expose."""
    allowed = (
        "id", "name", "site", "notes", "tags", "platform", "timezone", "locale",
        "screen_width", "screen_height", "hardware_concurrency", "humanize",
        "human_preset", "geoip", "color_scheme", "created_at", "updated_at", "status",
    )
    return {key: account.get(key) for key in allowed if key in account}


def _accounts() -> list[dict[str, Any]]:
    value = _req("GET", "/accounts")
    if not isinstance(value, list):
        raise CloakAccountsError("CloakAccounts 返回的账号列表格式无效。")
    return [item for item in value if isinstance(item, dict)]


def _resolve_id(account: str) -> str:
    if not isinstance(account, str) or not account.strip():
        raise CloakAccountsError("account 必须是非空的账号 id 或名称。")
    matches = [a for a in _accounts() if a.get("id") == account or a.get("name") == account]
    if not matches:
        raise CloakAccountsError(f"找不到账号「{account}」。请先调用 list_accounts。")
    if len(matches) > 1:
        candidates = ", ".join(str(a.get("id")) for a in matches)
        raise CloakAccountsError(f"账号名称「{account}」不唯一，请改用 account id：{candidates}")
    return str(matches[0]["id"])


def _validate_url(url: str | None, *, required: bool = False) -> str | None:
    if url is None or not url.strip():
        if required:
            raise CloakAccountsError("页面 URL 不能为空，且必须是完整的 http(s) URL。")
        return None
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise CloakAccountsError("页面 URL 必须是完整的 http(s) URL。")
    return url


def _endpoints() -> list[dict[str, Any]]:
    value = _req("GET", "/endpoints")
    if not isinstance(value, list):
        raise CloakAccountsError("CloakAccounts 返回的端点列表格式无效。")
    return [item for item in value if isinstance(item, dict)]


def _endpoint_for(account_id: str) -> dict[str, Any] | None:
    return next((e for e in _endpoints() if e.get("id") == account_id), None)


def _cdp_ready(cdp_url: str) -> dict[str, Any]:
    parsed = urllib.parse.urlsplit(cdp_url)
    if parsed.scheme != "http" or parsed.hostname not in LOOPBACK_HOSTS:
        raise CloakAccountsError("浏览器 CDP 端点不是受信任的本机地址。")
    try:
        with urllib.request.urlopen(cdp_url.rstrip("/") + "/json/version", timeout=2) as response:
            data = json.loads(response.read().decode())
    except (urllib.error.URLError, TimeoutError, OSError, UnicodeError, json.JSONDecodeError):
        raise CloakAccountsError("浏览器已启动但 CDP 尚未就绪。请稍后重试。") from None
    if not isinstance(data, dict) or not data.get("webSocketDebuggerUrl"):
        raise CloakAccountsError("CDP 返回的浏览器信息不完整。")
    return data


def _wait_for_endpoint(account_id: str, timeout: float = 15.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        endpoint = _endpoint_for(account_id)
        if endpoint and isinstance(endpoint.get("cdp_url"), str):
            try:
                version = _cdp_ready(endpoint["cdp_url"])
                return {**endpoint, "ready": True, "browser": version.get("Browser")}
            except CloakAccountsError as exc:
                last_error = str(exc)
        time.sleep(0.25)
    raise CloakAccountsError(last_error or "浏览器启动超时，未发现可用的 CDP 端点。")


def _safe_cdp_url(endpoint: dict[str, Any]) -> dict[str, Any]:
    return {
        "account_id": endpoint.get("id"),
        "name": endpoint.get("name"),
        "cdp_url": endpoint.get("cdp_url"),
        "cdp_port": endpoint.get("cdp_port"),
    }


@mcp.tool()
def list_accounts() -> list[dict[str, Any]]:
    """List accounts with safe metadata and current running status."""
    return [_safe_account(account) for account in _accounts()]


@mcp.tool()
def get_account(account: str) -> dict[str, Any]:
    """Get one account by unique name or id, excluding secrets and local paths."""
    return _safe_account(_req("GET", f"/accounts/{urllib.parse.quote(_resolve_id(account), safe='')}"))


@mcp.tool()
def account_context(account: str | None = None) -> dict[str, Any] | list[dict[str, Any]]:
    """Combine safe account metadata, endpoint state, and CDP readiness."""
    accounts = list_accounts()
    if account is not None:
        selected_id = _resolve_id(account)
        accounts = [item for item in accounts if item.get("id") == selected_id]
    endpoints = {str(item.get("id")): item for item in _endpoints()}
    result = []
    for item in accounts:
        endpoint = endpoints.get(str(item.get("id")))
        context = {"account": item, "browser": {"status": item.get("status", "stopped")}}
        if endpoint:
            try:
                version = _cdp_ready(str(endpoint["cdp_url"]))
                context["browser"] = {**_safe_cdp_url(endpoint), "status": "ready", "browser": version.get("Browser")}
            except CloakAccountsError as exc:
                context["browser"] = {**_safe_cdp_url(endpoint), "status": "starting", "error": str(exc)}
        result.append(context)
    return result[0] if account is not None else result


@mcp.tool()
def start_account(account: str, url: str | None = None) -> dict[str, Any]:
    """Start an account, open an optional URL, and wait until CDP is ready."""
    target = _validate_url(url)
    account_id = _resolve_id(account)
    endpoint = _endpoint_for(account_id)
    if endpoint:
        ready = _wait_for_endpoint(account_id)
        if target:
            navigation = navigate_page(account_id, target)
            return {**ready, "navigation": navigation}
        return ready
    body = {"url": target} if target else {}
    _req("POST", f"/accounts/{urllib.parse.quote(account_id, safe='')}/start", body)
    return _wait_for_endpoint(account_id)


@mcp.tool()
def ensure_account_running(account: str, url: str | None = None) -> dict[str, Any]:
    """Idempotently reuse or start an account and return a verified CDP endpoint."""
    return start_account(account, url)


@mcp.tool()
def stop_account(account: str) -> dict[str, Any]:
    """Stop one account browser. Repeated stop is reported as an idempotent result."""
    account_id = _resolve_id(account)
    try:
        result = _req("POST", f"/accounts/{urllib.parse.quote(account_id, safe='')}/stop")
    except CloakAccountsError as exc:
        if "未在运行" not in str(exc):
            raise
        return {"account_id": account_id, "status": "already_stopped"}
    return {"account_id": account_id, "status": "stopped", **(result if isinstance(result, dict) else {})}


@mcp.tool()
def stop_all() -> dict[str, Any]:
    """Stop every running account browser."""
    return _req("POST", "/stop-all")


@mcp.tool()
def list_endpoints() -> list[dict[str, Any]]:
    """List only safe CDP endpoint metadata for running account browsers."""
    return [_safe_cdp_url(endpoint) for endpoint in _endpoints()]


@mcp.tool()
def create_account(
    name: str,
    site: str | None = None,
    proxy: str | None = None,
    platform: str = "windows",
    notes: str | None = None,
) -> dict[str, Any]:
    """Create an account. Proxy is accepted for compatibility but never returned."""
    if not name.strip() or len(name.strip()) > 120:
        raise CloakAccountsError("账号名称必须为 1-120 个字符。")
    if platform not in {"windows", "macos", "linux"}:
        raise CloakAccountsError("platform 必须是 windows、macos 或 linux。")
    body: dict[str, Any] = {"name": name.strip(), "platform": platform}
    for key, value in (("site", site), ("proxy", proxy), ("notes", notes)):
        if value:
            body[key] = value
    return _safe_account(_req("POST", "/accounts", body))


@mcp.tool()
def update_account(account: str, updates: dict[str, Any]) -> dict[str, Any]:
    """Update non-secret account settings by unique name or id."""
    account_id = _resolve_id(account)
    if not isinstance(updates, dict) or not updates:
        raise CloakAccountsError("updates 必须是非空对象。")
    allowed = {"name", "site", "notes", "tags", "timezone", "locale", "platform", "humanize", "human_preset", "geoip", "color_scheme", "screen_width", "screen_height", "hardware_concurrency", "fingerprint_seed"}
    unknown = set(updates) - allowed
    if unknown:
        raise CloakAccountsError(f"不允许更新字段：{', '.join(sorted(unknown))}")
    return _safe_account(_req("PATCH", f"/accounts/{urllib.parse.quote(account_id, safe='')}", updates))


@mcp.tool()
def delete_account(account: str, confirm: bool = False) -> dict[str, Any]:
    """Delete an account and its profile; requires explicit confirm=true."""
    if not confirm:
        raise CloakAccountsError("删除账号会清除其 profile 数据，请再次调用并传 confirm=true。")
    account_id = _resolve_id(account)
    _req("DELETE", f"/accounts/{urllib.parse.quote(account_id, safe='')}")
    return {"account_id": account_id, "status": "deleted"}


@mcp.tool()
def clear_account_data(account: str, confirm: bool = False) -> dict[str, Any]:
    """Clear one stopped account's profile; requires explicit confirm=true."""
    if not confirm:
        raise CloakAccountsError("清除账号数据会删除该 profile 的 cookies 和登录状态，请再次调用并传 confirm=true。")
    account_id = _resolve_id(account)
    _req(
        "POST",
        f"/accounts/{urllib.parse.quote(account_id, safe='')}/clear-data",
        {"confirm": True},
    )
    return {"account_id": account_id, "status": "data_cleared"}


@mcp.tool()
def clear_all_cache() -> dict[str, Any]:
    """Clear cache for stopped accounts while keeping cookies and login state."""
    return _req("POST", "/clear-cache")


def _inspect_page_async(cdp_url: str, url: str | None = None) -> dict[str, Any]:
    async def inspect() -> dict[str, Any]:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise CloakAccountsError("inspect_page 需要安装 playwright：pip install -r mcp-server/requirements.txt") from exc
        async with async_playwright() as playwright:
            browser = None
            try:
                browser = await playwright.chromium.connect_over_cdp(cdp_url, timeout=5000)
                pages = [page for context in browser.contexts for page in context.pages]
                if not pages:
                    raise CloakAccountsError("浏览器已连接，但没有可用标签页。")
                page = next((item for item in pages if url and item.url == url), pages[0])
                text = " ".join((await page.locator("body").inner_text(timeout=5000)).split())
                return {"url": page.url, "title": await page.title(), "text": text[:MAX_PAGE_TEXT], "truncated": len(text) > MAX_PAGE_TEXT, "tabs": [{"url": item.url, "title": await item.title()} for item in pages]}
            finally:
                if browser is not None:
                    await browser.close()

    return asyncio.run(inspect())


@mcp.tool()
def inspect_page(account: str, url: str | None = None) -> dict[str, Any]:
    """Read the active page through the account-scoped CDP connection; no actions are sent."""
    endpoint = _wait_for_endpoint(_resolve_id(account))
    return _inspect_page_async(str(endpoint["cdp_url"]), url)


@mcp.tool()
def navigate_page(account: str, url: str) -> dict[str, Any]:
    """Navigate one account's active page to an explicit http(s) URL and return its title."""
    target = _validate_url(url, required=True)
    endpoint = _wait_for_endpoint(_resolve_id(account))

    async def navigate() -> dict[str, Any]:
        from playwright.async_api import async_playwright
        async with async_playwright() as playwright:
            browser = await playwright.chromium.connect_over_cdp(str(endpoint["cdp_url"]), timeout=5000)
            try:
                pages = [page for context in browser.contexts for page in context.pages]
                if not pages:
                    raise CloakAccountsError("浏览器没有可用标签页。")
                page = pages[0]
                await page.goto(target, wait_until="domcontentloaded", timeout=30_000)
                return {"account_id": endpoint.get("account_id"), "url": page.url, "title": await page.title()}
            finally:
                await browser.close()

    return asyncio.run(navigate())


if __name__ == "__main__":
    mcp.run()
