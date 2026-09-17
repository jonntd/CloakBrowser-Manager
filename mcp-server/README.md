# CloakAccounts MCP 服务

让 **Claude** 连上 CloakAccounts，管理账号并驱动浏览器——列账号、启动/停止、拿到 CDP 地址后直接控制页面。

## 工作原理

```
Claude ──MCP(stdio)──▶ cloak_accounts_mcp.py ──HTTP──▶ CloakAccounts 应用内嵌服务
                                                          (127.0.0.1:8797，唯一进程管理者)
```

- CloakAccounts 桌面应用运行时会内嵌一个本地 HTTP 服务（账号 CRUD、启停、CDP 端点），
  地址写在 `~/.cloak-accounts/server.json`。
- 本 MCP 服务是安全的本地编排层：校验 loopback API、解析唯一账号、等待 CDP 就绪，并可通过 Playwright 读取页面。
- GUI 和 MCP 共享同一个进程管理器，启停状态、CDP 端口分配一致，不会互相冲突。
- 账号返回结果会脱敏，不包含 proxy 凭据、profile 路径或 launch 参数。

## 依赖

```bash
pip install -r mcp-server/requirements.txt
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
| `list_accounts` | 列出脱敏账号及状态（运行中/已停止） |
| `get_account(account)` | 获取单个账号的脱敏信息 |
| `account_context(account?)` | 汇总账号、运行状态、CDP 端点和就绪状态 |
| `start_account(account, url?)` | 启动账号并等待 CDP 就绪 |
| `ensure_account_running(account, url?)` | 幂等复用或启动账号并返回已验证端点 |
| `stop_account(account)` | 停止账号浏览器 |
| `stop_all` | 停止所有运行中的浏览器 |
| `list_endpoints` | 列出运行中浏览器的安全 CDP 元数据 |
| `inspect_page(account, url?)` | 只读读取页面 URL、标题、可见文本和标签页 |
| `navigate_page(account, url)` | 导航账号当前标签页到指定 HTTP(S) 地址 |
| `create_account(name, site?, proxy?, platform?, notes?)` | 新建账号 |
| `update_account(account, updates)` | 更新允许的非敏感账号设置 |
| `delete_account(account, confirm=true)` | 删除账号及 profile，必须显式确认 |
| `clear_account_data(account, confirm=true)` | 清除停止账号的 profile，必须显式确认 |
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
TOK=$(python3 -c "import json,os;print(json.load(open(os.path.expanduser('~/.cloak-accounts/server.json')))['token'])")

curl -H "X-Auth-Token: $TOK" $BASE/accounts
curl -H "X-Auth-Token: $TOK" -X POST $BASE/accounts/<id或名称>/start -d '{"url":"https://example.com"}'
curl -H "X-Auth-Token: $TOK" $BASE/endpoints
curl -H "X-Auth-Token: $TOK" -X POST $BASE/accounts/<id或名称>/stop
```

> 安全：HTTP API 只绑定 `127.0.0.1`，且要求 `server.json`（0600）中的 token
> （`X-Auth-Token` 头）与 loopback Host 头——网页 CSRF / DNS rebinding 无法触达。
> token 随应用每次重启刷新，本 MCP 服务会自动读取并携带。CDP 端口仅本机可连；
> 跨机器用 SSH 隧道，不要转发到公网。
