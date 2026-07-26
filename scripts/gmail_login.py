#!/usr/bin/env python3
"""Gmail / Google Workspace 自动登录 —— 驱动 CloakAccounts 的账号浏览器登录 Gmail。

流程(已在 xai003@mel.pub 上验证可用):
  1) 邮箱页:填 #identifierId → 点 #identifierNext(“下一步”)
  2) 密码页:填 input[name="Passwd"] → 点 #passwordNext
  3) 首次登录欢迎/条款页:点“我了解”按钮
  4) 进入 https://mail.google.com/…

拟人化(降低风控):
  - 邮箱/密码都是逐字符输入 + 每键随机延迟(不是瞬间 fill),偶尔更长“思考”停顿。
  - 各步之间随机抖动的停顿(_pause),用 --slow 整体放慢(默认 1.5)。

关键坑(踩过):
  - 邮箱框是 input#identifierId,type 是 "text" 不是 "email"。
  - 用 Playwright 的 locator/get_by_role(自动等待、自动重试),不要用
    query_selector + ElementHandle.click —— 页面一跳转,handle 就“detached from DOM”。
  - 每步之间留足等待,别抢在导航前操作。

⚠️ 风控(重要):
  Google 对“同一 IP 短时间登录多个新账号”极敏感,会触发
  “验证是不是你本人 / 手机验证 / 临时封禁(rejected)”。批量登录务必:
    - 账号之间间隔足够长(分钟级,不是秒级);
    - 尽量每个账号配不同代理(独立出口 IP);
    - 遇到 challenge/blocked 人工处理,不要重试轰炸。

用法:
  # 账号浏览器已在运行时,自动发现端口并登录:
  python gmail_login.py --account xxx@mel.pub --password xxx

  # 让脚本先通过 API 启动该账号浏览器再登录:
  python gmail_login.py --account xxx@mel.pub --password xxx --start

  # 指定 CDP 端口:
  python gmail_login.py --port 5100 --account xxx@mel.pub --password xxx

依赖: pip install playwright   (CloakAccounts 应用需在运行)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import urllib.request
from pathlib import Path

from playwright.async_api import Page, async_playwright

BASE_DEFAULT = "http://127.0.0.1:8797"
LOGIN_URL = "https://accounts.google.com/ServiceLogin?service=mail"


async def _pause(base: float, slow: float) -> None:
    """Sleep for `base` seconds, scaled by `slow` and randomly jittered ±30–40%."""
    await asyncio.sleep(base * slow * random.uniform(0.7, 1.4))


async def _type_human(page: Page, selector: str, text: str, slow: float) -> None:
    """Focus a field and type it character-by-character with randomized per-key
    delays (plus occasional longer 'thinking' pauses), instead of an instant fill."""
    loc = page.locator(selector).first
    await loc.click()
    await asyncio.sleep(random.uniform(0.25, 0.6) * slow)
    for i, ch in enumerate(text):
        await page.keyboard.type(ch)
        await asyncio.sleep(random.uniform(0.08, 0.24) * slow)
        # every so often, pause a bit longer as a human would
        if i and i % random.randint(4, 7) == 0:
            await asyncio.sleep(random.uniform(0.3, 0.7) * slow)
    await asyncio.sleep(random.uniform(0.4, 0.9) * slow)


def _api_base() -> str:
    try:
        return json.loads(
            (Path.home() / ".cloak-accounts" / "server.json").read_text()
        )["base_url"]
    except Exception:
        return BASE_DEFAULT


def _api(method: str, path: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(_api_base() + path, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as r:
        t = r.read().decode()
        return json.loads(t) if t.strip() else {}


def resolve_id(account: str) -> str | None:
    for a in _api("GET", "/accounts"):
        if a["id"] == account or a["name"] == account:
            return a["id"]
    return None


def resolve_port(account: str) -> int | None:
    """CDP port of a running account (by name or id)."""
    for e in _api("GET", "/endpoints"):
        if e["id"] == account or e["name"] == account:
            return e["cdp_port"]
    return None


async def gmail_login(page: Page, email: str, password: str, slow: float = 1.0) -> str:
    """Log a Workspace account into Gmail on an already-open page. Returns a status."""
    if "mail.google.com" in page.url:
        return "ALREADY_LOGGED_IN"
    if "accounts.google.com" not in page.url:
        await page.goto(LOGIN_URL, wait_until="domcontentloaded")
    await _pause(2.5, slow)

    # 1) email  (identifier field is type=text, id=identifierId)
    await page.wait_for_selector("#identifierId", state="visible", timeout=20000)
    await _type_human(page, "#identifierId", email, slow)
    await _pause(1.0, slow)
    await page.locator("#identifierNext").first.click(timeout=15000)

    # 2) password (name=Passwd appears after the email step)
    await page.wait_for_selector('input[name="Passwd"]', state="visible", timeout=25000)
    await _pause(1.6, slow)
    await _type_human(page, 'input[name="Passwd"]', password, slow)
    await _pause(1.0, slow)
    await page.locator("#passwordNext").first.click(timeout=15000)

    # 3) resolve outcome: welcome/ToS ("我了解") -> Gmail, or challenge/blocked
    for _ in range(24):
        await _pause(1.6, slow)
        u = page.url
        if "mail.google.com" in u:
            return "LOGGED_IN"
        if "challenge" in u:
            return "CHALLENGE_VERIFY"   # 需人工:验证身份/手机
        if "rejected" in u or "deniedsigningin" in u:
            return "BLOCKED"            # 被拒(风控)
        if "speedbump" in u or "termsofservice" in u:
            # 首次登录欢迎/条款页 —— 点“我了解”(含多语言兜底)
            for name in ("我了解", "I understand", "Accept", "I agree", "继续"):
                try:
                    await page.get_by_role("button", name=name).click(timeout=3000)
                    break
                except Exception:
                    continue
            await asyncio.sleep(2 * slow)
    return "TIMEOUT:" + page.url.split("?")[0]


async def run(account: str, password: str, port: int | None, do_start: bool, slow: float) -> str:
    if do_start:
        aid = resolve_id(account)
        if not aid:
            return "NO_ACCOUNT"
        _api("POST", f"/accounts/{aid}/start", {"url": LOGIN_URL})
        for _ in range(20):
            await asyncio.sleep(1)
            port = resolve_port(aid)
            if port:
                break
        await asyncio.sleep(4)  # let the window settle before driving it
    if port is None:
        port = resolve_port(account)
    if port is None:
        return "NO_PORT (账号浏览器未运行?先 --start 或用 API 启动)"

    async with async_playwright() as pw:
        b = await pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        ctx = b.contexts[0]
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        try:
            return await gmail_login(page, email=account, password=password, slow=slow)
        except Exception as e:
            return "ERROR:" + str(e).splitlines()[0][:80]


def main() -> None:
    ap = argparse.ArgumentParser(description="Gmail 自动登录(驱动 CloakAccounts 账号浏览器)")
    ap.add_argument("--account", required=True, help="账号名(邮箱)或 id")
    ap.add_argument("--password", required=True)
    ap.add_argument("--port", type=int, default=None, help="CDP 端口(默认自动发现)")
    ap.add_argument("--start", action="store_true", help="先经 API 启动该账号浏览器")
    ap.add_argument("--slow", type=float, default=1.5, help="放慢倍数(越大越慢越像真人,默认1.5;风控严时可设 2~3)")
    args = ap.parse_args()
    result = asyncio.run(run(args.account, args.password, args.port, args.start, args.slow))
    print(f"{args.account} -> {result}")


if __name__ == "__main__":
    main()
