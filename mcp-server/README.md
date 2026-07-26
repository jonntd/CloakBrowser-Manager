# CloakAccounts MCP 服务

让 **Claude** 连上 CloakAccounts，管理账号并驱动浏览器——列账号、启动/停止、拿到 CDP 地址后直接控制页面。

## 工作原理

```
Claude ──MCP(stdio)──▶ cloak_accounts_mcp.py ──HTTP──▶ CloakAccounts 应用内嵌服务
                                                          (127.0.0.1:8797，唯一进程管理者)
```

- CloakAccounts 桌面应用运行时会内嵌一个本地 HTTP 服务（账号 CRUD、启停、CDP 端点），
  地址写在 `~/.cloak-accounts/server.json`。
- 本 MCP 服务是一层薄转发，把 Claude 的工具调用转成 HTTP 请求。
- GUI 和 MCP 共享同一个进程管理器，启停状态、CDP 端口分配一致，不会互相冲突。

## 依赖

```bash
pip install mcp
```

（CloakAccounts 应用需处于运行状态——它托管 API 并持有浏览器进程。）

## 接入 Claude Code

```bash
claude mcp add cloak-accounts -- python3 /Volumes/date/CloakBrowser-Manager/mcp-server/cloak_accounts_mcp.py
```

或手动写进 MCP 配置：

```json
{
  "mcpServers": {
    "cloak-accounts": {
      "command": "python3",
      "args": ["/Volumes/date/CloakBrowser-Manager/mcp-server/cloak_accounts_mcp.py"]
    }
  }
}
```

## 可用工具

| 工具 | 说明 |
|------|------|
| `list_accounts` | 列出所有账号及状态（运行中/已停止） |
| `start_account(account, url?)` | 按名称或 id 启动账号浏览器，返回其 `cdp_url` |
| `stop_account(account)` | 停止账号浏览器（优雅关闭，刷 cookie、清缓存） |
| `stop_all` | 停止所有运行中的浏览器 |
| `list_endpoints` | 列出运行中浏览器的 CDP 端点，供直接控制 |
| `create_account(name, site?, proxy?, platform?)` | 新建账号 |
| `clear_all_cache` | 清理所有已停止账号的缓存（保留 cookie） |

## 用法示例（直接对 Claude 说）

> "列出我的 CloakAccounts 账号。"
> "启动账号「ge002」，打开小红书。"
> "启动账号「方法」，然后连上它的浏览器，告诉我是否已登录 twitter。"
> "停止所有浏览器。"

启动账号后，`start_account` / `list_endpoints` 会返回 `cdp_url`（如 `http://127.0.0.1:5100`）。
Claude 再用 CDP（Playwright `connect_over_cdp` 或 chrome-cdp）控制该账号浏览器的页面。

## 直接用 HTTP API（不经 MCP）

```bash
BASE=$(python3 -c "import json,os;print(json.load(open(os.path.expanduser('~/.cloak-accounts/server.json')))['base_url'])")
curl $BASE/accounts
curl -X POST $BASE/accounts/<id或名称>/start -d '{"url":"https://example.com"}'
curl $BASE/endpoints
curl -X POST $BASE/accounts/<id或名称>/stop
```

> 安全：HTTP API 与 CDP 端点都只绑定 `127.0.0.1`，无鉴权。不要转发到公网；跨机器用 SSH 隧道。
