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
import signal
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


def _chrome_bookmarks_path() -> Path | None:
    """Locate the local Chrome Bookmarks file (Default profile preferred)."""
    if sys.platform == "darwin":
        base = Path.home() / "Library/Application Support/Google/Chrome"
    elif sys.platform.startswith("win"):
        local_app_data = os.environ.get("LOCALAPPDATA")
        if not local_app_data:
            return None
        base = Path(local_app_data) / "Google/Chrome/User Data"
    else:
        base = Path.home() / ".config/google-chrome"
    if not base.is_dir():
        return None
    default = base / "Default" / "Bookmarks"
    if default.exists():
        return default
    profiles = sorted(
        base.glob("Profile */Bookmarks"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return profiles[0] if profiles else None


# Marker stored in each imported node's meta_info. Chromium round-trips
# meta_info untouched, which lets every launch find and replace the nodes
# imported last time (mirroring Chrome-side edits and deletions) without
# touching bookmarks the user created inside the account profile.
_IMPORT_MARK = {"cloak_src": "chrome"}


def _is_imported(node: dict) -> bool:
    return (node.get("meta_info") or {}).get("cloak_src") == "chrome"


def _sanitize_bookmark_node(node: dict) -> dict | None:
    """Copy a Chrome bookmark node, dropping ids/guids so Chromium reassigns them."""
    node_type = node.get("type")
    if node_type == "url":
        if not node.get("url"):
            return None
        return {
            "type": "url",
            "name": node.get("name", ""),
            "url": node["url"],
            "date_added": node.get("date_added", "0"),
            "meta_info": dict(_IMPORT_MARK),
        }
    if node_type == "folder":
        children = [
            c
            for c in (_sanitize_bookmark_node(ch) for ch in node.get("children", []))
            if c
        ]
        return {
            "type": "folder",
            "name": node.get("name", ""),
            "children": children,
            "date_added": node.get("date_added", "0"),
            "date_modified": node.get("date_modified", "0"),
            "meta_info": dict(_IMPORT_MARK),
        }
    return None


def _load_chrome_bookmarks() -> tuple[list, list] | None:
    """Read the local Chrome bookmarks as (bar_children, other_children).

    Returns None when Chrome's bookmarks can't be found or parsed, so callers
    can skip the sync instead of wiping previously imported nodes.
    """
    path = _chrome_bookmarks_path()
    if path is None:
        return None
    try:
        roots = json.loads(path.read_text(encoding="utf-8")).get("roots", {})
    except Exception as exc:
        logger.warning("Failed to read Chrome bookmarks at %s: %s", path, exc)
        return None

    def children_of(root_key: str) -> list:
        raw = roots.get(root_key, {}).get("children", [])
        return [c for c in (_sanitize_bookmark_node(ch) for ch in raw) if c]

    bar = children_of("bookmark_bar")
    other = children_of("other")
    if bar or other:
        logger.info(
            "Importing %d bar + %d other bookmark(s) from Chrome (%s)",
            len(bar),
            len(other),
            path,
        )
    return bar, other


def _strip_imported(nodes: list) -> list:
    """Remove previously imported nodes anywhere in the tree."""
    kept = []
    for node in nodes:
        if _is_imported(node):
            continue
        if node.get("type") == "folder":
            node["children"] = _strip_imported(node.get("children") or [])
        kept.append(node)
    return kept


def _sync_chrome_bookmarks(bookmarks_path: Path) -> None:
    """Mirror Chrome's current bookmarks into an existing profile.

    Replaces the nodes imported on a previous launch with Chrome's current
    state; bookmarks created inside the account profile are preserved. Must
    run while the browser is closed.
    """
    imported = _load_chrome_bookmarks()
    if imported is None:
        return
    chrome_bar, chrome_other = imported

    try:
        data = json.loads(bookmarks_path.read_text(encoding="utf-8"))
        roots = data["roots"]
    except Exception as exc:
        logger.warning("Skipping bookmark sync, unreadable %s: %s", bookmarks_path, exc)
        return

    for root_key, fresh in (("bookmark_bar", chrome_bar), ("other", chrome_other)):
        root = roots.get(root_key)
        if root is None:
            continue
        root["children"] = _strip_imported(root.get("children") or []) + fresh

    data["checksum"] = ""  # Chromium recomputes it on load
    bookmarks_path.write_text(json.dumps(data, indent=2))
    logger.info("Synced Chrome bookmarks into %s", bookmarks_path.parent.parent.name)


def _init_profile_defaults(user_data_dir: Path) -> None:
    """Seed bookmarks/search on first launch; re-sync Chrome bookmarks after."""
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

        chrome_bar, chrome_other = _load_chrome_bookmarks() or ([], [])

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
                    ]
                    + chrome_bar,
                },
                "other": {
                    "type": "folder",
                    "id": "2",
                    "name": "Other bookmarks",
                    "children": chrome_other,
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
    else:
        _sync_chrome_bookmarks(bookmarks_path)

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


# Shared, unpacked extensions dropped here load into EVERY account's browser.
GLOBAL_EXTENSIONS_DIR = Path.home() / ".cloak-accounts" / "extensions"


def _resolve_extensions(account: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Return (extension_dirs, remaining_launch_args).

    Combines unpacked extensions from the global shared dir with any
    ``--load-extension=`` paths in the account's launch_args, so every extension
    ends up in a single ``--load-extension`` flag (Chromium honours only one).
    """
    paths: list[str] = []
    if GLOBAL_EXTENSIONS_DIR.exists():
        for d in sorted(GLOBAL_EXTENSIONS_DIR.iterdir()):
            if d.is_dir() and (d / "manifest.json").exists():
                paths.append(str(d))

    remaining: list[str] = []
    for arg in account.get("launch_args") or []:
        if arg.startswith("--load-extension="):
            for p in arg.split("=", 1)[1].split(","):
                if p and p not in paths:
                    paths.append(p)
        else:
            remaining.append(arg)
    return paths, remaining


def _ensure_developer_mode(user_data_dir: Path) -> None:
    """Turn on chrome://extensions Developer Mode by seeding the profile prefs
    (must run while the browser is not running)."""
    default_dir = user_data_dir / "Default"
    default_dir.mkdir(parents=True, exist_ok=True)
    prefs_path = default_dir / "Preferences"
    prefs: dict = {}
    if prefs_path.exists():
        try:
            prefs = json.loads(prefs_path.read_text())
        except Exception:
            prefs = {}
    prefs.setdefault("extensions", {}).setdefault("ui", {})["developer_mode"] = True
    prefs_path.write_text(json.dumps(prefs))


# Pure-cache directories that are safe to delete on close. Deleting these frees
# disk without touching login state: Cookies, "Local Storage", IndexedDB,
# "Login Data" and "Network/Cookies" are deliberately NOT in this list.
CACHE_SUBPATHS = (
    "Default/Cache",
    "Default/Code Cache",
    "Default/GPUCache",
    "Default/DawnCache",
    "Default/DawnGraphiteCache",
    "Default/DawnWebGPUCache",
    "Default/GrShaderCache",
    "Default/Service Worker/CacheStorage",
    "Default/Service Worker/ScriptCache",
    "GPUCache",
    "ShaderCache",
    "GrShaderCache",
    "component_crx_cache",
)


def _clean_cache_keep_cookies(user_data_dir: Path) -> None:
    """Delete HTTP/GPU/code caches after the browser closes, keeping cookies.

    Must run only once the browser has fully shut down (file locks released),
    otherwise Chromium may recreate or partially hold these directories.
    """
    import shutil

    cleared = 0
    for rel in CACHE_SUBPATHS:
        p = user_data_dir / rel
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)
            if not p.exists():
                cleared += 1
    logger.info(
        "Cleared %d cache dir(s), kept cookies for %s", cleared, user_data_dir.name
    )


# ---------------------------------------------------------------------------
# Launch
# ---------------------------------------------------------------------------


async def run(account: dict[str, Any], start_url: str | None, cdp_port: int | None = None) -> None:
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
    _ensure_developer_mode(user_data_dir)

    extra_args = _build_fingerprint_args(account)
    # Shared + per-account unpacked extensions — passed via cloakbrowser's
    # extension_paths (it emits the correct --disable-extensions-except +
    # --load-extension pair; a bare --load-extension alone doesn't load).
    ext_paths, other_args = _resolve_extensions(account)
    extra_args += other_args
    if ext_paths:
        logger.info("Loading %d extension(s): %s", len(ext_paths), ext_paths)

    # Prefer the port assigned by the desktop app (collision-free across accounts);
    # fall back to probing when run standalone.
    if cdp_port is None:
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
        extension_paths=ext_paths or None,
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

    # Shut down cleanly on SIGTERM/SIGINT (sent by the desktop app's stop/stop-all
    # or quit) so the browser flushes cookies/session to the profile dir before
    # the process exits, instead of being hard-killed mid-write.
    loop = asyncio.get_running_loop()
    for _sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(_sig, closed.set)
        except (NotImplementedError, RuntimeError):
            pass  # signal handlers unsupported on this loop/platform

    try:
        await closed.wait()
    except asyncio.CancelledError:
        pass
    finally:
        try:
            await context.close()
        except Exception as exc:
            logger.debug("context.close failed: %s", exc)
        # Browser is fully closed now → safe to purge caches while keeping cookies.
        try:
            _clean_cache_keep_cookies(user_data_dir)
        except Exception as exc:
            logger.debug("cache cleanup failed: %s", exc)
        logger.info("Browser closed for account %s", account.get("id"))


def main() -> None:
    parser = argparse.ArgumentParser(description="CloakBrowser headed launcher")
    parser.add_argument(
        "--account-file",
        required=True,
        help="Path to JSON file containing the account config",
    )
    parser.add_argument("--url", default=None, help="Optional start URL override")
    parser.add_argument(
        "--cdp-port",
        type=int,
        default=None,
        help="CDP remote-debugging port assigned by the app (avoids probing/collisions)",
    )
    args = parser.parse_args()

    path = Path(args.account_file)
    if not path.exists():
        logger.error("Account file not found: %s", path)
        sys.exit(1)

    account = json.loads(path.read_text(encoding="utf-8"))
    try:
        asyncio.run(run(account, args.url, args.cdp_port))
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        logger.exception("Launcher failed: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
