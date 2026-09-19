"""本地 CloakAccounts HTTP API 的共享客户端(仅限本机回环地址)。

MCP 服务器和 scripts/ 下的辅助脚本都必须只把 API token 发给桌面应用生成的
本机服务,因此 server.json 读取、base_url 校验和带认证的请求统一在这里实现,
避免多处实现漂移导致安全边界不一致。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

SERVER_INFO_PATH = Path.home() / ".cloak-accounts" / "server.json"
DEFAULT_PORT = 8797
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class LocalApiError(RuntimeError):
    """本地 API 配置无效或请求失败;消息面向最终用户,可直接展示。"""


def read_server_info(path: Path | None = None) -> dict[str, Any]:
    resolved = path if path is not None else SERVER_INFO_PATH
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LocalApiError(
            f"无法读取 CloakAccounts 服务配置 {resolved}：{exc}。请先启动桌面应用。"
        ) from None
    if not isinstance(value, dict):
        raise LocalApiError("CloakAccounts server.json 格式无效。请重启桌面应用。")
    return value


def validate_base_url(value: object) -> str:
    """校验 base_url 只允许本机 http 根路径,返回去尾斜杠的规范地址。"""
    if not isinstance(value, str):
        raise LocalApiError("server.json 的 base_url 必须是字符串。")
    parsed = urllib.parse.urlsplit(value)
    try:
        port = parsed.port
    except ValueError:
        raise LocalApiError("server.json 的 base_url 端口无效。") from None
    if parsed.scheme != "http" or parsed.hostname not in LOOPBACK_HOSTS:
        raise LocalApiError("出于安全原因，CloakAccounts API 只允许使用本机 HTTP 地址。")
    if port != DEFAULT_PORT or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise LocalApiError("server.json 的 base_url 必须是本机 8797 端口，且不能包含凭据或参数。")
    if parsed.path not in {"", "/"} or not parsed.netloc:
        raise LocalApiError("server.json 的 base_url 必须指向本机 API 根路径。")
    return value.rstrip("/")


def validate_token(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise LocalApiError("server.json 缺少 API token。请重启桌面应用。")
    return value


def api_config(path: Path | None = None) -> tuple[str, str]:
    """读取并校验 server.json,返回 (base_url, token)。"""
    info = read_server_info(path)
    return validate_base_url(info.get("base_url")), validate_token(info.get("token"))


def request_json(
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    *,
    config: tuple[str, str] | None = None,
    timeout: float = 30.0,
) -> Any:
    """带 X-Auth-Token 的本地 API 请求,返回解析后的 JSON(空响应返回 {})。

    path 中的动态段(如账号 id)由调用方先做 urllib.parse.quote;
    不传 config 时每次调用都重新读取 server.json,桌面应用重启换 token 后无需重启调用方。
    """
    base, token = config if config is not None else api_config()
    url = base + (path if path.startswith("/") else f"/{path}")
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("X-Auth-Token", token)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:2000]
        if exc.code == 401:
            raise LocalApiError(
                "CloakAccounts 拒绝了请求（401）。请确认桌面应用仍在运行，并重新读取当前 server.json。"
            ) from None
        raise LocalApiError(f"CloakAccounts API 返回 HTTP {exc.code}: {detail}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LocalApiError(f"无法连接 CloakAccounts 本地服务：{exc}") from None
    if not raw:
        return {}
    try:
        return json.loads(raw.decode())
    except (UnicodeError, json.JSONDecodeError):
        raise LocalApiError("CloakAccounts API 返回了无效 JSON。") from None
