# CloakAccounts — 开发说明

Tauri 桌面应用：每个账号独占一个浏览器配置（独立指纹 / 代理 / cookie），点击启动后在本机弹出真实有头浏览器窗口。

## 目录结构

```
frontend/                 # React 管理 UI
src-tauri/                # Tauri 2 (Rust) 外壳
  binaries/
    cloak_launcher.py     # 有头浏览器驱动（调用 cloakbrowser）
  src/
    store.rs              # ~/.cloak-accounts/accounts.json
    launcher.rs           # 启动子进程 + PID 登记
    commands/             # Tauri invoke 命令
```

## 开发

```bash
cd frontend && npm install && cd ..
source "$HOME/.cargo/env"
cd src-tauri && cargo tauri dev
```

## 测试

```bash
# 前端
cd frontend && npm test

# Rust
cd src-tauri && cargo test
```

## 数据目录

```
~/.cloak-accounts/
  accounts.json
  profiles/<uuid>/
  tmp/
```
