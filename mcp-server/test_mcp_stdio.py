"""MCP stdio 真实集成测试:通过子进程握手、枚举工具并验证错误映射。

不依赖桌面应用运行:子进程的 HOME 指向临时目录,server.json 缺失,
用于验证“后端不可达”在 MCP 协议层表现为可操作的 isError 结果。
"""
import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

import pytest

SERVER = Path(__file__).resolve().parent / "cloak_accounts_mcp.py"
PROTOCOL_VERSION = "2024-11-05"

EXPECTED_TOOLS = {
    "list_accounts",
    "get_account",
    "account_context",
    "start_account",
    "ensure_account_running",
    "stop_account",
    "stop_all",
    "list_endpoints",
    "create_account",
    "update_account",
    "delete_account",
    "clear_account_data",
    "clear_all_cache",
    "inspect_page",
    "navigate_page",
}


class StdioMcp:
    """Minimal MCP client speaking newline-delimited JSON-RPC over stdio."""

    def __init__(self, proc: subprocess.Popen):
        self._proc = proc
        self._queue: queue.Queue = queue.Queue()
        self._next_id = 0
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        for line in self._proc.stdout:
            line = line.strip()
            if line:
                try:
                    self._queue.put(json.loads(line))
                except json.JSONDecodeError:
                    continue

    def request(self, method: str, params: dict | None = None) -> dict:
        self._next_id += 1
        message: dict = {"jsonrpc": "2.0", "id": self._next_id, "method": method}
        if params is not None:
            message["params"] = params
        self._send(message)
        return self._recv_response(self._next_id)

    def notify(self, method: str, params: dict | None = None) -> None:
        message: dict = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self._send(message)

    def _send(self, message: dict) -> None:
        assert self._proc.stdin is not None and self._proc.poll() is None, "MCP 子进程已退出"
        self._proc.stdin.write((json.dumps(message) + "\n").encode())
        self._proc.stdin.flush()

    def _recv_response(self, request_id: int, timeout: float = 20.0) -> dict:
        while True:
            message = self._queue.get(timeout=timeout)
            if message.get("id") == request_id:
                return message
            # 通知与乱序消息(不应出现)跳过,继续等待对应响应。


@pytest.fixture
def mcp_stdio(tmp_path):
    env = {**os.environ, "HOME": str(tmp_path)}
    proc = subprocess.Popen(
        [sys.executable, str(SERVER)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        cwd=str(SERVER.parent),
    )
    client = StdioMcp(proc)
    yield client
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def _handshake(client: StdioMcp) -> dict:
    result = client.request(
        "initialize",
        {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "pytest-stdio", "version": "0.0.0"},
        },
    )
    assert "error" not in result, result
    client.notify("notifications/initialized")
    return result["result"]


def test_initialize_returns_cloak_accounts_server(mcp_stdio):
    result = _handshake(mcp_stdio)
    assert result["serverInfo"]["name"] == "cloak-accounts"
    assert result["protocolVersion"] == PROTOCOL_VERSION


def test_tools_list_exposes_orchestration_surface(mcp_stdio):
    _handshake(mcp_stdio)
    tools = mcp_stdio.request("tools/list")["result"]["tools"]
    names = {tool["name"] for tool in tools}
    assert EXPECTED_TOOLS <= names


def test_tool_call_without_backend_maps_to_is_error(mcp_stdio):
    _handshake(mcp_stdio)
    result = mcp_stdio.request("tools/call", {"name": "list_accounts", "arguments": {}})
    assert "error" not in result, result
    payload = result["result"]
    assert payload.get("isError") is True
    text = "".join(c.get("text", "") for c in payload.get("content", []))
    assert "server.json" in text
    assert "token" not in text  # 错误消息不得泄露 token


def test_unknown_tool_maps_to_is_error(mcp_stdio):
    _handshake(mcp_stdio)
    # FastMCP 对未知工具返回 isError 工具结果(而非协议级 error),
    # 模型侧看到的是可操作的文本错误。
    result = mcp_stdio.request("tools/call", {"name": "no_such_tool", "arguments": {}})
    assert "error" not in result, result
    payload = result["result"]
    assert payload.get("isError") is True
    text = "".join(c.get("text", "") for c in payload.get("content", []))
    assert "Unknown tool" in text
