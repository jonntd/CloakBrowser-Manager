#!/usr/bin/env python3
"""CloakBrowser headed launcher for the local desktop app.

Usage:
  python cloak_launcher.py --account-file /path/to/account.json [--url URL]

Reads account JSON from --account-file, launches a headed CloakBrowser
window bound to that account's user_data_dir, keeps running until the
window is closed, then exits with code 0.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import socket
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger("cloak_launcher")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)

BASE_CDP_PORT = 5100
CDP_PORT_RANGE = 100


# ---------------------------------------------------------------------------
# Proxy / fingerprint helpers for CloakBrowser launch args
# ---------------------------------------------------------------------------


def _normalize_proxy(raw: str) -> str:
    """Convert common proxy formats to http://user:pass@host:port."""
    if raw.startswith(("http://", "https://", "socks5://")):
        return raw
    parts = raw.split(":")
    if len(parts) == 4:
        host, port, user, passwd = parts
        return f"http://{user}:{passwd}@{host}:{port}"
    if len(parts) == 2:
        return f"http://{raw}"
    return raw


def _validate_proxy(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https", "socks5"):
        raise ValueError(
            f"Invalid proxy scheme '{parsed.scheme}'. Must be http, https, or socks5."
        )
    if not parsed.hostname:
        raise ValueError(f"Proxy URL missing hostname: {url}")
    if not parsed.port:
        raise ValueError(f"Proxy URL missing port: {url}")


def _init_profile_defaults(user_data_dir: Path) -> None:
    """Set up bookmarks and DuckDuckGo search on first launch."""
    default_dir = user_data_dir / "Default"
    default_dir.mkdir(parents=True, exist_ok=True)

    bookmarks_path = default_dir / "Bookmarks"
    if not bookmarks_path.exists():
        ts = str(int(time.time() * 1_000_000))
        _id = 1

        def bm(name: str, url: str) -> dict:
            nonlocal _id
            _id += 1
            return {
                "type": "url",
                "id": str(_id),
                "name": name,
                "url": url,
                "date_added": ts,
            }

        def folder(name: str, children: list) -> dict:
            nonlocal _id
            _id += 1
            return {
                "type": "folder",
                "id": str(_id),
                "name": name,
                "children": children,
                "date_added": ts,
                "date_modified": ts,
            }

        bookmarks = {
            "checksum": "",
            "roots": {
                "bookmark_bar": {
                    "type": "folder",
                    "id": "1",
                    "name": "Bookmarks bar",
                    "date_added": ts,
                    "date_modified": ts,
                    "children": [
                        folder(
                            "Detection Tests",
                            [
                                bm("Rebrowser Bot Detector", "https://bot-detector.rebrowser.net/"),
                                bm("Incolumitas", "https://bot.incolumitas.com/"),
                                bm("SannySort", "https://bot.sannysoft.com/"),
                                bm("BrowserScan Bot", "https://www.browserscan.net/bot-detection"),
                                bm("FingerprintJS Demo", "https://demo.fingerprint.com/web-scraping"),
                                bm("Pixelscan", "https://pixelscan.net/fingerprint-check"),
                                bm("CreepJS", "https://abrahamjuliot.github.io/creepjs/"),
                                bm("fingerprint-scan", "https://fingerprint-scan.com/"),
                                bm("DeviceInfo Bot", "https://deviceandbrowserinfo.com/are_you_a_bot"),
                            ],
                        ),
                        folder(
                            "Fingerprint",
                            [
                                bm("BrowserLeaks Canvas", "https://browserleaks.com/canvas"),
                                bm("BrowserLeaks WebGL", "https://browserleaks.com/webgl"),
                                bm("BrowserLeaks Fonts", "https://browserleaks.com/fonts"),
                                bm("BrowserLeaks JS", "https://browserleaks.com/javascript"),
                                bm("FingerprintJS OSS", "https://fingerprintjs.github.io/fingerprintjs/"),
                                bm("Audio FP", "https://audiofingerprint.openwpm.com/"),
                                bm("DeviceInfo", "https://deviceandbrowserinfo.com/info_device"),
                            ],
                        ),
                        folder(
                            "Headers & TLS",
                            [
                                bm("httpbin headers", "https://httpbin.org/headers"),
                                bm("httpbin IP", "https://httpbin.org/ip"),
                                bm("TLS Fingerprint", "https://tls.browserleaks.com/"),
                            ],
                        ),
                        folder(
                            "reCAPTCHA",
                            [
                                bm(
                                    "Google v3 Demo",
                                    "https://recaptcha-demo.appspot.com/recaptcha-v3-request-scores.php",
                                ),
                                bm("2captcha v3", "https://2captcha.com/demo/recaptcha-v3"),
                                bm("Turnstile", "https://peet.ws/turnstile-test/non-interactive.html"),
                            ],
                        ),
                    ],
                },
                "other": {
                    "type": "folder",
                    "id": "2",
                    "name": "Other bookmarks",
                    "children": [],
                },
                "synced": {
                    "type": "folder",
                    "id": "3",
                    "name": "Mobile bookmarks",
                    "children": [],
                },
            },
            "version": 1,
        }
        bookmarks_path.write_text(json.dumps(bookmarks, indent=2))
        logger.info("Created default bookmarks for %s", user_data_dir.name)

    prefs_path = default_dir / "Preferences"
    if not prefs_path.exists():
        prefs = {
            "default_search_provider_data": {
                "template_url_data": {
                    "keyword": "duckduckgo.com",
                    "short_name": "DuckDuckGo",
                    "url": "https://duckduckgo.com/?q={searchTerms}",
                    "suggestions_url": "https://duckduckgo.com/ac/?q={searchTerms}&type=list",
                    "favicon_url": "https://duckduckgo.com/favicon.ico",
                }
            },
            "default_search_provider": {"enabled": True},
        }
        prefs_path.write_text(json.dumps(prefs, indent=2))
        logger.info("Set DuckDuckGo as default search for %s", user_data_dir.name)


def _build_fingerprint_args(account: dict[str, Any]) -> list[str]:
    args: list[str] = [
        "--disable-infobars",
        "--test-type",
    ]

    seed = account.get("fingerprint_seed")
    if seed is not None:
        args.append(f"--fingerprint={seed}")

    platform = account.get("platform")
    if platform:
        args.append(f"--fingerprint-platform={platform}")

    vendor = account.get("gpu_vendor")
    if vendor:
        args.append(f"--fingerprint-gpu-vendor={vendor}")

    renderer = account.get("gpu_renderer")
    if renderer:
        args.append(f"--fingerprint-gpu-renderer={renderer}")

    hw = account.get("hardware_concurrency")
    if hw is not None:
        args.append(f"--fingerprint-hardware-concurrency={hw}")

    sw = account.get("screen_width")
    sh = account.get("screen_height")
    if sw:
        args.append(f"--fingerprint-screen-width={sw}")
    if sh:
        args.append(f"--fingerprint-screen-height={sh}")

    return args


def _allocate_cdp_port() -> int:
    for i in range(CDP_PORT_RANGE):
        port = BASE_CDP_PORT + i
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(
        f"No free CDP ports in range {BASE_CDP_PORT}-{BASE_CDP_PORT + CDP_PORT_RANGE - 1}"
    )


def _clean_lock_files(user_data_dir: Path) -> None:
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        (user_data_dir / name).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Launch
# ---------------------------------------------------------------------------


async def run(account: dict[str, Any], start_url: str | None) -> None:
    try:
        from cloakbrowser import launch_persistent_context_async
    except ImportError:
        logger.error(
            "cloakbrowser is not installed. Run: pip install 'cloakbrowser[geoip]'"
        )
        sys.exit(2)

    user_data_dir = Path(account["user_data_dir"])
    user_data_dir.mkdir(parents=True, exist_ok=True)
    _clean_lock_files(user_data_dir)
    _init_profile_defaults(user_data_dir)

    extra_args = _build_fingerprint_args(account)
    extra_args += list(account.get("launch_args") or [])
    cdp_port = _allocate_cdp_port()
    extra_args.append(f"--remote-debugging-port={cdp_port}")

    raw_proxy = account.get("proxy") or None
    proxy = _normalize_proxy(raw_proxy) if raw_proxy else None
    if proxy:
        _validate_proxy(proxy)

    screen_w = int(account.get("screen_width") or 1920)
    screen_h = int(account.get("screen_height") or 1080)

    logger.info(
        "Launching headed browser for account %s (seed=%s, cdp=%d, dir=%s)",
        account.get("name") or account.get("id"),
        account.get("fingerprint_seed"),
        cdp_port,
        user_data_dir,
    )

    # Print CDP port so parent process can parse if needed
    print(f"CDP_PORT={cdp_port}", flush=True)
    print(f"PID={os.getpid()}", flush=True)

    context = await launch_persistent_context_async(
        user_data_dir=str(user_data_dir),
        headless=False,
        proxy=proxy,
        args=extra_args,
        timezone=account.get("timezone") or None,
        locale=account.get("locale") or None,
        humanize=bool(account.get("humanize", False)),
        human_preset=account.get("human_preset") or "default",
        geoip=bool(account.get("geoip", False)),
        color_scheme=account.get("color_scheme") or None,
        user_agent=account.get("user_agent") or None,
        viewport={"width": screen_w, "height": max(screen_h - 133, 600)},
    )

    # Open start URL if provided
    url = start_url or account.get("site") or None
    if url and not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    if url:
        try:
            pages = context.pages
            page = pages[0] if pages else await context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        except Exception as exc:
            logger.warning("Failed to open start URL %s: %s", url, exc)

    # Keep alive until the browser context closes
    closed = asyncio.Event()

    def _on_close() -> None:
        closed.set()

    context.on("close", lambda: _on_close())

    try:
        await closed.wait()
    except asyncio.CancelledError:
        pass
    finally:
        try:
            await context.close()
        except Exception as exc:
            logger.debug("context.close failed: %s", exc)
        logger.info("Browser closed for account %s", account.get("id"))


def main() -> None:
    parser = argparse.ArgumentParser(description="CloakBrowser headed launcher")
    parser.add_argument(
        "--account-file",
        required=True,
        help="Path to JSON file containing the account config",
    )
    parser.add_argument("--url", default=None, help="Optional start URL override")
    args = parser.parse_args()

    path = Path(args.account_file)
    if not path.exists():
        logger.error("Account file not found: %s", path)
        sys.exit(1)

    account = json.loads(path.read_text(encoding="utf-8"))
    try:
        asyncio.run(run(account, args.url))
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        logger.exception("Launcher failed: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
