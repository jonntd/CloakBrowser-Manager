# CloakAccounts

本地账号浏览器管理器（Tauri 桌面应用）。

为每个**账号**创建并独占一个独立浏览器配置（指纹 / 代理 / cookie 互不共用）。
点击「启动」后在本机弹出真实有头浏览器窗口——不是 Docker，不是 noVNC。

## 功能

- 账号 CRUD：名称、目标站点、备注、彩色标签
- 每账号独立 `user_data_dir` + 指纹种子 + 代理 / 时区 / 平台等配置
- 一键启动 / 停止有头 CloakBrowser 窗口
- 配置持久化到本地 JSON：`~/.cloak-accounts/accounts.json`
- 不存储登录凭据——在浏览器窗口内自行登录，cookie 自动持久化

## 依赖

1. **Rust**（[rustup](https://rustup.rs)）
2. **Node.js 20+**
3. **Python 3** + CloakBrowser：
   ```bash
   pip install 'cloakbrowser[geoip]'
   ```
4. macOS：Xcode Command Line Tools（`xcode-select --install`）

## 开发启动

```bash
# 前端依赖
cd frontend && npm install && cd ..

# 首次安装 Tauri CLI
source "$HOME/.cargo/env"
cargo install tauri-cli --version "^2" --locked

# 启动桌面应用（同时起 Vite 热更新）
cd src-tauri
cargo tauri dev
```

或从 frontend 目录：

```bash
cd frontend
npm run tauri:dev
```

## 使用流程

1. 打开应用 → 新建账号（名称必填，站点 / 代理 / 指纹可选）
2. 选中账号 → 点「启动浏览器」
3. 桌面弹出独立浏览器窗口，在窗口内自行登录
4. 可同时启动多个账号，各自独立窗口与 cookie
5. 「停止」关闭窗口；「删除」同时清除其用户数据目录

## 数据目录

```
~/.cloak-accounts/
  accounts.json          # 账号元数据
  endpoints.json         # 运行中浏览器的 CDP 端点清单（自动更新）
  profiles/<uuid>/       # 每账号独立 Chromium 用户数据
  logs/<uuid>.log        # 每账号 launcher 日志（含 CDP_PORT）
  tmp/<uuid>.json        # 启动时临时传给 launcher 的配置
```

## 用 Claude / 外部工具控制浏览器（CDP）

每个启动的浏览器都开着 **CDP（Chrome DevTools Protocol）** 端口，可被 Claude、
Playwright、Puppeteer 或 IDE 的浏览器调试工具接管。

**自动发现**：运行中的浏览器会实时写入 `~/.cloak-accounts/endpoints.json`：

```json
[
  { "id": "…", "name": "账号A", "cdp_port": 5100, "cdp_url": "http://127.0.0.1:5100" }
]
```

读这个文件即可拿到每个账号浏览器的 CDP 地址。也可在应用内通过 `list_endpoints`
命令获取同样的数据。

**连接方式**：

```bash
# 验证端点 / 列出页面
curl http://127.0.0.1:5100/json/version
curl http://127.0.0.1:5100/json
```

```js
// Playwright
const browser = await chromium.connectOverCDP("http://127.0.0.1:5100");

// Puppeteer
const browser = await puppeteer.connect({ browserURL: "http://127.0.0.1:5100" });
```

- **Claude**：读取 `endpoints.json` 拿到端口，用 `chrome-cdp` 能力连到该端口驱动页面。
- 端点默认只绑 `127.0.0.1`（仅本机）。跨机器控制请用 SSH 端口转发，**不要**把它暴露到公网——CDP 无鉴权，能连端口即可完全控制浏览器（含读取 cookie）。

## 让 Claude 管理账号（MCP 服务 + HTTP API）

应用运行时会内嵌一个本地 **HTTP 账号 API**（`127.0.0.1:8797`，地址写在
`~/.cloak-accounts/server.json`），GUI 与该 API 共享同一个进程管理器。

在其上提供了一个 **MCP 服务**，让 Claude 直接以工具方式管理账号（列出 / 启动 /
停止 / 拿 CDP 地址 / 新建），启动后再经 CDP 控制对应账号的浏览器。

一次性接入：

```bash
claude mcp add cloak-accounts -- python3 mcp-server/cloak_accounts_mcp.py
```

之后直接对 Claude 说「启动账号 X 并打开某站」即可。详见
[mcp-server/README.md](mcp-server/README.md)。

也可不经 MCP，直接调 HTTP API：

```bash
curl http://127.0.0.1:8797/accounts
curl -X POST http://127.0.0.1:8797/accounts/<id或名称>/start -d '{"url":"https://example.com"}'
curl http://127.0.0.1:8797/endpoints
curl -X POST http://127.0.0.1:8797/accounts/<id或名称>/stop
```

## 架构

| 层 | 技术 | 职责 |
|----|------|------|
| UI | React 19 + Tailwind | 账号列表 / 表单 / 状态 |
| 外壳 | Tauri 2 (Rust) | JSON 存储、进程管理、命令 |
| 驱动 | `src-tauri/binaries/cloak_launcher.py` | 调用 cloakbrowser 弹有头窗口 |
| 引擎 | CloakBrowser | 每账号独立指纹与会话 |

## 构建发布包

```bash
cd src-tauri
cargo tauri build
```

产物在 `src-tauri/target/release/bundle/`。

## 许可证

- **本应用源码** — MIT。见 [LICENSE](LICENSE)。
- **CloakBrowser 二进制** — 可免费使用，禁止再分发。见 [BINARY-LICENSE.md](BINARY-LICENSE.md)。
